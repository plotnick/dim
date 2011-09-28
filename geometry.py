# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple

__all__ = ["Position", "Geometry", "Rectangle", "AspectRatio",
           "is_move_only"]

Position = namedtuple("Position", "x, y")
Position.__nonzero__ = lambda self: self.x != 0 or self.y != 0
Position.__str__ = lambda self: "%+d%+d" % self

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.translate = lambda self, x, y: \
    self._replace(x=self.x + x, y=self.y + y)
Geometry.__nonzero__ = lambda self: \
    (self.x != 0 or self.y != 0 or
     self.width != 0 or self.height != 0 or
     self.border_width != 0)
Geometry.__str__ = lambda self: "%ux%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)
Geometry.__unicode__ = lambda self: u"%u×%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)

Rectangle = namedtuple("Rectangle", "width, height")
Rectangle.__nonzero__ = lambda self: self.width != 0 or self.height != 0
Rectangle.__str__ = lambda self: "%ux%u" % self
Rectangle.__unicode__ = lambda self: u"%u×%u" % self

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
