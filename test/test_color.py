# -*- mode: Python; coding: utf-8 -*-

from math import isnan
import unittest

import xcb
from xcb.xproto import *

from color import *

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
