# -*- mode: Python; coding: utf-8 -*-

from time import sleep
import unittest

from event import *
from geometry import *
from focus import *

import xcb
from xcb.xproto import *
import xcb.xtest

from test_manager import EventType, TestWindow, WMTestCase

def center(geometry):
    bw = geometry.border_width
    return geometry.position() + geometry.size() // 2 + Position(bw, bw)

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

    def is_focused(self, window):
        if isinstance(window, TestWindow):
            window = window.id
        # The server and the window manager must agree on the focus.
        return (self.conn.core.GetInputFocus().reply().focus == window and
                self.wm_thread.wm.current_focus.window == window)

    def assertFocus(self, window):
        self.assertTrue(self.is_focused(window))

    def assertNotFocus(self, window):
        self.assertFalse(self.is_focused(window))

class TestInitialFocus(FocusPolicyTestCase):
    wm_class = FocusPolicy

    def setUp(self, start_wm=False):
        super(TestInitialFocus, self).setUp(start_wm)

    def test_initial_focus(self):
        g = Geometry(0, 0, 100, 100, 5)
        self.warp_pointer(*center(g))
        w = self.add_window(self.create_window(g))
        w.map()

        self.assertNotFocus(w)
        self.wm_thread.start()
        self.event_loop(lambda: self.is_focused(w))

class TestSloppyFocus(FocusPolicyTestCase):
    wm_class = SloppyFocus

    def test_focus(self):
        # We need to be able to reach the root window with the pointer.
        # Let's ensure that the northwest corner is free of other windows.
        self.warp_pointer(1, 1)
        reply = self.conn.core.QueryPointer(self.screen.root).reply()
        self.assertFalse(reply.child, "northwest corner must be clear")

        g = Geometry(5, 5, 100, 100, 1)
        w = self.add_window(self.create_window(g))
        w.map()

        # Move the pointer into the window, and make sure it gets the focus.
        self.fake_input(EventType.MotionNotify, False, *center(g))
        self.event_loop(lambda: self.is_focused(w))

        # Now move it back to the root, and ensure that it still has the focus.
        self.fake_input(EventType.MotionNotify, False, 1, 1)
        self.event_loop(lambda: self.is_focused(w))

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
