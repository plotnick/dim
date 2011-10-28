# -*- mode: Python; coding: utf-8 -*-

from time import sleep
import unittest

from event import *
from geometry import *
from focus import *

import xcb
from xcb.xproto import *
import xcb.xtest

from test_manager import EventType, TestClient, WMTestCase

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
        return (self.conn.core.GetInputFocus().reply().focus == window and
                self.wm_thread.wm.current_focus and
                self.wm_thread.wm.current_focus.window == window and
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
        self.warp_pointer(*center(geometry))
        client = self.add_client(FocusTestClient(geometry))
        client.map()

        self.assertNotFocus(client)
        self.wm_thread.start()
        self.loop(self.make_focus_test(client))

class TestSloppyFocus(FocusPolicyTestCase):
    wm_class = SloppyFocus

    def test_focus(self):
        # We need to be able to reach the root window with the pointer.
        # Let's ensure that the northwest corner is free of other windows.
        self.warp_pointer(1, 1)
        reply = self.conn.core.QueryPointer(self.screen.root).reply()
        self.assertFalse(reply.child, "northwest corner must be clear")

        geometry = Geometry(5, 5, 100, 100, 1)
        client = self.add_client(FocusTestClient(geometry))
        client.map()

        # Move the pointer into the window, and make sure it gets the focus.
        self.fake_input(EventType.MotionNotify, False, *center(geometry))
        self.loop(self.make_focus_test(client))

        # Now move it back to the root, and ensure that it still has the focus.
        self.fake_input(EventType.MotionNotify, False, 1, 1)
        self.loop(self.make_focus_test(client))

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
