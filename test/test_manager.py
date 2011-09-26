# -*- mode: Python; coding: utf-8 -*-

from random import randint
from struct import unpack
from select import select
from threading import Thread, Lock
import unittest

import xcb
from xcb.xproto import *

from event import *
from manager import WindowManager, compress
from xutil import *

class WindowManagerThread(Thread):
    def __init__(self, wm_class=WindowManager):
        super(WindowManagerThread, self).__init__()
        self.conn = xcb.connect()
        self.wm = wm_class(self.conn)

    def run(self):
        try:
            self.wm.event_loop()
        except:
            pass

    def stop(self):
        """Abort the window manager by closing its connection. This method
        must not be called from the WM's thread, as it calls join."""
        self.conn.flush()
        self.conn.disconnect()
        self.join()

class TestWindow(EventHandler):
    """A simple top-level window."""

    def __init__(self, conn, geometry, event_mask=0):
        event_mask |= (EventMask.StructureNotify | EventMask.PropertyChange)

        self.conn = conn
        self.atoms = AtomCache(conn, ["WM_STATE"])
        self.id = conn.generate_id()
        self.mapped = False
        self.managed = False
        self.geometry = None
        self.above_sibling = None
        self.override_redirect = False
        self.synthetic_configure_notify = False

        setup = conn.get_setup()
        screen = conn.pref_screen
        root = setup.roots[screen].root
        depth = setup.roots[screen].root_depth
        visual = setup.roots[screen].root_visual
        white = setup.roots[screen].white_pixel

        conn.core.CreateWindowChecked(depth, self.id, root,
                                      geometry.x, geometry.y,
                                      geometry.width, geometry.height,
                                      geometry.border_width,
                                      WindowClass.InputOutput,
                                      visual,
                                      CW.BackPixel | CW.EventMask,
                                      [white, event_mask]).check()

    def map(self):
        self.conn.core.MapWindowChecked(self.id).check()

    def resize(self, geometry):
        assert isinstance(geometry, Geometry)
        self.conn.core.ConfigureWindowChecked(self.id,
                                              (ConfigWindow.X |
                                               ConfigWindow.Y |
                                               ConfigWindow.Width |
                                               ConfigWindow.Height |
                                               ConfigWindow.BorderWidth),
                                              geometry).check()
        return geometry

    def destroy(self):
        self.conn.core.DestroyWindowChecked(self.id).check()

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        assert event.window == self.id
        self.mapped = True

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        assert event.window == self.id
        self.mapped = False

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        assert event.window == self.id
        self.geometry = Geometry(event.x, event.y,
                                 event.width, event.height,
                                 event.border_width)
        self.above_sibling = event.above_sibling
        self.override_redirect = event.override_redirect
        self.synthetic_configure_notify = is_synthetic_event(event)

    @handler(PropertyNotifyEvent)
    def handle_property_notify(self, event):
        assert event.window == self.id
        if (event.state == Property.NewValue and
            event.atom == self.atoms["WM_STATE"]):
            self.managed = True

class WMTestCase(unittest.TestCase):
    """A test fixture that establishes an X connection and starts the WM in
    a separate thread."""

    wm_class = WindowManager

    def setUp(self):
        self.conn = xcb.connect()
        self.windows = {} # test windows, indexed by id
        self.wm_thread = WindowManagerThread(self.wm_class)
        self.wm_thread.start()

    def tearDown(self):
        for window in self.windows.values():
            window.destroy()
        self.conn.flush()
        self.wm_thread.stop()

    def add_window(self, window):
        """Create and return a new client window."""
        assert isinstance(window, TestWindow)
        self.windows[window.id] = window
        return window

    def event_loop(self, test=lambda: False, max_timeouts=5):
        """A simple client event loop."""
        self.conn.flush()
        timeouts = 0
        rlist = [self.conn.get_file_descriptor()]
        wlist = []
        xlist = []
        while timeouts < max_timeouts:
            # Process pending events from XCB.
            while True:
                event = self.conn.poll_for_event()
                if not event:
                    break
                try:
                    self.windows[event.window].handle_event(event)
                except KeyError:
                    self.fail("Event received for unknown window")
            if test():
                return True
            # Wait for more events, but only for a second.
            r, w, x = select(rlist, wlist, xlist, 1)
            if not r and not w and not x:
                timeouts += 1
        self.fail()

class TestWMStartup(WMTestCase):
    # We'll override WMTestCase's setUp method so that it doesn't start the
    # WM for us.
    def setUp(self):
        self.conn = xcb.connect()
        self.windows = {}

    def test_startup(self):
        """Ensure that the window manager adopts extant top-level windows"""

        # Create a few top-level windows. Just for fun, we'll map two and
        # leave one more withdrawn; that last will not be managed.
        w1 = self.add_window(TestWindow(self.conn, Geometry(0, 0, 100, 100, 1)))
        w2 = self.add_window(TestWindow(self.conn, Geometry(10, 10, 10, 10, 1)))
        w3 = self.add_window(TestWindow(self.conn, Geometry(20, 20, 20, 20, 1)))
        w1.map()
        w2.map()
        self.event_loop(lambda: w1.mapped and w2.mapped and not w3.mapped)
        self.assertFalse(w1.managed or w2.managed or w3.managed)

        # Now fire up the window manager.
        self.wm_thread = WindowManagerThread()
        self.wm_thread.start()

        self.event_loop(lambda: w1.managed and w2.managed and not w3.managed)

class TestWMClientMoveResize(WMTestCase):
    def setUp(self):
        super(TestWMClientMoveResize, self).setUp()
        self.initial_geometry = Geometry(0, 0, 100, 100, 5)
        self.w = self.add_window(TestWindow(self.conn, self.initial_geometry))
        self.w.map()
        
    def test_no_change(self):
        """Configure a top-level window without changing its size or position"""
        self.w.resize(self.initial_geometry)
        geometry = self.initial_geometry.translate(5, 5) # adjust for border
        self.event_loop(lambda: (self.w.geometry == geometry and
                                 self.w.synthetic_configure_notify))

    def test_move(self):
        """Move a top-level window without changing its size"""
        self.w.resize(self.initial_geometry.translate(5, 5))
        geometry = self.initial_geometry.translate(10, 10) # adjust for border
        self.event_loop(lambda: (self.w.geometry == geometry and
                                 self.w.synthetic_configure_notify))

    def test_resize(self):
        """Resize and move a top-level window"""
        geometry = Geometry(5, 5, 50, 50, 5)
        self.w.resize(geometry)
        # The real ConfigureNotify event reflects the actual border width.
        self.event_loop(lambda: (self.w.geometry == geometry and
                                 not self.w.synthetic_configure_notify))

class EventLoopTester(WindowManager):
    """A window manager that records the number of ConfigureNotify events
    that it receives on its client windows."""

    def __init__(self, *args, **kwargs):
        super(EventLoopTester, self).__init__(*args, **kwargs)
        self.events_received = 0

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        self.events_received += 1

class TestWMEventLoop(WMTestCase):
    wm_class = EventLoopTester

    def jiggle_window(self, n=100):
        # Realize a client window.
        g = Geometry(0, 0, 100, 100, 5)
        w = self.add_window(TestWindow(self.conn, g))
        w.map()

        # Move the window around a bunch of times.
        for i in range(n):
            w.resize(g.translate(randint(1, 100), randint(1, 100)))

    def test_event_loop(self):
        """Test the window manager's event loop"""
        n = 100
        self.jiggle_window(n)
        self.event_loop(lambda: self.wm_thread.wm.events_received == n)

class EventCompressionTester(EventLoopTester):
    @handler(ConfigureNotifyEvent)
    @compress
    def handle_configure_notify(self, event):
        raise UnhandledEvent(event) # decline; pass to the next handler

class TestWMEventLoopWithCompression(TestWMEventLoop):
    wm_class = EventCompressionTester

    def test_event_loop(self):
        """Test event compression"""
        n = 100
        self.jiggle_window(n)
        self.event_loop(lambda: self.wm_thread.wm.events_received == 1)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
