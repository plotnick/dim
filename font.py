# -*- mode: Python; coding: utf-8 -*-

import xcb

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
            self.fonts[name] = self.conn.generate_id()
            self.conn.core.OpenFont(self.fonts[name], len(name), name)
        return self.fonts[name]

    def info(self, font):
        if font not in self.font_info:
            self.font_info[font] = self.conn.core.QueryFont(font).reply()
        return self.font_info[font]
