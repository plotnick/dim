# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple
import operator
from struct import Struct

from xcb.xproto import *

__all__ = ["power_of_2", "popcount", "int16",
           "Position", "Geometry", "Rectangle", "AspectRatio",
           "is_synthetic_event", "configure_notify",
           "select_values", "value_list",
           "AtomCache"]

def power_of_2(x):
    """Check whether x is a power of 2."""
    return isinstance(x, int) and x > 0 and x & (x - 1) == 0

def popcount(x):
    """Count the number of 1 bits in the binary representation of x."""
    return bin(x).count("1")

def int16(x):
    """Truncate an integer to 16 bits, ignoring sign."""
    return x & 0xffff

Position = namedtuple("Position", "x, y")
Position.__str__ = lambda self: "%+d%+d" % self

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.__str__ = lambda self: "%ux%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)
Geometry.translate = lambda self, x, y: \
    self._replace(x=self.x + x, y=self.y + y)

Rectangle = namedtuple("Rectangle", "width, height")
Rectangle.__str__ = lambda self: "%ux%u" % self

AspectRatio = namedtuple("AspectRatio", "numerator, denominator")
Rectangle.__str__ = lambda self: "%u/%u" % self

def is_synthetic_event(event):
    """Returns True if the given event was produced via a SendEvent request."""
    # Events begin with an 8-bit type code; synthetic events have the
    # most-significant bit of this code set.
    return (ord(event[0]) & 0x80) != 0

class AtomCache(object):
    """A simple cache for X atoms."""

    def __init__(self, conn, names=[]):
        assert isinstance(conn, xcb.Connection)
        self.conn = conn
        self.atoms = {}
        if names:
            self.prime_cache(names)

    def prime_cache(self, names):
        cookies = [self.conn.core.InternAtom(False, len(name), name)
                   for name in names]
        for name, cookie in zip(names, cookies):
            self.atoms[name] = cookie.reply().atom

    def __getitem__(self, name):
        try:
            # Is it in the cache?
            return self.atoms[name]
        except KeyError:
            pass
        try:
            # Is it one of the pre-defined atoms?
            return getattr(Atom, name)
        except AttributeError:
            pass
        # Request the atom from the server and cache it.
        atom = self.conn.core.InternAtom(False, len(name), name).reply().atom
        self.atoms[name] = atom
        return atom

def select_values(value_mask, values):
    """Create a value-list from the supplied possible values according to the
    bits in the given value-mask."""
    return [values[i] for i in range(len(values)) if value_mask & (1 << i)]

def value_list(flag_class, **kwargs):
    """Construct and return a value-mask and value-list from the supplied
    keyword arguments. The flag_class should be an object with attributes
    that define the flags for the possible values."""
    flags = {}
    for attr in dir(flag_class):
        if not attr.startswith("_"):
            value = getattr(flag_class, attr, None)
            if power_of_2(value):
                flags[attr.lower()] = value
    assert len(set(flags.values())) == len(flags), \
        "Duplicate flags in %s" % (flag_class.__name__ \
                                       if hasattr(flag_class, "__name__")
                                       else flag_class)
    
    values = [(value, flags[name.replace("_", "").lower()])
              for name, value in kwargs.items()]
    return (reduce(operator.or_, map(operator.itemgetter(1), values), 0),
            map(operator.itemgetter(0),
                sorted(values, key=operator.itemgetter(1))))

def configure_notify(connection, window, x, y, width, height, border_width,
                     override_redirect=False,
                     event_struct=Struct("bx2xIIIhhHHHB5x")):
    """Send a synthetic ConfigureNotify event to a window, as per ICCCM §4.1.5
    and §4.2.3."""
    assert event_struct.size == 32
    connection.core.SendEvent(False,
                              window,
                              EventMask.StructureNotify,
                              event_struct.pack(22, # code
                                                window, # event
                                                window, # window
                                                0, # above-sibling: None
                                                x + border_width,
                                                y + border_width,
                                                width,
                                                height,
                                                border_width,
                                                override_redirect))
