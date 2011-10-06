# -*- mode: Python; coding: utf-8 -*-

from cursorfont import *

class FontCursor(object):
    def __init__(self, conn, font_name="cursor"):
        self.conn = conn
        self.cursor_font = self.conn.generate_id()
        self.conn.core.OpenFontChecked(self.cursor_font,
                                       len(font_name), font_name).check()
        self.cursors = {}

    def __getitem__(self, key):
        if key in self.cursors:
            return self.cursors[key]

        # The cursor font contains the shape glyph followed by the mask
        # glyph; so character position 0 contains a shape, 1 the mask for 0,
	# 2 a shape, etc.
        self.cursors[key] = self.conn.generate_id()
        self.conn.core.CreateGlyphCursorChecked(self.cursors[key],
                                                self.cursor_font,
                                                self.cursor_font,
                                                key, key + 1,
                                                0x0, 0x0, 0x0,
                                                0xffff, 0xffff, 0xffff).check()
        return self.cursors[key]
