# -*- mode: Python; coding: utf-8 -*-

from logging import debug, info, warning, error

import xcb
from xcb.xproto import BadName

__all__ = ["FontCache"]

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
                warning('Invalid font name "%s"; falling back to "fixed".' %
                        name)
                font = self["fixed"]
            self.fonts[name] = font
        return self.fonts[name]

    def info(self, font):
        if font not in self.font_info:
            self.font_info[font] = self.conn.core.QueryFont(font).reply()
        return self.font_info[font]
