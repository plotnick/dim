# -*- mode: Python; coding: utf-8 -*-

from random import randint
from struct import unpack
from select import select
from time import sleep
from threading import Thread
import unittest

import xcb
from xcb.xproto import *
import xcb.xtest

from atom import AtomCache
from event import *
from geometry import *
from keymap import *
from manager import WindowManager, compress
from xutil import *

class EventType(object):
    """X event type codes."""
    KeyPress = 2
    KeyRelease = 3
    ButtonPress = 4
    ButtonRelease = 5
    MotionNotify = 6

class WindowManagerThread(Thread):
    def __init__(self, wm_class, screen):
        assert issubclass(wm_class, WindowManager)
        assert isinstance(screen, int)

        super(WindowManagerThread, self).__init__()
        self.wm = wm_class(None, screen)

    def run(self):
        try:
            self.wm.start()
        finally:
            self.wm.shutdown()

class TestWindow(EventHandler):
    """A simple top-level window."""

    def __init__(self, conn, screen, geometry, event_mask=0):
        assert isinstance(conn, xcb.Connection)
        assert isinstance(screen, SCREEN)

        self.conn = conn
        self.screen = screen
        self.atoms = AtomCache(conn, ["WM_STATE"])
        self.id = conn.generate_id()
        self.mapped = False
        self.managed = False
        self.geometry = None
        self.above_sibling = None
        self.override_redirect = False
        self.synthetic_configure_notify = False

        event_mask |= (EventMask.StructureNotify | EventMask.PropertyChange)
        conn.core.CreateWindowChecked(self.screen.root_depth, self.id,
                                      self.screen.root,
                                      geometry.x, geometry.y,
                                      geometry.width, geometry.height,
                                      geometry.border_width,
                                      WindowClass.InputOutput,
                                      self.screen.root_visual,
                                      CW.BackPixel | CW.EventMask,
                                      [self.screen.white_pixel,
                                       event_mask]).check()

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

    # The class of window manager to instantiate. Subclasses may override
    # this to test other window manager classes.
    wm_class = WindowManager

    def setUp(self, screen=None, start_wm=True):
        self.conn = xcb.connect()
        self.xtest = self.conn(xcb.xtest.key)
        if screen is None:
            screen = self.conn.pref_screen
        self.screen = self.conn.get_setup().roots[screen]
        self.atoms = AtomCache(self.conn)
        self.modmap = ModifierMap(self.conn)
        self.keymap = KeyboardMap(self.conn, None, self.modmap)
        self.buttons = PointerMap(self.conn)
        self.windows = {} # test windows, indexed by id
        self.wm_thread = WindowManagerThread(self.wm_class, screen)
        if start_wm:
            self.wm_thread.start()

    def tearDown(self):
        for window in self.windows.values():
            window.destroy()
        self.conn.flush()
        if self.wm_thread.is_alive():
            self.kill_wm()
            self.wm_thread.join()

    def kill_wm(self):
        """Ask the window manager to exit."""
        send_client_message(self.conn, self.screen.root,
                            EventMask.StructureNotify,
                            8, self.atoms["WM_EXIT"], [0] * 20)
        self.conn.flush()

    def add_window(self, window):
        """Track a new top-level window."""
        assert isinstance(window, TestWindow)
        self.windows[window.id] = window
        return window

    def create_window(self, geometry):
        """Create a new top-level window with the given geometry."""
        return TestWindow(self.conn, self.screen, geometry)

    def fake_input(self, type, detail, root_x=0, root_y=0):
        """Simulate user input."""
        self.xtest.FakeInputChecked(type, detail, Time.CurrentTime,
                                    self.screen.root, root_x, root_y, 0).check()
        sleep(0.0001) # block & yield control

    def warp_pointer(self, x, y):
        """Warp the pointer to the given coordinates relative to the origin
        of the root window."""
        self.conn.core.WarpPointerChecked(0, self.screen.root, 0, 0, 0, 0,
                                          int16(x), int16(y)).check()

    def event_loop(self, test=lambda: False, max_timeouts=50):
        """A simple client event loop."""
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
                if hasattr(event, "window"):
                    try:
                        self.windows[event.window].handle_event(event)
                    except KeyError:
                        self.fail("Event received for unknown window")
            if test():
                return True

            self.conn.flush()

            # Wait for more events, but only for a few milliseconds.
            r, w, x = select(rlist, wlist, xlist, 0.001)
            if not r and not w and not x:
                timeouts += 1
        self.fail("timed out")

class TestWMStartup(WMTestCase):
    def setUp(self):
        super(TestWMStartup, self).setUp(start_wm=False)

    def test_startup(self):
        """Ensure that the window manager adopts extant top-level windows"""
        # Create a few top-level windows. Just for fun, we'll map two and
        # leave one more withdrawn; that last will not be managed.
        w1 = self.add_window(self.create_window(Geometry(0, 0, 100, 100, 1)))
        w2 = self.add_window(self.create_window(Geometry(10, 10, 10, 10, 1)))
        w3 = self.add_window(self.create_window(Geometry(20, 20, 20, 20, 1)))
        w1.map()
        w2.map()

        # Now fire up the window manager.
        self.wm_thread.start()

        self.event_loop(lambda: w1.managed and w2.managed and not w3.managed)

class TestWMClientMoveResize(WMTestCase):
    def setUp(self):
        super(TestWMClientMoveResize, self).setUp()
        self.initial_geometry = Geometry(0, 0, 100, 100, 5)
        self.w = self.add_window(self.create_window(self.initial_geometry))
        self.w.map()
        
    def test_no_change(self):
        """Configure a top-level window without changing its size or position"""
        self.w.resize(self.initial_geometry)
        geometry = self.initial_geometry + (5, 5) # adjust for border
        self.event_loop(lambda: (self.w.geometry == geometry and
                                 self.w.synthetic_configure_notify))

    def test_move(self):
        """Move a top-level window without changing its size"""
        self.w.resize(self.initial_geometry + (5, 5))
        geometry = self.initial_geometry + (10, 10) # adjust for border
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
        w = self.add_window(self.create_window(g))
        w.map()

        # Move the window around a bunch of times.
        for i in range(n):
            w.resize(g + (randint(1, 100), randint(1, 100)))

    def test_event_loop(self):
        """Test the window manager's event loop"""
        n = 100
        self.jiggle_window(n)
        self.event_loop(lambda: self.wm_thread.wm.events_received >= n)

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
        self.event_loop(lambda: 0 < self.wm_thread.wm.events_received < n)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
