# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple
from operator import add, sub

__all__ = ["Position", "Rectangle", "Geometry", "AspectRatio",
           "is_move_only"]

def make_tuple_adder(op):
    def add_sub_tuple(self, other):
        """Add or subtract two named tuples or a named tuple and a scalar."""
        if isinstance(other, tuple):
            return self._make(map(op, self, other))
        elif isinstance(other, (int, float)):
            return self._make(op(field, other) for field in self)
        else:
            return NotImplemented
    return add_sub_tuple

def multiply_tuple(self, other):
    """Multiply the components of a named tuple by a scalar."""
    if isinstance(other, (int, float)):
        return self._make(x * other for x in self)
    else:
        return NotImplemented

def make_translater(op):
    def translate_geometry(self, other):
        """Translate a geometry by a relative position or a scalar."""
        if isinstance(other, tuple):
            return self._replace(x=op(self.x, other[0]), y=op(self.y, other[1]))
        elif isinstance(other, (int, float)):
            return self._replace(x=op(self.x, other), y=op(self.y, other))
        else:
            return NotImplemented
    return translate_geometry

Position = namedtuple("Position", "x, y")
Position.__add__ = Position.__radd__ = make_tuple_adder(add)
Position.__sub__ = make_tuple_adder(sub)
Position.__mul__ = Position.__rmul__ = multiply_tuple
Position.__nonzero__ = lambda self: self.x != 0 or self.y != 0
Position.__str__ = lambda self: "%+d%+d" % self

Rectangle = namedtuple("Rectangle", "width, height")
Rectangle.__add__ = Rectangle.__radd__ = make_tuple_adder(add)
Rectangle.__sub__ = make_tuple_adder(sub)
Rectangle.__mul__ = Rectangle.__rmul__ = multiply_tuple
Rectangle.__nonzero__ = lambda self: self.width != 0 or self.height != 0
Rectangle.__str__ = lambda self: "%ux%u" % self
Rectangle.__unicode__ = lambda self: u"%u×%u" % self

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.__add__ = Geometry.__radd__ = make_translater(add)
Geometry.__sub__ = make_translater(sub)
Geometry.__nonzero__ = lambda self: \
    (self.x != 0 or self.y != 0 or
     self.width != 0 or self.height != 0 or
     self.border_width != 0)
Geometry.__str__ = lambda self: "%ux%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)
Geometry.__unicode__ = lambda self: u"%u×%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)

AspectRatio = namedtuple("AspectRatio", "numerator, denominator")
AspectRatio.__nonzero__ = lambda self: self.numerator != 0
AspectRatio.__str__ = lambda self: "%u/%u" % self
AspectRatio.__unicode__ = lambda self: u"%u⁄%u" % self

def is_move_only(old, new):
    """Returns True if the new geometry represents a move without a resize
    of the old geometry."""
    return ((old and new) and
            (new.x != old.x or new.y != old.y) and
            (new.width == old.width) and
            (new.height == old.height) and
            (new.border_width == old.border_width))
