# -*- mode: Python; coding: utf-8 -*-

from operator import lt, gt
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
        self.assertEqual(p // 2, (50, -25))
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
        self.assertEqual(r // 2, (1, 2))
        self.assertEqual(str(r), "3x5")
        self.assertFalse(Rectangle(0, 0))

    def test_geometry(self):
        g = Geometry(x=100, y=-50, width=3, height=5, border_width=1)
        p = Position(x=10, y=20)
        r = Rectangle(width=2, height=4)
        self.assertTrue(g)
        self.assertEqual(g, (100, -50, 3, 5, 1))
        self.assertEqual(g + p, g._replace(x=g.x + p.x, y=g.y + p.y))
        self.assertEqual(g + 10, g._replace(x=g.x + 10, y=g.y + 10))
        self.assertEqual(g - 10, g._replace(x=g.x - 10, y=g.y - 10))
        self.assertEqual(g + 10, 10 + g)
        self.assertEqual(g + r,
                         g._replace(width=g.width + r.width,
                                    height=g.height + r.height))
        self.assertEqual(r + g, g + r)
        self.assertEqual(str(g), "3x5+100-50")
        self.assertFalse(Geometry(0, 0, 0, 0, 0))

    def test_aspect_ratio(self):
        a = AspectRatio(16, 9)
        self.assertTrue(a)
        self.assertEqual(a, (1600, 900))
        self.assertTrue(a < (1600, 800))
        self.assertFalse(a < (1600, 1200))
        self.assertFalse(a > (1600, 800))
        self.assertTrue(a > (1600, 1200))
        self.assertEqual(str(a), "16:9")
        self.assertFalse(AspectRatio(None, None))
        self.assertFalse(AspectRatio(0, 100))
        self.assertFalse(AspectRatio(0, 0))
        self.assertEqual(AspectRatio(16, 9).crop(Rectangle(1600, 800)),
                         Rectangle(1600, 900))
        self.assertEqual(AspectRatio(3, 4).crop(Rectangle(1600, 1600)),
                         Rectangle(1200, 1600))

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
        self.assertFalse(is_move_only(g, Geometry(2, 2, 2, 2, 1))) # resize
        self.assertFalse(is_move_only(g, Geometry(2, 2, 1, 1, 2))) # bw change
        self.assertTrue(is_move_only(g, Geometry(2, 2, 1, 1, 1))) # move
        self.assertTrue(is_move_only(g, g)) # trivial move

if __name__ == "__main__":
    unittest.main()
