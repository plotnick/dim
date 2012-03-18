# -*- mode: Python; coding: utf-8 -*-

from array import array

import xcb
from xcb.xproto import CHARINFO

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
    def __init__(self, info, atoms):
        for attr in ("draw_direction",
                     "min_char_or_byte2", "max_char_or_byte2",
                     "min_byte1", "max_byte1",
                     "all_chars_exist",
                     "default_char",
                     "min_bounds",
                     "max_bounds",
                     "font_ascent",
                     "font_descent",
                     "properties"):
            setattr(self, attr, getattr(info, attr))

        # Rather than storing the list of CHARINFO instances, we'll keep
        # only the underlying buffer, and re-construct the instances on
        # demand. The issue here is space: in a font like the ISO-10646
        # version of Misc-Fixed, the 65,536 CHARINFO objects consume nearly
        # 90 megabytes of memory on a 64-bit system, which is quite a lot
        # of overhead for 768 kilobytes of raw data.
        self.char_infos = info.char_infos.buf()

        # Storing these bounds as a tuple lets us replace four attribute
        # lookups with one, which makes a measurable performance difference
        # in char_info.
        self.index_bounds = (self.min_byte1,
                             self.max_byte1,
                             self.min_char_or_byte2,
                             self.max_char_or_byte2)

        self.default_char_info = self.char_info(self.default_char, None)

        for p in self.properties:
            if p.name == atoms["SPACING"]:
                self.spacing = atoms.name(p.value).upper()
                break
        else:
            self.spacing = None

    def char_info(self, char, default=True, charinfo_size=12):
        """Return the CHARINFO for the given character.

        If the given character is nonexistent or missing, then the info
        returned depends on the default argument. If default is True, then
        the CHARINFO for the font's default character is returned (which
        may be None if that character is itself nonexistent or missing).
        Otherwise, the provided default is returned."""
        # See the QueryFont entry in the X protocol reference manual.
        try:
            char = ord(char)
        except TypeError:
            # An integer is acceptable as a character designator.
            pass
        byte1 = char >> 8
        byte2 = char & 0xff
        (min_byte1, max_byte1, min_byte2, max_byte2) = self.index_bounds
        if (min_byte1 <= byte1 <= max_byte1 and
            min_byte2 <= byte2 <= max_byte2):
            offset = (((byte1 - min_byte1) * (max_byte2 - min_byte2 + 1)) +
                      (byte2 - min_byte2)) * charinfo_size
            try:
                info = CHARINFO(self.char_infos, offset, charinfo_size)
            except Exception:
                return self.min_bounds
        else:
            # Undefined character.
            return self.default_char_info if default is True else default
        if (info.character_width == 0 and
            info.left_side_bearing == 0 and
            info.right_side_bearing == 0 and
            info.ascent == 0 and
            info.descent == 0):
            # Nonexistent character.
            return self.default_char_info if default is True else default
        return info

    def text_width(self, string):
        """Compute the width of the given string."""
        if self.spacing == "M" or self.spacing == "C":
            # Monospaced font.
            return self.min_bounds.character_width * len(string)
        else:
            return sum(info.character_width
                       for info in map(self.char_info, string)
                       if info)

    def truncate(self, string, max_width):
        """Return a possibly-truncated version of the given string that fits
        in max_width pixels.

        If there is room, an ellipsis will be appended to the truncated
        string to indicate that truncation has occurred. The width of the
        ellipsis is accounted for in the computation, thus maintaining the
        invariant that the width of whatever string is returned will be
        less than or equal to max_width."""
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
