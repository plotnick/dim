# -*- mode: Python; coding: utf-8 -*-

import unittest

from geometry import *
from properties import WMSizeHints

class TestGeometryClasses(unittest.TestCase):
    def test_position(self):
        p = Position(x=100, y=-50)
        self.assertTrue(p)
        self.assertEqual(p, (100, -50))
        self.assertEqual(p + 5, (105, -45))
        self.assertEqual(p + 5, 5 + p)
        self.assertEqual(p - 5, (95, -55))
        self.assertEqual(p + p, (200, -100))
        self.assertEqual(p - p, (0, 0))
        self.assertEqual(p * 2, (200, -100))
        self.assertEqual(p * 2, 2 * p)
        self.assertEqual(str(p), "+100-50")
        self.assertFalse(Position(0, 0))

    def test_rectangle(self):
        r = Rectangle(width=3, height=5)
        self.assertTrue(r)
        self.assertEqual(r, (3, 5))
        self.assertEqual(r + 5, (8, 10))
        self.assertEqual(r + 5, 5 + r)
        self.assertEqual(r - 5, (-2, 0))
        self.assertEqual(r + r, (6, 10))
        self.assertEqual(r - r, (0, 0))
        self.assertEqual(r * 2, (6, 10))
        self.assertEqual(r * 2, 2 * r)
        self.assertEqual(str(r), "3x5")
        self.assertFalse(Rectangle(0, 0))

    def test_geometry(self):
        g = Geometry(x=100, y=-50, width=3, height=5, border_width=1)
        p = Position(x=10, y=20)
        self.assertTrue(g)
        self.assertEqual(g, (100, -50, 3, 5, 1))
        self.assertEqual(g + p, g._replace(x=g.x + p.x, y=g.y + p.y))
        self.assertEqual(g + 10, g._replace(x=g.x + 10, y=g.y + 10))
        self.assertEqual(g - 10, g._replace(x=g.x - 10, y=g.y - 10))
        self.assertEqual(g + 10, 10 + g)
        self.assertEqual(str(g), "3x5+100-50")
        self.assertFalse(Geometry(0, 0, 0, 0, 0))

    def test_aspect_ratio(self):
        a = AspectRatio(16, 9)
        self.assertTrue(a)
        self.assertEqual(a, (16, 9))
        self.assertEqual(str(a), "16/9")
        self.assertFalse(AspectRatio(0, 100))

class TestIsMoveOnly(unittest.TestCase):
    """Test case for the is_move_only function."""

    def test_null_geometry(self):
        """Test is_move_only with null geometry"""
        self.assertFalse(is_move_only(None, None))
        self.assertFalse(is_move_only(None, Geometry(1, 1, 1, 1, 1)))
        self.assertFalse(is_move_only(Geometry(1, 1, 1, 1, 1), None))

    def test_is_move_only(self):
        """Test is_move_only"""
        g = Geometry(1, 1, 1, 1, 1)
        self.assertFalse(is_move_only(g, Geometry(1, 1, 1, 1, 1)))
        self.assertFalse(is_move_only(g, Geometry(2, 2, 2, 2, 1)))
        self.assertFalse(is_move_only(g, Geometry(2, 2, 1, 1, 2)))
        self.assertTrue(is_move_only(g, Geometry(2, 2, 1, 1, 1)))

class TestConstrainSize(unittest.TestCase):
    """Test case for the constrain_size function."""

    min_size = Rectangle(10, 17)
    resize_inc = Rectangle(6, 13)
    base_size = Rectangle(4, 4)

    def assertConstraint(self, size, expected_size):
        self.assertEqual(constrain_size(size, self.hints), expected_size)

    def test_constrain_size_min_size(self):
        self.hints = WMSizeHints(min_size=self.min_size)
        self.assertConstraint(Rectangle(-2, -4), self.min_size)
        self.assertConstraint(Rectangle(0, 0), self.min_size)
        self.assertConstraint(self.min_size, self.min_size)
        self.assertConstraint(Rectangle(25, 25), Rectangle(25, 25))

    def test_constrain_size_resize_inc(self):
        self.hints = WMSizeHints(resize_inc=self.resize_inc)
        self.assertConstraint(Rectangle(3, 5), Rectangle(1, 1))
        self.assertConstraint(Rectangle(7, 14), Rectangle(7, 14))
        self.assertConstraint(Rectangle(14, 19), Rectangle(13, 14))
        self.assertConstraint(Rectangle(14, 27), Rectangle(13, 27))

    def test_constrain_base_inc(self):
        self.hints = WMSizeHints(resize_inc=self.resize_inc,
                                 base_size=self.base_size)
        self.assertConstraint(Rectangle(0, 0), self.base_size)
        self.assertConstraint(self.base_size, self.base_size)
        self.assertConstraint(Rectangle(5, 5), self.base_size)
        self.assertConstraint(Rectangle(6, 13), self.base_size)
        self.assertConstraint(Rectangle(10, 17), Rectangle(10, 17))
        self.assertConstraint(Rectangle(12, 17), Rectangle(10, 17))
        self.assertConstraint(Rectangle(16, 17), Rectangle(16, 17))
        self.assertConstraint(Rectangle(22, 30), Rectangle(22, 30))

    def test_constrain_min_base_inc(self):
        self.hints = WMSizeHints(min_size=self.min_size,
                                 resize_inc=self.resize_inc,
                                 base_size=self.base_size)
        self.assertConstraint(Rectangle(0, 0), self.min_size)
        self.assertConstraint(self.base_size, self.min_size)
        self.assertConstraint(self.min_size, self.min_size)
        self.assertConstraint(Rectangle(12, 17), self.min_size)
        self.assertConstraint(Rectangle(16, 17), Rectangle(16, 17))
        self.assertConstraint(Rectangle(22, 30), Rectangle(22, 30))

if __name__ == "__main__":
    unittest.main()
