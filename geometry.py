# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple

__all__ = ["Position", "Rectangle", "Geometry", "AspectRatio",
           "is_move_only"]

def add_tuple(self, other):
    """Add a named tuple to another tuple or a scalar."""
    if isinstance(other, Geometry):
        return other._replace(x=self.x + other.x, y=self.y + other.y)
    elif isinstance(other, tuple):
        return self._make(x + y for x, y in zip(self, other))
    elif isinstance(other, (int, float)):
        return self._make(x + other for x in self)
    else:
        return NotImplemented

def multiply_tuple(self, other):
    """Multiply the components of a named tuple by a scalar."""
    if isinstance(other, (int, float)):
        return self._make(x * other for x in self)
    else:
        return NotImplemented

def translate_geometry(self, other):
    """Translate a geometry by a relative position or a scalar."""
    if isinstance(other, tuple):
        return self._replace(x=self.x + other[0], y=self.y + other[1])
    elif isinstance(other, (int, float)):
        return self._replace(x=self.x + other, y=self.y + other)
    else:
        return NotImplemented

Position = namedtuple("Position", "x, y")
Position.__add__ = Position.__radd__ = add_tuple
Position.__mul__ = Position.__rmul__ = multiply_tuple
Position.__nonzero__ = lambda self: self.x != 0 or self.y != 0
Position.__str__ = lambda self: "%+d%+d" % self

Rectangle = namedtuple("Rectangle", "width, height")
Rectangle.__add__ = Rectangle.__radd__ = add_tuple
Rectangle.__mul__ = Rectangle.__rmul__ = multiply_tuple
Rectangle.__nonzero__ = lambda self: self.width != 0 or self.height != 0
Rectangle.__str__ = lambda self: "%ux%u" % self
Rectangle.__unicode__ = lambda self: u"%u×%u" % self

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.__add__ = Geometry.__radd__ = translate_geometry
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
