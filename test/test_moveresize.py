# -*- mode: Python; coding: utf-8 -*-

from time import sleep
import unittest

import xcb
from xcb.xproto import *
import xcb.xtest

from cursor import *
from decorator import Decorator
from geometry import *
from keymap import *
from moveresize import ClientMove, ClientResize, MoveResize
from properties import WMSizeHints
from test_manager import TestWindow, WMTestCase

class MockClient(object):
    def __init__(self, test, geometry, size_hints=WMSizeHints()):
        self.test = test
        self.geometry = geometry
        self.screen = None
        self.window = None
        self.decorator = Decorator(None, self)
        self.wm_normal_hints = size_hints

    def move(self, position):
        self.test.assertTrue(isinstance(position, Position))
        self.geometry = self.geometry._replace(x=position.x, y=position.y)

    def resize(self, size):
        self.test.assertTrue(isinstance(size, Rectangle))
        self.geometry = self.geometry._replace(width=size.width,
                                               heigh=size.height)

    def update_geometry(self, geometry):
        self.test.assertTrue(isinstance(geometry, Geometry))
        self.geometry = geometry

class TestClientMove(unittest.TestCase):
    def test_move(self):
        g = Geometry(x=5, y=10, width=20, height=30, border_width=1)
        client = MockClient(self, g)
        def cleanup(time):
            self.assertEqual(time, Time.CurrentTime)
        def change_cursor(cursor):
            self.assertEqual(cursor, ClientMove.cursor)
        move = ClientMove(client, Position(0, 0), cleanup, change_cursor)

        pointer = Position(5, 10)
        move.update(pointer)
        self.assertEqual(client.geometry, g + pointer)

        move.rollback()
        self.assertEqual(client.geometry, g)

class TestClientResize(unittest.TestCase):
    def simple_resize_test(self, pointer, cursor, delta, **offsets):
        g = Geometry(x=0, y=0, width=15, height=30, border_width=1)
        client = MockClient(self, g)
        def cleanup(time):
            self.assertEqual(time, Time.CurrentTime)
        def change_cursor(new_cursor):
            self.assertEqual(cursor, new_cursor)
        resize = ClientResize(client, pointer, cleanup, change_cursor)

        resize.update(pointer + delta)
        d = g._asdict()
        for k, v in offsets.items():
            d[k] += v
        self.assertEqual(client.geometry, Geometry(**d))

        resize.rollback()
        self.assertEqual(client.geometry, g)
        
    def test_resize_northwest(self):
        self.simple_resize_test(Position(1, 1),
                                XC_top_left_corner,
                                Position(5, 10),
                                x=+5, width=-5, y=+10, height=-10)

    def test_resize_north(self):
        self.simple_resize_test(Position(5, 1),
                                XC_top_side,
                                Position(5, 10),
                                y=+10, height=-10)

    def test_resize_northeast(self):
        self.simple_resize_test(Position(10, 1),
                                XC_top_right_corner,
                                Position(5, 10),
                                width=+5, y=+10, height=-10)

    def test_resize_west(self):
        self.simple_resize_test(Position(1, 15),
                                XC_left_side,
                                Position(5, 10),
                                x=+5, width=-5)

    def test_resize_center(self):
        self.simple_resize_test(Position(7, 15),
                                XC_fleur,
                                Position(5, 10),
                                x=+5, y=+10)

    def test_resize_east(self):
        self.simple_resize_test(Position(10, 15),
                                XC_right_side,
                                Position(5, 10),
                                width=+5)

    def test_resize_southwest(self):
        self.simple_resize_test(Position(1, 25),
                                XC_bottom_left_corner,
                                Position(5, 10),
                                x=+5, width=-5, height=+10)

    def test_resize_south(self):
        self.simple_resize_test(Position(5, 25),
                                XC_bottom_side,
                                Position(5, 10),
                                height=+10)

    def test_resize_southeast(self):
        self.simple_resize_test(Position(10, 25),
                                XC_bottom_right_corner,
                                Position(5, 10),
                                width=+5, height=+10)

    def test_constrained_resize(self):
        g = Geometry(x=0, y=0, width=484, height=316, border_width=1)
        min = Rectangle(10, 17)
        inc = Rectangle(6, 13)
        base = Rectangle(4, 4)
        client = MockClient(self, g, WMSizeHints(min_size=min,
                                                 resize_inc=inc,
                                                 base_size=base))
        def cleanup(time):
            self.assertEqual(time, Time.CurrentTime)
        def change_cursor(cursor):
            self.assertEqual(cursor, XC_bottom_right_corner)
        pointer = Position(480, 300)
        resize = ClientResize(client, pointer, cleanup, change_cursor)

        resize.update(pointer + Position(5, 10)) # < resize increment
        self.assertEqual(client.geometry, g)
        resize.update(pointer + Position._make(inc))
        self.assertEqual(client.geometry, g.resize(inc + (g.width, g.height)))
        resize.update(pointer + Position(-2 * inc.width, -2 * inc.height))
        self.assertEqual(client.geometry, g + Rectangle._make(-2 * inc))
        resize.update(pointer + Position(-1000, -1000))
        self.assertEqual(client.geometry, g.resize(min))

        resize.rollback()
        self.assertEqual(client.geometry, g)

class EventCode(object):
    KeyPress = 2
    KeyRelease = 3
    ButtonPress = 4
    ButtonRelease = 5
    MotionNotify = 6

class TestMoveResize(WMTestCase):
    """Integration test for interactive move/resize."""

    wm_class = MoveResize

    def setUp(self):
        super(TestMoveResize, self).setUp()
        self.root = self.conn.get_setup().roots[self.conn.pref_screen].root
        self.xtest = self.conn(xcb.xtest.key)
        self.cursors = FontCursor(self.conn)
        self.modmap = ModifierMap(self.conn)
        self.keymap = KeyboardMap(self.conn, None, self.modmap)
        self.pointer_map = PointerMap(self.conn)
        self.initial_geometry = Geometry(x=0, y=0, width=100, height=100,
                                         border_width=1)
        self.window = self.add_window(TestWindow(self.conn,
                                                 self.initial_geometry))
        self.window.map()

    def fake_input(self, type, detail, root_x=0, root_y=0):
        self.xtest.FakeInputChecked(type, detail, Time.CurrentTime,
                                    self.root, root_x, root_y, 0).check()
        sleep(0.0001) # block & yield control

    def warp(self, x, y):
        self.conn.core.WarpPointerChecked(0, self.root, 0, 0, 0, 0,
                                          x, y).check()

    def test_move(self):
        mod1 = self.modmap[MapIndex._1][0]
        but1 = self.pointer_map[1]
        delta = Position(5, 10)

        self.warp(50, 50)
        self.fake_input(EventCode.KeyPress, mod1)
        self.fake_input(EventCode.ButtonPress, but1)
        self.fake_input(EventCode.MotionNotify, True, *delta)
        self.fake_input(EventCode.ButtonRelease, but1)
        self.fake_input(EventCode.KeyRelease, mod1)
        self.event_loop(lambda: self.window.geometry == \
                            self.initial_geometry + delta)

    def test_resize_southeast(self):
        mod1 = self.modmap[MapIndex._1][0]
        but3 = self.pointer_map[3]
        delta = Position(5, 10)

        self.warp(75, 75)
        self.fake_input(EventCode.KeyPress, mod1)
        self.fake_input(EventCode.ButtonPress, but3)
        self.fake_input(EventCode.MotionNotify, True, *delta)
        self.fake_input(EventCode.ButtonRelease, but3)
        self.fake_input(EventCode.KeyRelease, mod1)
        self.event_loop(lambda: self.window.geometry == \
                            self.initial_geometry + Rectangle._make(delta))

    def test_resize_northwest(self):
        mod1 = self.modmap[MapIndex._1][0]
        but3 = self.pointer_map[3]
        delta = Position(5, 10)

        # Shrink the window just a bit.
        self.warp(5, 5)
        self.fake_input(EventCode.KeyPress, mod1)
        self.fake_input(EventCode.ButtonPress, but3)
        self.fake_input(EventCode.MotionNotify, True, *delta)
        self.fake_input(EventCode.ButtonRelease, but3)
        self.fake_input(EventCode.KeyRelease, mod1)
        self.event_loop(lambda: self.window.geometry == \
                            self.initial_geometry + delta - \
                            Rectangle._make(delta))

        # Shrink the window all the way down.
        self.fake_input(EventCode.KeyPress, mod1)
        self.fake_input(EventCode.ButtonPress, but3)
        self.fake_input(EventCode.MotionNotify, True,
                        self.initial_geometry.width,
                        self.initial_geometry.height)
        self.fake_input(EventCode.ButtonRelease, but3)
        self.fake_input(EventCode.KeyRelease, mod1)
        self.event_loop(lambda: (self.window.geometry.width == 1 and
                                 self.window.geometry.height == 1))

if __name__ == "__main__":
    unittest.main()
