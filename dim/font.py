# -*- mode: Python; coding: utf-8 -*-

import logging

import xcb
from xcb.xproto import BadName

__all__ = ["FontCache"]

log = logging.getLogger("font")

class FontCache(object):
    """A simple cache for core X fonts."""

    def __init__(self, conn):
        assert isinstance(conn, xcb.Connection)
        self.conn = conn
        self.fonts = {}

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
