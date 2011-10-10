# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple
from operator import add, sub

__all__ = ["Position", "Rectangle", "Geometry", "AspectRatio",
           "is_move_only", "constrain_size"]

def make_tuple_adder(op):
    def add_sub_tuple(self, other):
        """Add or subtract two named tuples or a named tuple and a scalar."""
        if isinstance(other, tuple) and len(self) == len(other):
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

def make_geometry_adder(op):
    def add_sub_geometry(self, other):
        """Translate a geometry by a relative position or a scalar, or
        increment its width and height."""
        if isinstance(other, Rectangle):
            return self._replace(width=op(self.width, other.width),
                                 height=op(self.height, other.height))
        elif isinstance(other, tuple):
            return self._replace(x=op(self.x, other[0]), y=op(self.y, other[1]))
        elif isinstance(other, (int, float)):
            return self._replace(x=op(self.x, other), y=op(self.y, other))
        else:
            return NotImplemented
    return add_sub_geometry

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
Geometry.resize = lambda self, other: \
    self._replace(width=other.width, height=other.height)
Geometry.__add__ = Geometry.__radd__ = make_geometry_adder(add)
Geometry.__sub__ = make_geometry_adder(sub)
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

def constrain_size(size, hints):
    """Given a window's potential size and size hints, return the closest
    allowable size.

    This function does not yet handle aspect ratios."""
    base = hints.base_size
    min_size = hints.min_size
    inc = hints.resize_inc
    def constrain(size, i):
        return max((((size[i] - base[i]) // inc[i]) * inc[i]) + base[i],
                   min_size[i])
    return Rectangle(constrain(size, 0), constrain(size, 1))
