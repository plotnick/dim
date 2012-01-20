# -*- mode: Python; coding: utf-8 -*-

from random import randint
from struct import pack, unpack
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
from manager import *
from properties import WindowProperty, WMState, WMSizeHints, WMHints
from xutil import *

ms = 1e-3 # one millisecond; useful for sleep times

class EventType(object):
    """X event type codes."""
    KeyPress = 2
    KeyRelease = 3
    ButtonPress = 4
    ButtonRelease = 5
    MotionNotify = 6

class WindowManagerThread(Thread):
    def __init__(self, wm_class, screen, **kwargs):
        assert issubclass(wm_class, WindowManager)
        assert isinstance(screen, int)

        super(WindowManagerThread, self).__init__(name="WM")
        self.wm = wm_class(None, screen, **kwargs)

    def run(self):
        try:
            self.wm.start()
        finally:
            self.wm.shutdown()

class ClientDestroyed(Exception):
    pass

class TestClient(EventHandler, Thread):
    """A simple client with one top-level window."""

    def __init__(self, geometry, screen=None, event_mask=0):
        super(TestClient, self).__init__(name="Client")

        self.conn = xcb.connect()
        if screen is None:
            screen = self.conn.pref_screen
        self.screen = self.conn.get_setup().roots[screen]
        self.atoms = AtomCache(self.conn, ["WM_STATE"])
        self.window = self.conn.generate_id()
        self.mapped = False
        self.managed = False
        self.destroyed = False
        self.reparented = False
        self.parent = self.screen.root
        self.geometry = geometry
        self.synthetic_geometry = None

        event_mask |= (EventMask.StructureNotify | EventMask.PropertyChange)
        self.conn.core.CreateWindowChecked(self.screen.root_depth,
                                           self.window,
                                           self.screen.root,
                                           geometry.x, geometry.y,
                                           geometry.width, geometry.height,
                                           geometry.border_width,
                                           WindowClass.InputOutput,
                                           self.screen.root_visual,
                                           (CW.BackPixel |
                                            CW.BorderPixel |
                                            CW.EventMask),
                                           [self.screen.white_pixel,
                                            self.screen.black_pixel,
                                            event_mask]).check()

    def map(self):
        self.conn.core.MapWindowChecked(self.window).check()

    def unmap(self):
        self.conn.core.UnmapWindowChecked(self.window).check()

    def destroy(self):
        self.conn.core.DestroyWindowChecked(self.window).check()

    def resize(self, size, border_width):
        assert isinstance(size, Rectangle)
        self.conn.core.ConfigureWindowChecked(self.window,
                                              (ConfigWindow.Width |
                                               ConfigWindow.Height |
                                               ConfigWindow.BorderWidth),
                                              [size.width,
                                               size.height,
                                               border_width]).check()
        return (size, border_width)

    def configure(self, geometry):
        assert isinstance(geometry, Geometry)
        self.conn.core.ConfigureWindowChecked(self.window,
                                              (ConfigWindow.X |
                                               ConfigWindow.Y |
                                               ConfigWindow.Width |
                                               ConfigWindow.Height |
                                               ConfigWindow.BorderWidth),
                                              geometry).check()
        return geometry

    @property
    def frame_geometry(self):
        return get_window_geometry(self.conn, self.parent)

    def set_size_hints(self, size_hints):
        self.conn.core.ChangePropertyChecked(PropMode.Replace, self.window,
                                             self.atoms["WM_NORMAL_HINTS"],
                                             self.atoms["WM_SIZE_HINTS"],
                                             *size_hints.change_property_args()).check()

    @property
    def wm_state(self):
        reply = self.conn.core.GetProperty(False, self.window,
                                           self.atoms["WM_STATE"],
                                           self.atoms["WM_STATE"],
                                           0, 0xffffffff).reply()
        return WMState.unpack(reply.value.buf())

    @property
    def wm_hints(self):
        reply = self.conn.core.GetProperty(False, self.window,
                                           self.atoms["WM_HINTS"],
                                           self.atoms["WM_HINTS"],
                                           0, 0xffffffff).reply()
        return WMHints.unpack(reply.value.buf())

    @wm_hints.setter
    def wm_hints(self, wm_hints):
        self.conn.core.ChangePropertyChecked(PropMode.Replace, self.window,
                                             self.atoms["WM_HINTS"],
                                             self.atoms["WM_HINTS"],
                                             *wm_hints.change_property_args()).check()

    def run(self, max_timeouts=100):
        """A simple client event loop."""
        timeouts = 0
        rlist = [self.conn.get_file_descriptor()]
        wlist = []
        xlist = []
        while timeouts < max_timeouts:
            # Process pending events from XCB.
            while True:
                event = self.conn.poll_for_event()
                if event:
                    try:
                        self.handle_event(event)
                    except ClientDestroyed:
                        self.shutdown()
                        return
                else:
                    break

            self.conn.flush()

            # Wait for more events, but only for a few milliseconds.
            r, w, x = select(rlist, wlist, xlist, randint(1, 10) * ms)
            if not r and not w and not x:
                timeouts += 1
        assert False, "client timed out"

    def withdraw(self):
        # See ICCCM §4.1.4.
        self.unmap()
        self.conn.core.SendEvent(False, self.screen.root,
                                 (EventMask.SubstructureRedirect |
                                  EventMask.SubstructureNotify),
                                 pack("bx2xIIB19x",
                                      18, # code (UnmapNotify)
                                      self.screen.root, # event
                                      self.window, # window
                                      False)) # from-configure

    def iconify(self):
        # See ICCCM §4.1.4.
        send_client_message(self.conn, self.screen.root, self.window,
                            (EventMask.SubstructureRedirect |
                             EventMask.SubstructureNotify),
                            32, self.atoms["WM_CHANGE_STATE"],
                            [WMState.IconicState, 0, 0, 0, 0])

    def shutdown(self):
        self.conn.flush()
        self.conn.disconnect()

    def unhandled_event(self, event):
        pass

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        assert event.window == self.window
        self.mapped = True

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        assert event.window == self.window
        self.mapped = False

    @handler(ReparentNotifyEvent)
    def handle_reparent_notify(self, event):
        assert event.window == self.window
        self.parent = event.parent
        self.reparented = (self.parent != self.screen.root)

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        assert event.window == self.window
        self.destroyed = True
        raise ClientDestroyed

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        assert event.window == self.window
        assert not event.override_redirect
        geometry = Geometry(event.x, event.y,
                            event.width, event.height,
                            event.border_width)
        if is_synthetic_event(event):
            self.synthetic_geometry = geometry
        else:
            self.geometry = geometry

    @handler(PropertyNotifyEvent)
    def handle_property_notify(self, event):
        assert event.window == self.window
        if event.atom == self.atoms["WM_STATE"]:
            if event.state == Property.NewValue:
                self.managed = True
            elif event.state == Property.Delete:
                self.managed = False

class WMTestCase(unittest.TestCase):
    """A test fixture that establishes an X connection and starts the WM in
    a separate thread."""

    # The class of window manager to instantiate. Subclasses may override
    # this to test other window manager classes.
    wm_class = WindowManager

    def setUp(self, screen=None, start_wm=True, **kwargs):
        self.conn = xcb.connect()
        self.xtest = self.conn(xcb.xtest.key)
        if screen is None:
            screen = self.conn.pref_screen
        self.screen = self.conn.get_setup().roots[screen]
        self.atoms = AtomCache(self.conn)
        self.modmap = ModifierMap(self.conn)
        self.keymap = KeyboardMap(self.conn, None, self.modmap)
        self.buttons = PointerMap(self.conn)
        self.clients = []
        self.wm_thread = WindowManagerThread(self.wm_class, screen, **kwargs)
        if start_wm:
            self.wm_thread.start()

    def tearDown(self):
        if self.wm_thread.is_alive():
            self.kill_wm()
            self.wm_thread.join(100 * ms)
            assert not self.wm_thread.is_alive(), "WM thread is still alive"
        for client in self.clients:
            if not client.destroyed:
                client.destroy()
            client.join(100 * ms)
            assert not client.is_alive(), "client thread is still alive"
        self.conn.flush()
        self.conn.disconnect()

    def kill_wm(self):
        """Ask the window manager to exit."""
        send_client_message(self.conn, self.screen.root, self.screen.root,
                            EventMask.StructureNotify,
                            8, self.atoms["WM_EXIT"], [0] * 20)
        self.conn.flush()

    def add_client(self, client, start_client=True):
        """Manage and start a client thread."""
        assert isinstance(client, TestClient)
        self.clients.append(client)
        if start_client:
            client.start()
        return client

    def fake_input(self, type, detail, root_x=0, root_y=0):
        """Simulate user input."""
        # For faked ButtonPress/ButtonRelease events, the detail field
        # specifies a physical button. To simplify the interface, we'll
        # accept a logical button, and grovel for the corresponding
        # physical button.
        if type == EventType.ButtonPress or type == EventType.ButtonRelease:
            for i, button in enumerate(self.buttons):
                if button == detail:
                    detail = i + 1

        self.xtest.FakeInputChecked(type, detail, Time.CurrentTime,
                                    self.screen.root, root_x, root_y, 0).check()
        sleep(1 * ms) # block & yield control

    def warp_pointer(self, x, y):
        """Warp the pointer to the given coordinates relative to the origin
        of the root window."""
        self.conn.core.WarpPointerChecked(0, self.screen.root, 0, 0, 0, 0,
                                          int16(x), int16(y)).check()

    def loop(self, test=lambda: False, max_timeouts=100):
        """Loop until the given test is true or we time out too many times."""
        timeouts = 0
        while timeouts < max_timeouts:
            if test():
                return True
            self.conn.flush()
            sleep(randint(1, 10) * ms)
            timeouts += 1
        self.fail("test loop timed out")

class WarpedPointer(object):
    """A context manager that warps the pointer to the specified position on
    enter, and warps it back to its original position on exit."""

    def __init__(self, test, pointer):
        assert isinstance(pointer, Position)
        assert isinstance(test, WMTestCase)
        self.test = test
        self.pointer = pointer

    def __enter__(self):
        reply = self.test.conn.core.QueryPointer(self.test.screen.root).reply()
        self.original_pointer = Position(reply.root_x, reply.root_y)
        self.test.warp_pointer(*self.pointer)

    def __exit__(self, *exc_info):
        self.test.warp_pointer(*self.original_pointer)

class TestWMStartup(WMTestCase):
    def setUp(self):
        super(TestWMStartup, self).setUp(start_wm=False)

    def test_startup(self):
        """Ensure that the window manager adopts extant top-level windows"""
        # Create a few top-level windows. Just for fun, we'll map two and
        # leave one more withdrawn; that last will not be managed.
        w1 = self.add_client(TestClient(Geometry(0, 0, 100, 100, 1)))
        w2 = self.add_client(TestClient(Geometry(10, 10, 10, 10, 1)))
        w3 = self.add_client(TestClient(Geometry(20, 20, 20, 20, 1)))
        w1.map()
        w2.map()

        # Now fire up the window manager.
        self.wm_thread.start()

        self.loop(lambda: w1.managed and w2.managed and not w3.managed)

        # Let's bring up that last window.
        w3.map()
        self.loop(lambda: w3.managed)

class TestWMStates(WMTestCase):
    """Test the various state transitions, as described in ICCCM §4.1.4.

    In addition to verifying that the effect on the client is correct,
    we also peek at the manager's internal data structures to ensure that
    they're being updated correctly."""

    geometry = Geometry(0, 0, 100, 100, 1)

    def setUp(self):
        super(TestWMStates, self).setUp()
        self.client = self.add_client(TestClient(self.geometry))

    def normalize_client(self):
        self.client.map()
        self.loop(lambda: (self.client.mapped and
                           self.client.managed and
                           self.client.reparented and
                           self.client.wm_state == WMState.NormalState))

        # Peek at WM bookkeeping.
        wm_client = self.wm_thread.wm.clients[self.client.window]
        self.loop(lambda: (wm_client.window == self.client.window and
                           wm_client.frame == self.client.parent))

    def iconify_client(self):
        window = self.client.window
        frame = self.client.parent

        self.client.iconify()
        self.loop(lambda: (not self.client.mapped and
                           self.client.managed and
                           self.client.reparented and
                           self.client.wm_state == WMState.IconicState))

        # The manager should not undecorate iconified clients, so everything
        # should be the same as for a client in the Normal state.
        wm_client = self.wm_thread.wm.clients[window]
        self.loop(lambda: (wm_client.window == window and
                           wm_client.frame == frame))

    def withdraw_client(self):
        window = self.client.window
        frame = self.client.parent

        self.client.withdraw()
        self.loop(lambda: (not self.client.mapped and
                           self.client.parent == self.client.screen.root and
                           self.client.wm_state == WMState.WithdrawnState))

        # Withdrawn clients are unmanaged by the WM.
        self.loop(lambda: window not in self.wm_thread.wm.clients)
        self.loop(lambda: frame not in self.wm_thread.wm.frames)

    def destroy_client(self):
        window = self.client.window
        frame = self.client.parent

        self.client.destroy()
        self.loop(lambda: (not self.client.mapped and
                           self.client.destroyed))

        # Once destroyed, all record of this client window should be
        # removed from the WM's books.
        self.loop(lambda: window not in self.wm_thread.wm.clients)
        self.loop(lambda: frame not in self.wm_thread.wm.frames)

    def test_withdrawn_iconic(self):
        """Withdrawn → Iconic → Normal state transitions"""
        self.client.wm_hints = WMHints(initial_state=WMState.IconicState)
        self.client.map()
        self.loop(lambda: (not self.client.mapped and
                           self.client.managed and
                           self.client.reparented and
                           self.client.wm_state == WMState.IconicState))
        self.normalize_client()
        self.destroy_client()

    def test_state_transitions(self):
        """Test state transitions"""
        self.client.wm_hints = WMHints(initial_state=WMState.NormalState)
        self.normalize_client()
        self.withdraw_client()
        self.normalize_client()
        self.iconify_client()
        self.normalize_client()
        self.destroy_client()

class TestWMClientMoveResize(WMTestCase):
    def setUp(self):
        super(TestWMClientMoveResize, self).setUp()
        geometry = self.initial_geometry = Geometry(0, 0, 100, 100, 1)
        self.client = self.add_client(TestClient(geometry))
        self.client.map()
        self.loop(lambda: (self.client.mapped and
                           self.client.managed and
                           self.client.reparented and
                           self.client.synthetic_geometry == geometry))

        # Reset received geometries for tests.
        self.geometry = None
        self.client.synthetic_geometry = None

    def test_no_change(self):
        """Configure a top-level window without changing its size or position"""
        geometry = self.initial_geometry
        self.client.configure(geometry)
        self.loop(lambda: self.client.synthetic_geometry == geometry)

    def test_change_border_width(self):
        """Ignore changes to the client's border width"""
        geometry = self.initial_geometry
        self.client.configure(geometry.reborder(5))
        self.loop(lambda: self.client.synthetic_geometry == geometry)

    def test_move(self):
        """Move a top-level window without changing its size"""
        geometry = self.initial_geometry + Position(5, 5)
        self.client.configure(geometry)
        self.loop(lambda: self.client.synthetic_geometry == geometry)

    def test_move_resize(self):
        """Move and resize a top-level window"""
        geometry = Geometry(5, 5, 50, 50, 1)
        self.client.configure(geometry)
        self.loop(lambda: (self.client.geometry.size() == geometry.size() and
                           self.client.frame_geometry == geometry))

    def test_resize_gravity(self):
        """Resize a client window with gravity"""
        geometry = self.initial_geometry + Rectangle(50, 50)
        gravity = Gravity.SouthEast
        self.client.set_size_hints(WMSizeHints(win_gravity=gravity))
        self.client.resize(geometry.size(), geometry.border_width)
        self.loop(lambda: (self.client.geometry.size() == geometry.size() and
                           (self.client.frame_geometry ==
                            self.initial_geometry.resize(geometry.size(),
                                                         gravity=gravity))))

class TransientTestClient(TestClient):
    def __init__(self, geometry, transient_for, **kwargs):
        super(TransientTestClient, self).__init__(geometry, **kwargs)

        assert isinstance(transient_for, TestClient)
        self.transient_for = transient_for.window

    @property
    def transient_for(self):
        reply = self.conn.core.GetProperty(False, self.window,
                                           self.atoms["WM_TRANSIENT_FOR"],
                                           self.atoms["WINDOW"],
                                           0, 1)
        return WindowProperty.unpack(reply.value.buf())

    @transient_for.setter
    def transient_for(self, window):
        window = WindowProperty(window)
        self.conn.core.ChangePropertyChecked(PropMode.Replace, self.window,
                                             self.atoms["WM_TRANSIENT_FOR"],
                                             self.atoms["WINDOW"],
                                             *window.change_property_args()).check()

class TestWMTransient(WMTestCase):
    def setUp(self):
        super(TestWMTransient, self).setUp()

        self.client = TestClient(Geometry(0, 0, 100, 100, 1))
        self.transient = TransientTestClient(Geometry(50, 50, 10, 10, 0),
                                             self.client)
        self.add_client(self.client)
        self.add_client(self.transient)

        self.client.map()
        self.transient.map()
        self.loop(lambda: (self.client.mapped and
                           self.client.managed and
                           self.transient.mapped and
                           self.transient.managed))

    def test_iconfify_with_transient(self):
        """Iconify client with transient"""
        self.client.iconify()
        self.loop(lambda: (not self.client.mapped and
                           not self.transient.mapped))

    def test_normalize_with_transient(self):
        """Normalize client with transient"""
        self.client.iconify()
        self.transient.iconify()
        self.loop(lambda: (not self.client.mapped and
                           not self.transient.mapped))

        self.client.map()
        self.loop(lambda: (self.client.mapped and
                           self.transient.mapped))

class EventLoopTester(WindowManager):
    """A window manager that records the number of ConfigureNotify events
    that it receives on its client windows."""

    def __init__(self, *args, **kwargs):
        super(EventLoopTester, self).__init__(*args, **kwargs)
        self.events_received = 0

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        if is_synthetic_event(event):
            self.events_received += 1

class EventLoopTestCase(WMTestCase):
    def jiggle_window(self, n=100):
        # Realize a client window.
        geometry = Geometry(0, 0, 100, 100, 5)
        client = self.add_client(TestClient(geometry))
        client.map()
        self.loop(lambda: (client.mapped and
                           client.managed and
                           client.reparented))

        # Move the window around a bunch of times.
        for i in range(n):
            client.configure(geometry + (randint(1, 100), randint(1, 100)))

class TestWMEventLoop(EventLoopTestCase):
    wm_class = EventLoopTester

    def test_event_loop(self):
        """Test the window manager's event loop"""
        n = 100
        self.jiggle_window(n)
        self.loop(lambda: self.wm_thread.wm.events_received >= n)

class EventCompressionTester(EventLoopTester):
    @handler(ConfigureNotifyEvent)
    @compress
    def handle_configure_notify(self, event):
        return

class TestWMEventLoopWithCompression(EventLoopTestCase):
    wm_class = EventCompressionTester

    def test_event_loop(self):
        """Test event compression"""
        n = 100
        self.jiggle_window(n)
        self.loop(lambda: 0 < self.wm_thread.wm.events_received < n)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
