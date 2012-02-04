# -*- mode: Python; coding: utf-8 -*-

from array import array

import xcb

from atom import AtomCache

__all__ = ["FontInfoCache", "FontInfo"]

class FontInfoCache(object):
    """A simple cache for information about core X fonts."""

    def __init__(self, conn, atoms=None):
        assert isinstance(conn, xcb.Connection)
        self.conn = conn
        self.font_info = {}
        self.atoms = atoms if atoms else AtomCache(conn)

    def __getitem__(self, font):
        if font not in self.font_info:
            query = self.conn.core.QueryFont(font)
            self.font_info[font] = FontInfo(query.reply(), self.atoms)
        return self.font_info[font]

class FontInfo(object):
    def __init__(self, info, atoms,
                 attrs=("draw_direction",
                        "min_char_or_byte2", "max_char_or_byte2",
                        "min_byte1", "max_byte1",
                        "all_chars_exist",
                        "default_char",
                        "min_bounds",
                        "max_bounds",
                        "font_ascent",
                        "font_descent",
                        "char_infos",
                        "properties")):
        for attr in attrs:
            setattr(self, attr, getattr(info, attr))

        self.default_char_info = self.char_info(self.default_char, None)

        for p in self.properties:
            if p.name == atoms["SPACING"]:
                self.spacing = atoms.name(p.value).upper()
                break
        else:
            self.spacing = None

    def char_info(self, char, default=True):
        if isinstance(char, basestring):
            char = ord(char)
        row = char >> 8
        col = char & 0xff
        if (self.min_byte1 <= row <= self.max_byte1 and
            self.min_char_or_byte2 <= col <= self.max_char_or_byte2):
            info = (self.char_infos[((row - self.min_byte1) *
                                     (self.max_char_or_byte2 -
                                      self.min_char_or_byte2 + 1)) +
                                    (col - self.min_char_or_byte2)]
                    if self.char_infos
                    else self.min_bounds)
        else:
            info = default
        if (not info or
            (info.character_width == 0 and
             info.left_side_bearing == 0 and
             info.right_side_bearing == 0 and
             info.ascent == 0 and
             info.descent == 0)):
            return self.default_char_info if default is True else default
        return info

    def text_width(self, string):
        if self.spacing == "M" or self.spacing == "C":
            # Monospaced font.
            return self.min_bounds.character_width * len(string)
        else:
            return sum(info.character_width
                       for info in map(self.char_info, string)
                       if info)

    def truncate(self, string, max_width):
        if self.text_width(string) <= max_width:
            return string
        ellipsis = u"…"
        ellipsis_info = self.char_info(ellipsis, None)
        if ellipsis_info:
            ellipsis_width = ellipsis_info.character_width
        else:
            ellipsis = "..."
            ellipsis_width = self.text_width(ellipsis)
        if max_width < ellipsis_width:
            return ""
        max_width -= ellipsis_width
        char_widths = [info.character_width
                       for info in map(self.char_info, string)
                       if info]
        i = len(string)
        while sum(char_widths[:i]) > max_width:
            i -= 1
        return string[:i] + ellipsis
