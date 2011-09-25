# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple
import operator
from struct import pack

from xcb.xproto import *

MAX_CARD32 = 2**32 - 1

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.__str__ = lambda self: "%ux%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)
Geometry.translate = lambda self, x, y: \
    self._replace(x=self.x + x, y=self.y + y)

def is_move_only(old_geometry, new_geometry):
    """Returns True if the new geometry represents a move without a resize
    of the old geometry."""
    return (old_geometry and new_geometry and
            (new_geometry.x != old_geometry.x or
             new_geometry.y != old_geometry.y) and
            new_geometry.width == old_geometry.width and
            new_geometry.height == old_geometry.height and
            new_geometry.border_width == old_geometry.border_width)

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

def power_of_2(x):
    """Check whether x is a power of 2."""
    return isinstance(x, int) and x > 0 and x & (x - 1) == 0

def popcount(x):
    """Count the number of 1 bits in the binary representation of x."""
    return bin(x).count("1")

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
                     override_redirect=False):
    """Send a synthetic ConfigureNotify event to a window, as per ICCCM §4.1.5
    and §4.2.3."""
    event = pack("bx2xIIIhhHHHB5x",
                 22, # code
                 window, # event
                 window, # window
                 0, # above-sibling: None
                 x + border_width, # x
                 y + border_width, # y
                 width, # width
                 height, # height
                 border_width, # border-width
                 override_redirect) # override-redirect
    assert len(event) == 32
    connection.core.SendEvent(False, window, EventMask.StructureNotify, event)
