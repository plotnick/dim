# -*- mode: Python; coding: utf-8 -*-

from cmath import phase
from collections import namedtuple
from operator import add, sub, lt, le, eq, ne, gt, ge

from xcb.xproto import Gravity

__all__ = ["Position", "Rectangle", "Geometry", "AspectRatio", "is_move_only",
           "offset_gravity", "gravity_offset"]

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

def floor_divide_tuple(self, other):
    """Divide the components of a named tuple by a scalar."""
    if isinstance(other, (int, float)):
        return self._make(x // other for x in self)
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

def make_aspect_comparison(comp):
    def compare_aspect(self, other):
        return comp(self.width * other[1], self.height * other[0])
    return compare_aspect

Position = namedtuple("Position", "x, y")
Position.__add__ = Position.__radd__ = make_tuple_adder(add)
Position.__sub__ = make_tuple_adder(sub)
Position.__mul__ = Position.__rmul__ = multiply_tuple
Position.__floordiv__ = floor_divide_tuple
Position.__neg__ = lambda self: Position(-self.x, -self.y)
Position.__nonzero__ = lambda self: self.x != 0 or self.y != 0
Position.__str__ = lambda self: "%+d%+d" % self
Position.__abs__ = lambda self: abs(complex(*self))
Position.phase = lambda self: phase(complex(*self))

Rectangle = namedtuple("Rectangle", "width, height")
Rectangle.__add__ = Rectangle.__radd__ = make_tuple_adder(add)
Rectangle.__sub__ = make_tuple_adder(sub)
Rectangle.__mul__ = Rectangle.__rmul__ = multiply_tuple
Rectangle.__floordiv__ = floor_divide_tuple
Rectangle.__nonzero__ = lambda self: self.width != 0 or self.height != 0
Rectangle.__str__ = lambda self: "%ux%u" % self
Rectangle.__unicode__ = lambda self: u"%u×%u" % self

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.__add__ = Geometry.__radd__ = make_geometry_adder(add)
Geometry.__sub__ = make_geometry_adder(sub)
Geometry.__nonzero__ = lambda self: \
    (self.x != 0 or self.y != 0 or
     self.width != 0 or self.height != 0 or
     self.border_width != 0)
Geometry.__str__ = lambda self: \
    str(self.size()) + str(self.position())
Geometry.__unicode__ = lambda self: \
    unicode(self.size()) + unicode(self.position())
Geometry.position = lambda self: Position(self.x, self.y)
Geometry.move = lambda self, position: \
    self._replace(x=position.x, y=position.y)
Geometry.size = lambda self: Rectangle(self.width, self.height)
Geometry.resize = lambda self, size, border_width=None, gravity=Gravity.NorthWest: \
    resize_with_gravity(self, size, border_width, gravity)
Geometry.reborder = lambda self, border_width: \
    self._replace(border_width=border_width)

AspectRatio = namedtuple("AspectRatio", "width, height")
AspectRatio.__nonzero__ = lambda self: \
    self.width is not None and self.height is not None and \
    self.width != 0 and self.height != 0
AspectRatio.__lt__ = make_aspect_comparison(lt)
AspectRatio.__le__ = make_aspect_comparison(le)
AspectRatio.__eq__ = make_aspect_comparison(eq)
AspectRatio.__ne__ = make_aspect_comparison(ne)
AspectRatio.__gt__ = make_aspect_comparison(gt)
AspectRatio.__ge__ = make_aspect_comparison(ge)
AspectRatio.__str__ = lambda self: "%u:%u" % self
AspectRatio.__unicode__ = lambda self: u"%u∶%u" % self
AspectRatio.crop = lambda self, rect: \
    Rectangle(rect.width, rect.width * self.height // self.width) \
        if self.width > self.height \
        else Rectangle(rect.height * self.width // self.height, rect.height)

def is_move_only(old, new):
    """Return true if the new geometry represents a (possibly trivial) move
    without a resize or border-width change of the old geometry."""
    return (old is not None and
            new is not None and
            new.width == old.width and
            new.height == old.height and
            new.border_width == old.border_width)

# When dealing with window gravity, it's sometimes more convenient to use
# a slightly richer representation than the simple enumeration specified
# by the X11 protocol. Gravity values are just labels for the 8-cell Moore
# neighborhood surrounding a center (including the center). We can label
# them instead by their normalized Cartesian coordinates:
#     ┌──────┬──────┬──────┐
#     │ -1-1 │ +0-1 │ +1-1 │
#     ├──────┼──────┼──────┤
#     │ -1+0 │ +0+0 │ +1+0 │
#     ├──────┼──────┼──────┤
#     │ -1+1 │ +0+1 │ +1+1 │
#     └──────┴──────┴──────┘
offset_gravity = {Position(-1, -1): Gravity.NorthWest,
                  Position(+0, -1): Gravity.North,
                  Position(+1, -1): Gravity.NorthEast,
                  Position(-1, +0): Gravity.West,
                  Position(+0, +0): Gravity.Center,
                  Position(+1, +0): Gravity.East,
                  Position(-1, +1): Gravity.SouthWest,
                  Position(+0, +1): Gravity.South,
                  Position(+1, +1): Gravity.SouthEast}
gravity_offset = dict((v, k) for k, v in offset_gravity.items())

def resize_with_gravity(geometry, size, border_width, gravity):
    """Given a geometry, a requested size and border width, and a window
    gravity value, determine a new geometry that keeps the corresponding
    reference point fixed. See ICCCM §4.1.2.3 for details."""
    assert isinstance(size, Rectangle)
    if border_width is None:
        border_width = geometry.border_width
    db = border_width - geometry.border_width
    dw, dh = size - geometry.size()
    if gravity == Gravity.Static:
        dx = dy = db
    else:
        offset = gravity_offset[gravity]
        dx = (dw + 2 * db) * (offset.x + 1) // 2
        dy = (dh + 2 * db) * (offset.y + 1) // 2
    return (geometry.reborder(border_width) -
            Position(dx, dy) +
            Rectangle(dw, dh))
