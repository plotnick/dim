# -*- mode: Python; coding: utf-8 -*-

import unittest

import xcb
from xcb.xproto import *

from cursor import *
from decorator import Decorator
from geometry import *
from keysym import *
from moveresize import ClientMove, ClientResize, MoveResize
from properties import WMSizeHints
from xutil import int16

from test_manager import EventType, TestClient, WMTestCase

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

class TestMoveResize(WMTestCase):
    """Integration test for interactive move/resize."""

    wm_class = MoveResize

    def setUp(self):
        super(TestMoveResize, self).setUp()
        self.mod1 = self.modmap[MapIndex._1][0]
        self.initial_geometry = Geometry(x=0, y=0, width=100, height=100,
                                         border_width=1)
        self.client = self.add_client(TestClient(self.initial_geometry))
        self.client.map()
        self.loop(lambda: self.client.managed)

    def relative_position(self, ratio):
        return (self.initial_geometry.position() + 
                self.initial_geometry.size() * ratio)

    def make_geometry_test(self, geometry):
        return lambda: self.client.geometry == geometry

    def make_geometry_delta_test(self, delta):
        return self.make_geometry_test(self.initial_geometry + delta)

    def test_move(self):
        delta = Position(5, 10)
        self.warp_pointer(*self.relative_position(0.5)) # center
        self.fake_input(EventType.KeyPress, self.mod1)
        self.fake_input(EventType.ButtonPress, self.buttons[1])
        self.fake_input(EventType.MotionNotify, True, *delta)
        self.fake_input(EventType.ButtonRelease, self.buttons[1])
        self.fake_input(EventType.KeyRelease, self.mod1)
        self.loop(self.make_geometry_delta_test(delta))

    def test_resize_southeast(self):
        delta = Position(5, 10)
        self.warp_pointer(*self.relative_position(0.85)) # southeast corner
        self.fake_input(EventType.KeyPress, self.mod1)
        self.fake_input(EventType.ButtonPress, self.buttons[3])
        self.fake_input(EventType.MotionNotify, True, *delta)
        self.fake_input(EventType.ButtonRelease, self.buttons[3])
        self.fake_input(EventType.KeyRelease, self.mod1)
        self.loop(self.make_geometry_delta_test(Rectangle(*delta)))

    def test_resize_northwest(self):
        delta = Position(5, 10)

        # Shrink the window just a bit.
        self.warp_pointer(*self.relative_position(0.15)) # northwest corner
        self.fake_input(EventType.KeyPress, self.mod1)
        self.fake_input(EventType.ButtonPress, self.buttons[3])
        self.fake_input(EventType.MotionNotify, True, *delta)
        self.fake_input(EventType.ButtonRelease, self.buttons[3])
        self.fake_input(EventType.KeyRelease, self.mod1)
        self.loop(self.make_geometry_test(self.initial_geometry + delta -
                                          Rectangle(*delta)))

        # Shrink the window all the way down.
        self.fake_input(EventType.KeyPress, self.mod1)
        self.fake_input(EventType.ButtonPress, self.buttons[3])
        self.fake_input(EventType.MotionNotify, True,
                        self.initial_geometry.width,
                        self.initial_geometry.height)
        self.fake_input(EventType.ButtonRelease, self.buttons[3])
        self.fake_input(EventType.KeyRelease, self.mod1)
        self.loop(lambda: self.client.geometry.size() == Rectangle(1, 1))

    def test_resize_abort(self):
        delta = (20, 30)
        self.warp_pointer(*self.relative_position(0.85)) # southeast corner
        self.fake_input(EventType.KeyPress, self.mod1)
        self.fake_input(EventType.ButtonPress, self.buttons[3])
        self.fake_input(EventType.MotionNotify, True, *delta)
        self.fake_input(EventType.KeyRelease, self.mod1)
        self.loop(self.make_geometry_delta_test(Rectangle(*delta)))

        # Abort the resize by pressing "Escape".
        escape = self.keymap.keysym_to_keycode(XK_Escape)
        self.fake_input(EventType.KeyPress, escape)
        self.fake_input(EventType.KeyRelease, escape)
        self.fake_input(EventType.ButtonRelease, self.buttons[3])
        self.loop(self.make_geometry_test(self.initial_geometry))

if __name__ == "__main__":
    unittest.main()
