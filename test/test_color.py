# -*- mode: Python; coding: utf-8 -*-

from math import isnan
import unittest

import xcb
from xcb.xproto import *

from color import *

class TestRGB2HSV(unittest.TestCase):
    def assertNearEnough(self, a, b, n=3):
        def approx(x):
            return (None if isnan(x) else
                    round(x, 1) if x > 1 else
                    round(x, n))
        self.assertEqual(map(approx, a), map(approx, b))

    def test_rgbi_hsv(self):
        """Convert from RGBi to HSV and back again."""
        nan = float("NaN")
        # From the table of examples in the Wikipedia article on HSL & HSV.
        examples = [[(1.0, 1.0, 1.0), (nan, 0.0, 1.0)],
                    [(0.5, 0.5, 0.5), (nan, 0, 0.5)],
                    [(0.0, 0.0, 0.0), (nan, 0, 0)],
                    [(1.0, 0.0, 0.0), (0.0, 1.0, 1.0)],
                    [(0.75, 0.75, 0.0), (60.0, 1.0, 0.75)],
                    [(0.0, 0.5, 0.0), (120.0, 1.0, 0.5)],
                    [(0.5, 1.0, 1.0), (180.0, 0.5, 1.0)],
                    [(0.5, 0.5, 1.0), (240.0, 0.5, 1.0)],
                    [(0.75, 0.25, 0.75), (300.0, 0.667, 0.75)],
                    [(0.628, 0.643, 0.142), (61.8, 0.779, 0.643)],
                    [(0.255, 0.104, 0.918), (251.1, 0.887, 0.918)],
                    [(0.116, 0.675, 0.255), (134.9, 0.828, 0.675)],
                    [(0.941, 0.785, 0.053), (49.5, 0.944, 0.941)],
                    [(0.704, 0.187, 0.897), (283.7, 0.792, 0.897)],
                    [(0.931, 0.463, 0.316), (14.3, 0.661, 0.931)],
                    [(0.998, 0.974, 0.532), (56.9, 0.467, 0.998)],
                    [(0.099, 0.795, 0.591), (162.4, 0.875, 0.795)],
                    [(0.211, 0.149, 0.597), (248.3, 0.750, 0.597)],
                    [(0.495, 0.493, 0.721), (240.5, 0.316, 0.721)]]
        for rgbi_values, hsv_values in examples:
            rgbi = RGBi(*rgbi_values)
            hsv = HSVColor(*hsv_values)
            self.assertNearEnough(rgbi.hsv(), hsv)
            self.assertNearEnough(rgbi.hsv().rgbi(), rgbi)

class TestParseColor(unittest.TestCase):
    def test_hex_spec(self):
        self.assertEqual(parse_color("#3a7"), (0x3000, 0xa000, 0x7000))
        self.assertEqual(parse_color("#34ab78"), (0x3400, 0xab00, 0x7800))
        self.assertEqual(parse_color("#345abc789"), (0x3450, 0xabc0, 0x7890))
        self.assertEqual(parse_color("#3456abcd789a"), (0x3456, 0xabcd, 0x789a))

class TestColorCache(unittest.TestCase):
    # All of the returned ("actual") RGB values are hardware specific.
    # If you're not running 24-bit TrueColor, these tests will almost
    # certainly fail.

    def setUp(self):
        conn = xcb.connect()
        cmap = conn.get_setup().roots[conn.pref_screen].default_colormap
        self.color_cache = ColorCache(conn, cmap)

    def test_named_color(self):
        self.assertTrue(self.color_cache["snow"])
        self.assertEqual(set(self.color_cache.colors.keys()),
                         set(["snow", RGBColor(0xffff, 0xfafa, 0xfafa)]))

        self.assertRaises(BadName, lambda: self.color_cache["NoSuchColor"])

    def test_hex_spec(self):
        self.assertTrue(self.color_cache["#fffafa"])
        self.assertEqual(set(self.color_cache.colors.keys()),
                         set(["#fffafa", RGBColor(0xffff, 0xfafa, 0xfafa)]))

    def test_rgb(self):
        snow = RGBColor(0xffff, 0xfafa, 0xfafa)
        self.assertTrue(self.color_cache[snow])
        self.assertEqual(self.color_cache.colors.keys(), [snow])

    def test_invalid_color_spec(self):
        self.assertRaises(KeyError, lambda: self.color_cache[3.14159])

if __name__ == "__main__":
    unittest.main()
