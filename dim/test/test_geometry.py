# -*- mode: Python; coding: utf-8 -*-

from operator import lt, gt
import unittest

from xcb.xproto import Gravity

from dim.geometry import *
from dim.properties import WMSizeHints

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

    def test_resize(self):
        g = Geometry(x=0, y=0, width=100, height=100, border_width=1)
        self.assertEqual(g.resize(Rectangle(50, 200)),
                         Geometry(0, 0, 50, 200, 1))
        self.assertEqual(g.resize(Rectangle(50, 200), 0),
                         Geometry(0, 0, 50, 200, 0))
        self.assertEqual(g.resize(Rectangle(50, 200), 1, Gravity.SouthEast),
                         Geometry(50, -100, 50, 200, 1))
        self.assertEqual(g.resize(Rectangle(50, 200), 0, Gravity.SouthEast),
                         Geometry(52, -98, 50, 200, 0))
        self.assertEqual(g.resize(Rectangle(50, 200), 2, Gravity.SouthEast),
                         Geometry(48, -102, 50, 200, 2))

    def assertIntersecting(self, x, y):
        self.assertTrue(x & y)
        self.assertTrue(y & x)

    def assertNonIntersecting(self, x, y):
        self.assertFalse(x & y)
        self.assertFalse(y & x)

    def test_intersection(self):
        g = Geometry(x=0, y=0, width=10, height=10, border_width=0)
        self.assertIntersecting(Position(0, 0), g)
        self.assertIntersecting(Position(5, 5), g)
        self.assertNonIntersecting(Position(10, 10), g)
        self.assertIntersecting(g, g)
        self.assertIntersecting(Geometry(9, 9, 5, 5, 0), g)
        self.assertIntersecting(Geometry(0, 0, 1, 1, 0), g)
        self.assertNonIntersecting(Geometry(-10, -10, 5, 5, 0), g)

    def test_contains(self):
        g = Geometry(x=0, y=0, width=10, height=10, border_width=0)
        self.assertTrue(Position(0, 0) in g)
        self.assertTrue(Position(5, 5) in g)
        self.assertTrue(Position(10, 10) not in g)
        self.assertFalse(g in g)
        self.assertTrue(Geometry(1, 1, 5, 5, 0) in g)
        self.assertTrue(Geometry(1, 1, 5, 10, 0) not in g)

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

if __name__ == "__main__":
    unittest.main()
