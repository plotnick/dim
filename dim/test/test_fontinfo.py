# -*- mode: Python; coding: utf-8 -*-

import unittest

import xcb
from xcb.xproto import *

from dim.fontinfo import FontInfoCache, FontInfo
from dim.xutil import string16

fn_fixed = "-misc-fixed-medium-r-semicondensed--0-0-75-75-c-0-iso8859-1"
fn_helvetica = "-*-helvetica-medium-r-*-*-12-*-*-*-*-*-iso10646-1"

class FontInfoTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = xcb.connect()

    def tearDown(self):
        self.conn.disconnect()

    def open_font(self, font_name):
        font = self.conn.generate_id()
        name = font_name.encode("Latin-1")
        self.conn.core.OpenFontChecked(font, len(name), name).check()
        return font

class TestFontInfoCache(FontInfoTestCase):
    def test_cache(self):
        cache = FontInfoCache(self.conn)

        fixed = self.open_font(fn_fixed)
        fixed_info = cache[fixed]
        self.assertTrue(isinstance(fixed_info, FontInfo))
        self.assertTrue(fixed_info is cache[fixed])

        helvetica = self.open_font(fn_helvetica)
        helvetica_info = cache[helvetica]
        self.assertTrue(isinstance(helvetica_info, FontInfo))
        self.assertTrue(helvetica_info is cache[helvetica])
        self.assertTrue(helvetica_info is not fixed_info)

class TestFontInfo(FontInfoTestCase):
    def setUp(self):
        super(TestFontInfo, self).setUp()

        self.cache = FontInfoCache(self.conn)
        self.fixed = self.open_font(fn_fixed)
        self.helvetica = self.open_font(fn_helvetica)
        self.fixed_info = self.cache[self.fixed]
        self.helvetica_info = self.cache[self.helvetica]

    def query_text_extents(self, font, string):
        return self.conn.core.QueryTextExtents(font,
                                               len(string),
                                               string16(string)).reply()

    def text_width(self, font, string):
        return self.query_text_extents(font, string).overall_width

    def test_font_info(self):
        self.assertEqual(self.fixed_info.draw_direction,
                         FontDraw.LeftToRight)
        self.assertTrue(self.fixed_info.font_ascent > 0)
        self.assertTrue(self.fixed_info.font_descent > 0)
        self.assertTrue(self.fixed_info.min_bounds.character_width > 0)
        self.assertEqual(self.fixed_info.min_bounds.character_width,
                         self.fixed_info.max_bounds.character_width)

        self.assertEqual(self.helvetica_info.draw_direction,
                         FontDraw.LeftToRight)
        self.assertTrue(self.helvetica_info.font_ascent > 0)
        self.assertTrue(self.helvetica_info.font_descent > 0)
        self.assertTrue(self.helvetica_info.max_bounds.character_width > 0)
        self.assertTrue(self.helvetica_info.min_bounds.character_width <
                        self.helvetica_info.max_bounds.character_width)

    def test_default_char_info(self):
        default_char = self.fixed_info.default_char
        default_char_info = self.fixed_info.char_info(default_char)
        self.assertTrue(isinstance(default_char_info, CHARINFO))
        self.assertEqual(default_char_info.character_width,
                         self.fixed_info.min_bounds.character_width)

        # Test default argument handling with an undefined character.
        c = (self.fixed_info.max_byte1 + 1) << 8
        self.assertEqual(self.fixed_info.char_info(c), default_char_info)
        self.assertEqual(self.fixed_info.char_info(c, True), default_char_info)
        self.assertEqual(self.fixed_info.char_info(c, None), None)

        # We assume that ASCII DEL is defined but nonexistent.
        self.assertEqual(self.fixed_info.char_info("\177"), default_char_info)

    def test_char_info(self):
        # We'll do this test with a proportional font; it's not very
        # interesting with a fixed-width font.
        default_char = self.helvetica_info.default_char
        default_char_info = self.helvetica_info.char_info(default_char)

        x = self.helvetica_info.char_info("x")
        self.assertNotEqual(x, default_char_info)
        self.assertTrue(x.character_width > 0)
        self.assertTrue(x.ascent > 0)
        self.assertTrue(x.descent == 0)

        l = self.helvetica_info.char_info("l")
        m = self.helvetica_info.char_info("M")
        self.assertTrue(m.character_width > l.character_width)

    def test_text_width(self):
        string = u"The quick brown fox jumps over the lazy dog—1, 2, 2½, …"
        self.assertEqual(self.fixed_info.text_width(string),
                         self.text_width(self.fixed, string))
        self.assertEqual(self.helvetica_info.text_width(string),
                         self.text_width(self.helvetica, string))

if __name__ == "__main__":
    unittest.main()
