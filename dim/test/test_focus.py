# -*- mode: Python; coding: utf-8 -*-

# Most of these tests are based on Alex Hioreanu's description of sloppy
# focus in AHWM:
#
#   <http://people.cs.uchicago.edu/~ahiorean/ahwm/sloppy-focus.html>
#
# AHWM was one of the first window managers to take the problems of sloppy
# focus seriously, and our implementation owes it a debt of gratitude.

from time import sleep
import unittest

from dim.event import *
from dim.geometry import *
from dim.focus import *
from dim.properties import WMHints

from xcb.xproto import *

from test_manager import ms, EventType, TestClient, WMTestCase, WarpedPointer

def center(geometry):
    bw = geometry.border_width
    return geometry.position() + geometry.size() // 2 + Position(bw, bw)

class FocusTestClient(TestClient):
    def __init__(self, geometry, screen=None,
                 event_mask=EventMask.FocusChange,
                 input_hint=None):
        super(FocusTestClient, self).__init__(geometry, screen,
                                              event_mask=event_mask)
        self.focused = False
        if input_hint is not None:
            self.wm_hints = WMHints(input=input_hint)

    @handler(FocusInEvent)
    def handle_focus_in(self, event):
        self.focused = True

    @handler(FocusOutEvent)
    def handle_focus_out(self, event):
        self.focused = False

class FocusPolicyTestCase(WMTestCase):
    """Base class for focus policy integration tests."""

    wm_class = FocusPolicy

    # We need a "safe" position to which we can warp the pointer that will
    # not be over any of the windows that we create. There should be no
    # other client windows at this position, either.
    safe_position = Position(1000, 1000)

    def setUp(self, start_wm=True):
        super(FocusPolicyTestCase, self).setUp(start_wm=start_wm,
                                               focus_new_windows=False)
        self.conn.core.SetInputFocusChecked(InputFocus.PointerRoot,
                                            InputFocus.PointerRoot,
                                            Time.CurrentTime).check()

        # Save the current pointer position.
        reply = self.conn.core.QueryPointer(self.screen.root).reply()
        self.original_pointer_position = Position(reply.root_x, reply.root_y)

        # Warp the pointer out of the way.
        self.warp_pointer(*self.safe_position)
        self.assertPointerRoot()

    def tearDown(self):
        self.conn.core.SetInputFocusChecked(InputFocus.PointerRoot,
                                            InputFocus.PointerRoot,
                                            Time.CurrentTime).check()
        self.warp_pointer(*self.original_pointer_position)
        super(FocusPolicyTestCase, self).tearDown()

    def is_focused(self, client):
        # The server, the window manager, and the client must agree on who
        # has the input focus.
        window = client.window
        current_focus = self.conn.core.GetInputFocus().reply().focus
        try:
            wm_focus = self.wm_thread.wm.focus_list[0]
        except IndexError:
            wm_focus = None
        return (current_focus == window and
                wm_focus and
                wm_focus.window == window and
                client.focused)

    def make_focus_test(self, client):
        return lambda: self.is_focused(client)

    def assertFocus(self, client):
        self.assertTrue(self.is_focused(client))

    def assertNotFocus(self, client):
        self.assertFalse(self.is_focused(client))

    def steal_focus(self, client, verify=True):
        self.conn.core.SetInputFocusChecked(InputFocus.PointerRoot,
                                            client.window,
                                            Time.CurrentTime).check()
        if verify:
            self.loop(self.make_focus_test(client))

    def focus(self, client, verify=True):
        """Give the client the focus. Subclasses should provide methods that
        are better adapted to their focus policy."""
        self.steal_focus(client, verify=verify)

    def make_client(self, geometry, managed=True, **kwargs):
        """Add a focus-test client with the given geometry, map it, and wait
        for it to be mapped and (possibly) managed."""
        client = FocusTestClient(geometry, **kwargs)
        self.add_client(client)
        client.map()
        test = ((lambda: (client.mapped and
                          client.managed and
                          client.reparented))
                if managed
                else lambda: client.mapped)
        self.loop(test)
        return client

    def assertPointerRoot(self):
        """Ensure that only the root window is currently under the pointer."""
        reply = self.conn.core.QueryPointer(self.screen.root).reply()
        self.assertFalse(reply.child,
                         "there must not be a window at +%d+%d" %
                         (reply.root_x, reply.root_y))

class TestInitialFocus(FocusPolicyTestCase):
    def setUp(self, start_wm=False):
        super(TestInitialFocus, self).setUp(start_wm)

    def test_initial_focus(self):
        """Initial focus"""
        geometry = Geometry(0, 0, 100, 100, 5)
        with WarpedPointer(self, center(geometry)):
            client = self.make_client(geometry, managed=False)
            self.assertNotFocus(client)
            self.wm_thread.start()
            self.loop(self.make_focus_test(client))

class SharedFocusPolicyTests(object):
    """A mix-in for tests that apply to all focus policies."""

    def test_pointer_focus(self):
        """Ensure that we can focus the window under the pointer"""
        geometry = Geometry(0, 0, 100, 100, 1)
        self.warp_pointer(*center(geometry))
        self.focus(self.make_client(geometry))

    def test_steal_focus(self):
        """Focus stealing"""
        a = self.make_client(Geometry(0, 0, 100, 100, 1))
        b = self.make_client(Geometry(75, 75, 100, 100, 1))
        self.steal_focus(a)
        self.steal_focus(b)
        self.focus(a)

    def test_input_hint(self):
        """Input hint"""
        a = self.make_client(Geometry(0, 0, 100, 100, 1), input_hint=True)
        b = self.make_client(Geometry(75, 75, 100, 100, 1), input_hint=False)
        self.focus(a)
        self.focus(b, verify=False)
        sleep(10 * ms)
        self.loop(self.make_focus_test(a))

    def test_focus_revert_over_root(self):
        """Revert focus with pointer over root"""
        # This is problem 4 in the AHWM sloppy focus document.
        a = self.make_client(Geometry(0, 0, 100, 50, 1))
        b = self.make_client(Geometry(75, 40, 100, 50, 1))
        self.focus(a)
        self.focus(b)

        p = Position(110, 25) # over root, but not in A or B
        self.warp_pointer(*p)
        self.assertPointerRoot()

        b.unmap()
        self.loop(lambda: self.make_focus_test(a))

    def test_focus_revert_over_window(self):
        """Revert focus with pointer over another window"""
        # This is problem 5 in the AHWM sloppy focus document.
        a = self.make_client(Geometry(0, 0, 100, 50, 1))
        b = self.make_client(Geometry(110, 40, 100, 50, 1))
        c = self.make_client(Geometry(115, 0, 80, 35, 1))
        self.warp_pointer(*center(c.geometry))
        self.steal_focus(a)
        self.steal_focus(b)
        b.unmap()
        self.loop(self.make_focus_test(a))

class TestSloppyFocus(FocusPolicyTestCase, SharedFocusPolicyTests):
    """Test the behavior of the sloppy focus policy."""
    wm_class = SloppyFocus

    def focus(self, client, verify=True):
        # The only reliable way to focus a window under the sloppy focus
        # policy is to move the pointer in such a way that it generates an
        # EnterNotify event.
        self.warp_pointer(*self.safe_position)
        self.warp_pointer(*center(client.geometry))
        if verify:
            self.loop(self.make_focus_test(client))

    def pointer_window(self):
        root = self.screen.root
        return self.conn.core.QueryPointer(root).reply().child

    def test_sloppy(self):
        """Basic sloppy focus"""
        self.warp_pointer(1, 1)
        self.assertPointerRoot()

        client = self.make_client(Geometry(2, 2, 100, 100, 1))
        self.fake_input(EventType.MotionNotify, False, 10, 10)
        self.loop(self.make_focus_test(client))

        # Now move the pointer back to the root and ensure that we keep focus.
        self.fake_input(EventType.MotionNotify, False, 1, 1)
        self.loop(self.make_focus_test(client))

    def test_enter_window_keep_focus(self):
        """Keep focus when pointer enters a window due to client configure"""
        # This is problem 2 in the AHWM sloppy focus document.
        a = self.make_client(Geometry(0, 0, 100, 50, 1))
        b = self.make_client(Geometry(75, 25, 100, 50, 1))
        self.focus(b)

        # Put the pointer right next to A.
        self.warp_pointer(110, 10)

        # Resize A so that it contains the pointer.
        geometry = Geometry(0, 0, 150, 100, 1)
        a.resize(geometry.size(), geometry.border_width)
        self.loop(lambda: (a.geometry.size() == geometry.size() and
                           self.pointer_window() == a.parent))

        # B should still have the focus, since the entering of A was
        # not a result of a pointer movement.
        self.loop(self.make_focus_test(b))

    def test_leave_window_keep_focus(self):
        """Keep focus when pointer leaves a window due to client configure"""
        # This is problem 3 in the AHWM sloppy focus document. It is
        # closely related to problem 2, and shares a solution.
        a = self.make_client(Geometry(0, 0, 100, 50, 1))
        b = self.make_client(Geometry(75, 25, 100, 50, 1))

        # Put the pointer in B, but over A.
        self.warp_pointer(85, 30)
        self.loop(self.make_focus_test(b))

        # Move & resize B so that the pointer is now in A.
        geometry = Geometry(100, 25, 75, 50, 1)
        b.configure(geometry)
        self.loop(lambda: (b.geometry.size() == geometry.size() and
                           self.pointer_window() == a.parent))

        # B should still have the focus.
        self.loop(self.make_focus_test(b))

class TestClickToFocus(FocusPolicyTestCase, SharedFocusPolicyTests):
    wm_class = ClickToFocus

    def focus(self, client, verify=True):
        self.warp_pointer(*center(client.geometry))
        self.fake_input(EventType.ButtonPress, 1)
        self.fake_input(EventType.ButtonRelease, 1)
        if verify:
            self.loop(self.make_focus_test(client))

    def test_focus(self):
        """Basic click-to-focus"""
        self.focus(self.make_client(Geometry(0, 0, 100, 100, 1)))

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
