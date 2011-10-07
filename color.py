# -*- mode: Python; coding: utf-8 -*-

import re

from xutil import card16

class InvalidColorName(Exception):
    pass

def parse_color(name, pattern=re.compile("#([0-9a-z]+)$", re.I)):
    """Parse a device-independent hexadecimal color specification."""
    match = pattern.match(name)
    if not match:
        raise InvalidColorName
    spec = match.group(1)

    # Adapted from XParseColor.
    n = len(spec)
    if n != 3 and n != 6 and n != 9 and n != 12:
        raise InvalidColorName
    n //= 3
    g = b = 0
    i = 0
    while i < len(spec):
        r, g, b = g, b, 0
        for j in range(n):
            b = (b << 4) | int(spec[i], 16)
            i += 1
    n <<= 2
    n = 16 - n
    return (r << n, g << n, b << n)

class ColorCache(object):
    """A simple auto-allocating colormap wrapper."""

    def __init__(self, conn, cmap):
        self.conn = conn
        self.cmap = cmap
        self.colors = {}

    def __getitem__(self, key):
        if isinstance(key, basestring):
            key = key.lower()
            if key in self.colors:
                return self.colors[key]
            try:
                r, g, b = parse_color(key)
            except InvalidColorName:
                # Assume the key is a color name, and ask the server to
                # interpret it.
                reply = self.conn.core.AllocNamedColor(self.cmap,
                                                       len(key), key).reply()
                exact = (reply.exact_red, reply.exact_green, reply.exact_blue)
                self.colors[key] = self.colors[exact] = reply.pixel
                return reply.pixel
        elif isinstance(key, tuple):
            if key in self.colors:
                return self.colors[key]
            r, g, b = key
        else:
            raise KeyError("invalid color specification %r" % key)
        reply = self.conn.core.AllocColor(self.cmap,
                                          card16(r),
                                          card16(g),
                                          card16(b)).reply()
        actual = (reply.red, reply.green, reply.blue)
        self.colors[key] = self.colors[actual] = reply.pixel
        return reply.pixel