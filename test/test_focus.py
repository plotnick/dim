# -*- mode: Python; coding: utf-8 -*-

import unittest

from event import *
from geometry import *
from focus import *

from xcb.xproto import *

from test_manager import EventType, TestClient, WMTestCase, WarpedPointer

def center(geometry):
    bw = geometry.border_width
    return geometry.position() + geometry.size() // 2 + Position(bw, bw)

class FocusTestClient(TestClient):
    def __init__(self, geometry, screen=None, event_mask=EventMask.FocusChange):
        super(FocusTestClient, self).__init__(geometry, screen, event_mask)
        self.focused = False

    @handler(FocusInEvent)
    def handle_focus_in(self, event):
        self.focused = True

    @handler(FocusOutEvent)
    def handle_focus_out(self, event):
        self.focused = False

class FocusPolicyTestCase(WMTestCase):
    """Base class for focus policy integration tests."""

    def setUp(self, start_wm=True):
        super(FocusPolicyTestCase, self).setUp(start_wm=start_wm)
        self.conn.core.SetInputFocusChecked(InputFocus.PointerRoot,
                                            InputFocus.PointerRoot,
                                            Time.CurrentTime).check()

    def tearDown(self):
        self.conn.core.SetInputFocusChecked(InputFocus.PointerRoot,
                                            InputFocus.PointerRoot,
                                            Time.CurrentTime).check()
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

class TestInitialFocus(FocusPolicyTestCase):
    wm_class = FocusPolicy

    def setUp(self, start_wm=False):
        super(TestInitialFocus, self).setUp(start_wm)

    def test_initial_focus(self):
        geometry = Geometry(0, 0, 100, 100, 5)
        with WarpedPointer(self, center(geometry)):
            client = self.add_client(FocusTestClient(geometry))
            client.map()
            self.loop(lambda: client.mapped)

            self.assertNotFocus(client)
            self.wm_thread.start()
            self.loop(self.make_focus_test(client))

class TestSloppyFocus(FocusPolicyTestCase):
    """Test the behavior of the sloppy focus policy."""

    # Most of these tests are based on Alex Hioreanu's description of
    # sloppy focus in AHWM:
    #
    #   <http://people.cs.uchicago.edu/~ahiorean/ahwm/sloppy-focus.html>
    #
    # AHWM was one of the first window managers to take the problems of
    # sloppy focus seriously, and our implementation owes it a debt of
    # gratitude.

    wm_class = SloppyFocus

    def pointer_window(self):
        root = self.screen.root
        return self.conn.core.QueryPointer(root).reply().child

    def test_sloppy(self):
        with WarpedPointer(self, Position(1, 1)):
            # We need to be able to reach the root window with the pointer.
            # Let's ensure that the northwest corner is free of windows.
            reply = self.conn.core.QueryPointer(self.screen.root).reply()
            self.assertFalse(reply.child, "northwest corner must be clear")

            geometry = Geometry(5, 5, 100, 100, 1)
            client = self.add_client(FocusTestClient(geometry))
            client.map()
            self.loop(lambda: client.mapped and client.managed)

            # Move the pointer into the window and make sure it gets the focus.
            self.fake_input(EventType.MotionNotify, False, *center(geometry))
            self.loop(self.make_focus_test(client))

            # Now move it back to the root and ensure that it's still focused.
            self.fake_input(EventType.MotionNotify, False, 1, 1)
            self.loop(self.make_focus_test(client))

    def test_enter_window_keep_focus(self):
        # This is problem 2 in the AHWM sloppy focus document.
        a = self.add_client(FocusTestClient(Geometry(0, 0, 100, 50, 1)))
        a.map()
        self.loop(lambda: a.mapped and a.managed)

        b = self.add_client(FocusTestClient(Geometry(75, 25, 100, 50, 1)))
        b.map()
        self.loop(lambda: b.mapped and b.managed)

        # Focus window B.
        with WarpedPointer(self, Position(150, 50)):
            self.loop(self.make_focus_test(b))

        # Put the pointer right next to window A.
        with WarpedPointer(self, Position(110, 10)):
            # Resize A so that it now contains the pointer.
            a.resize(Rectangle(150, 100), 1)
            self.loop(lambda: (a.geometry == Geometry(0, 0, 150, 100, 1) and
                               self.pointer_window() == a.window))

            # B should still have the focus, since the entering of A was
            # not a result of a pointer movement.
            self.loop(self.make_focus_test(b))

    def test_leave_window_keep_focus(self):
        # This is problem 3 in the AHWM sloppy focus document. It is
        # closely related to problem 2, and shares a solution.
        a = self.add_client(FocusTestClient(Geometry(0, 0, 100, 50, 1)))
        a.map()
        self.loop(lambda: a.mapped and a.managed)

        b = self.add_client(FocusTestClient(Geometry(75, 25, 100, 50, 1)))
        b.map()
        self.loop(lambda: b.mapped and b.managed)

        # Put the pointer in window B, but over window A.
        with WarpedPointer(self, Position(85, 30)):
            self.loop(self.make_focus_test(b))

            # Move & resize B so that the pointer is now in A.
            geometry = Geometry(100, 25, 75, 50, 1)
            b.configure(geometry)
            self.loop(lambda: (b.geometry == geometry and
                               self.pointer_window() == a.window))

            # B should still have the focus.
            self.loop(self.make_focus_test(b))

class TestClickToFocus(FocusPolicyTestCase):
    wm_class = ClickToFocus

    def test_focus(self):
        geometry = Geometry(0, 0, 100, 100, 1)
        with WarpedPointer(self, center(geometry)):
            client = self.add_client(FocusTestClient(geometry))
            client.map()
            self.loop(lambda: client.mapped and client.managed)

            self.assertNotFocus(client)
            self.fake_input(EventType.ButtonPress, 1)
            self.fake_input(EventType.ButtonRelease, 1)
            self.loop(self.make_focus_test(client))

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
