# -*- mode: Python; coding: utf-8 -*-

from operator import itemgetter
import unittest

import xcb
from xcb.xproto import *

from cursor import *
from geometry import *
from keysym import *
from moveresize import bsearch_floor, bsearch_ceil, \
    ClientMove, ClientResize, MoveResize
from properties import WMSizeHints
from xutil import int16

from test_manager import EventType, TestClient, WMTestCase, WarpedPointer

class MockDecorator(object):
    def message(self, message):
        pass

class MockProperties(object):
    def __init__(self, size_hints):
        self.wm_normal_hints = size_hints

class MockClient(object):
    def __init__(self, test, geometry, size_hints=WMSizeHints()):
        self.test = test
        self.absolute_geometry = self.frame_geometry = self.geometry = geometry
        self.screen = None
        self.window = 0
        self.decorator = MockDecorator()
        self.properties = MockProperties(size_hints)

    def move(self, position):
        self.test.assertTrue(isinstance(position, Position))
        self.geometry = self.geometry._replace(x=position.x, y=position.y)
        return self.geometry

    def resize(self, size, border_width=None, gravity=Gravity.NorthWest):
        self.test.assertTrue(isinstance(size, Rectangle))
        return self.configure(self.geometry.resize(size, border_width, gravity))

    def configure(self, geometry):
        self.test.assertTrue(isinstance(geometry, Geometry))
        self.geometry = geometry
        return geometry

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

class ModButtonDown(object):
    """A little context manager for move/resize tests. On enter, simulates
    the press of a modifier key, then a pointer button, and then the release
    of the modifier. On exit, it releases the pointer button."""

    def __init__(self, test, modifier, button):
        self.test = test
        self.modifier = modifier
        self.button = button

    def __enter__(self):
        self.test.fake_input(EventType.KeyPress, self.modifier)
        self.test.fake_input(EventType.ButtonPress, self.button)
        self.test.fake_input(EventType.KeyRelease, self.modifier)

    def __exit__(self, *exc_info):
        self.test.fake_input(EventType.ButtonRelease, self.button)

class TestMoveResize(WMTestCase):
    """Integration test for interactive move/resize."""

    wm_class = MoveResize

    button_bindings = {("control", 1): MoveResize.move_window,
                       ("control", 3): MoveResize.resize_window}

    def setUp(self):
        super(TestMoveResize, self).setUp(button_bindings=self.button_bindings)
        self.control = self.modmap[MapIndex.Control][0]
        self.initial_geometry = Geometry(x=0, y=0, width=100, height=100,
                                         border_width=1)
        self.client = self.add_client(TestClient(self.initial_geometry))
        self.client.map()
        self.loop(lambda: self.client.mapped and self.client.managed)

    def relative_position(self, ratio):
        return (self.initial_geometry.position() + 
                self.initial_geometry.size() * ratio)

    def make_geometry_test(self, geometry):
        return lambda: self.client.frame_geometry == geometry

    def make_geometry_delta_test(self, delta):
        return self.make_geometry_test(self.initial_geometry + delta)

    def test_move(self):
        with WarpedPointer(self, self.relative_position(0.5)): # center
            with ModButtonDown(self, self.control, self.buttons[1]):
                delta = Position(5, 10)
                self.fake_input(EventType.MotionNotify, True, *delta)
                self.loop(self.make_geometry_delta_test(delta))

    def test_resize_southeast(self):
        with WarpedPointer(self, self.relative_position(0.85)): # southeast
            with ModButtonDown(self, self.control, self.buttons[3]):
                delta = Position(5, 10)
                self.fake_input(EventType.MotionNotify, True, *delta)
                self.loop(self.make_geometry_delta_test(Rectangle(*delta)))

    def test_resize_northwest(self):
        with WarpedPointer(self, self.relative_position(0.15)): # northwest
            with ModButtonDown(self, self.control, self.buttons[3]):
                # Shrink the window just a bit.
                delta = Position(5, 10)
                self.fake_input(EventType.MotionNotify, True, *delta)
                self.loop(self.make_geometry_test(self.initial_geometry +
                                                  delta - Rectangle(*delta)))

                # Shrink the window all the way down.
                self.fake_input(EventType.KeyPress, self.control)
                self.fake_input(EventType.ButtonPress, self.buttons[3])
                self.fake_input(EventType.MotionNotify, True,
                                self.initial_geometry.width,
                                self.initial_geometry.height)
                self.loop(lambda: self.client.geometry.size() == (1, 1))

    def test_resize_abort(self):
        with WarpedPointer(self, self.relative_position(0.85)): # southeast
            with ModButtonDown(self, self.control, self.buttons[3]):
                delta = (20, 30)
                self.fake_input(EventType.MotionNotify, True, *delta)
                self.loop(self.make_geometry_delta_test(Rectangle(*delta)))

                # Abort the resize by pressing "Escape".
                escape = self.keymap.keysym_to_keycode(XK_Escape)
                self.fake_input(EventType.KeyPress, escape)
                self.fake_input(EventType.KeyRelease, escape)
                self.loop(self.make_geometry_test(self.initial_geometry))

    def test_constrained_resize(self):
        min_size = Rectangle(10, 10)
        inc = Rectangle(10, 10)
        self.client.set_size_hints(WMSizeHints(min_size=min_size,
                                               resize_inc=inc))

        with WarpedPointer(self, self.relative_position(0.85)): # southeast
            with ModButtonDown(self, self.control, self.buttons[3]):
                self.fake_input(EventType.MotionNotify, True, *(inc // 2))
                self.loop(self.make_geometry_delta_test(Position(0, 0)))
                self.fake_input(EventType.MotionNotify, True, *inc)
                self.loop(self.make_geometry_delta_test(inc))
                self.fake_input(EventType.MotionNotify, True, *inc)
                self.loop(self.make_geometry_delta_test(2 * inc))
                self.fake_input(EventType.MotionNotify, False, 0, 0)
                min_geometry = self.initial_geometry.resize(min_size)
                self.loop(self.make_geometry_test(min_geometry))

    def test_screen_edge_resistance(self):
        with WarpedPointer(self, self.relative_position(0.5)): # center
            with ModButtonDown(self, self.control, self.buttons[1]):
                r = -Position(40, 40); half_r = r // 2
                self.fake_input(EventType.MotionNotify, True, *half_r)
                self.loop(self.make_geometry_delta_test((0, 0))) # resist
                self.fake_input(EventType.MotionNotify, True, *half_r)
                self.loop(self.make_geometry_delta_test(r))

    def test_window_edge_resistance(self):
        right = TestClient(self.initial_geometry +
                           Position(self.initial_geometry.right_edge(), 0))
        below = TestClient(self.initial_geometry +
                           Position(0, self.initial_geometry.bottom_edge()))
        self.add_client(right); right.map()
        self.add_client(below); below.map()
        self.loop(lambda: (right.mapped and below.mapped and
                           right.managed and below.managed))

        with WarpedPointer(self, self.relative_position(0.5)): # center
            with ModButtonDown(self, self.control, self.buttons[1]):
                r = Position(20, 20); half_r = r // 2
                self.fake_input(EventType.MotionNotify, True, *half_r)
                self.loop(self.make_geometry_delta_test((0, 0))) # resist
                self.fake_input(EventType.MotionNotify, True, *half_r)
                self.loop(self.make_geometry_delta_test(r))

class TestBinarySearch(unittest.TestCase):
    def test_bsearch_floor(self):
        sequence = [(1, 1), (2, 1), (2, 2), (3, 1)]
        self.assertEqual(bsearch_floor(0, sequence, key=itemgetter(0)),
                         set([]))
        self.assertEqual(bsearch_floor(1, sequence, key=itemgetter(0)),
                         set([(1, 1)]))
        self.assertEqual(bsearch_floor(2.5, sequence, key=itemgetter(0)),
                         set([(2, 1), (2, 2)]))
        self.assertEqual(bsearch_floor(4, sequence, key=itemgetter(0)),
                         set([(3, 1)]))

    def test_bsearch_ceil(self):
        sequence = [(1, 1), (2, 1), (2, 2), (3, 1)]
        self.assertEqual(bsearch_ceil(0, sequence, key=itemgetter(0)),
                         set([(1, 1)]))
        self.assertEqual(bsearch_ceil(1, sequence, key=itemgetter(0)),
                         set([(1, 1)]))
        self.assertEqual(bsearch_ceil(1.5, sequence, key=itemgetter(0)),
                         set([(2, 1), (2, 2)]))
        self.assertEqual(bsearch_ceil(4, sequence, key=itemgetter(0)),
                         set([]))

if __name__ == "__main__":
    unittest.main()
