# -*- mode: Python; coding: utf-8 -*-

from array import array
import logging

import xcb
from xcb.xproto import BadName

__all__ = ["FontCache", "text_width"]

log = logging.getLogger("font")

class FontCache(object):
    """A simple cache for core X fonts and their properties."""

    def __init__(self, conn):
        assert isinstance(conn, xcb.Connection)
        self.conn = conn
        self.fonts = {}
        self.font_info = {}

    def __getitem__(self, name):
        """Return the font with the given name."""
        # Font names are case-insensitive; canonicalize to lower case.
        name = name.lower()

        if name not in self.fonts:
            font = self.conn.generate_id()
            try:
                self.conn.core.OpenFontChecked(font, len(name), name).check()
            except BadName:
                log.warning('Invalid font name "%s"; falling back to "fixed".',
                            name)
                font = self["fixed"]
            self.fonts[name] = font
        return self.fonts[name]

    def info(self, font):
        if font not in self.font_info:
            self.font_info[font] = self.conn.core.QueryFont(font).reply()
        return self.font_info[font]

def text_width(font_info, string):
    """Using the character metrics in font_info, compute and return the width
    of the given string."""
    def nonexistent_char(char_info):
        return (char_info.character_width == 0 and
                char_info.left_side_bearing == 0 and
                char_info.right_side_bearing == 0 and
                char_info.ascent == 0 and
                char_info.descent == 0)

    min_byte1 = font_info.min_byte1
    min_char_or_byte2 = font_info.min_char_or_byte2
    max_char_or_byte2 = font_info.max_char_or_byte2
    d = max_char_or_byte2 - min_char_or_byte2 + 1
    def get_char_info(row, col, default):
        try:
            info = font_info.char_infos[((row - min_byte1) * d) +
                                        (col - min_char_or_byte2)]
        except IndexError:
            info = None
        return info if info and not nonexistent_char(info) else default

    default = get_char_info(font_info.default_char >> 8,
                            font_info.default_char & 0xff,
                            None)
    if (default and
        (font_info.min_bounds.character_width ==
         font_info.max_bounds.character_width)):
        return font_info.min_bounds.character_width * len(string)

    string16 = array("B", unicode(string).encode("UTF-16BE"))
    infos = (get_char_info(string16[i], string16[i+1], default)
             for i in xrange(0, len(string16), 2))
    return sum(info.character_width for info in infos if info)
