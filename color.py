# -*- mode: Python; coding: utf-8 -*-

from __future__ import division

from collections import namedtuple
from math import isnan
import re

from xutil import card16, int16

class Color(tuple):
    __slots__ = ()

    def rgb(self):
        return None

class RGBColor(Color, namedtuple("RGB", "red, green, blue")):
    __slots__ = ()

    def rgb(self):
        return self

    def hsv(self):
        # See the Wikipedia article on HSL and HSV.
        r, g, b = self
        v = max(r, g, b)
        c = v - min(r, g, b)
        s = 0 if c == 0 else c / v
        h = (float("NaN") if c == 0 else
             ((g - b) / c) % 6 if v == r else
             ((b - r) / c) + 2 if v == g else
             ((r - g) / c) + 4)
        h *= 60
        return HSVColor(h, s, v)

class RGBi(RGBColor):
    __slots__ = ()

    def rgb(self):
        r, g, b = self
        return RGBColor(int16(r * 0xffff), int16(g * 0xffff), int16(b * 0xffff))

class HSVColor(Color, namedtuple("HSV", "hue, saturation, value")):
    __slots__ = ()

    def rgbi(self):
        # See the Wikipedia article on HSL and HSV.
        h, s, v = self
        h %= 360
        assert 0.0 <= s <= 1.0
        assert 0.0 <= v <= 1.0

        c = v * s
        i = h / 60
        x = c * (1 - abs((i % 2) - 1))
        r, g, b = ((0, 0, 0) if isnan(h) else
                   (c, x, 0) if 0 <= i < 1 else 
                   (x, c, 0) if 1 <= i < 2 else
                   (0, c, x) if 2 <= i < 3 else
                   (0, x, c) if 3 <= i < 4 else
                   (x, 0, c) if 4 <= i < 5 else
                   (c, 0, x))
        m = v - c
        return RGBi(r + m, g + m, b + m)

    def rgb(self):
        return self.rgbi().rgb()

    def __eq__(self, other):
        return ((True if isnan(self.hue) and isnan(other.hue) else
                 self.hue == other.hue) and
                self.saturation == other.saturation and
                self.value == other.value)

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
    return RGBColor(r << n, g << n, b << n)

class ColorCache(object):
    """A simple auto-allocating colormap wrapper."""

    def __init__(self, conn, cmap):
        self.conn = conn
        self.cmap = cmap
        self.colors = {}

    def __getitem__(self, key):
        """Given a color specification (hex string, color name, or RGB triple),
        return the corresponding pixel value."""
        if isinstance(key, basestring):
            key = key.lower() # case doesn't matter; canonicalize to lower
            if key in self.colors:
                return self.colors[key]
            try:
                color = parse_color(key)
            except InvalidColorName:
                # Assume the key is a color name, and ask the server to
                # look it up.
                reply = self.conn.core.AllocNamedColor(self.cmap,
                                                       len(key), key).reply()
                exact = RGBColor(reply.exact_red,
                                 reply.exact_green,
                                 reply.exact_blue)
                self.colors[key] = self.colors[exact] = reply.pixel
                return reply.pixel
        elif isinstance(key, Color):
            if key in self.colors:
                return self.colors[key]
            color = key.rgb()
        else:
            raise KeyError("invalid color specification %r" % (key,))
        reply = self.conn.core.AllocColor(self.cmap,
                                          card16(color.red),
                                          card16(color.green),
                                          card16(color.blue)).reply()
        actual = RGBColor(reply.red, reply.green, reply.blue)
        self.colors[key] = self.colors[actual] = reply.pixel
        return reply.pixel
