# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple

__all__ = ["Position", "Geometry", "Rectangle", "AspectRatio",
           "is_move_only"]

Position = namedtuple("Position", "x, y")
Position.__str__ = lambda self: "%+d%+d" % self

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.__str__ = lambda self: "%ux%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)
Geometry.__unicode__ = lambda self: u"%u×%u%+d%+d" % \
    (self.width, self.height, self.x, self.y)
Geometry.translate = lambda self, x, y: \
    self._replace(x=self.x + x, y=self.y + y)

Rectangle = namedtuple("Rectangle", "width, height")
Rectangle.__str__ = lambda self: "%ux%u" % self
Rectangle.__str__ = lambda self: u"%u×%u" % self

AspectRatio = namedtuple("AspectRatio", "numerator, denominator")
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
