# -*- mode: Python; coding: utf-8 -*-

from cmath import phase
from collections import namedtuple
from numbers import Real
from operator import add, sub, lt, le, eq, ne, gt, ge

from xcb.xproto import BadWindow, Gravity

__all__ = ["Position", "Rectangle", "Geometry", "AspectRatio",
           "origin", "empty_rectangle", "empty_geometry", "null_aspect_ratio",
           "offset_gravity", "gravity_offset", "gravity_names"]

def make_tuple_adder(op):
    def add_sub_tuple(self, other):
        """Add or subtract two named tuples or a named tuple and a scalar."""
        if isinstance(other, tuple) and len(self) == len(other):
            return self._make(map(op, self, other))
        elif isinstance(other, Real):
            return self._make(op(field, other) for field in self)
        else:
            return NotImplemented
    return add_sub_tuple

def multiply_tuple(self, other):
    """Multiply the components of a named tuple by a scalar."""
    if isinstance(other, Real):
        return self._make(x * other for x in self)
    else:
        return NotImplemented

def floor_divide_tuple(self, other):
    """Divide the components of a named tuple by a scalar."""
    if isinstance(other, Real):
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
        elif isinstance(other, Real):
            return self._replace(x=op(self.x, other), y=op(self.y, other))
        else:
            return NotImplemented
    return add_sub_geometry

def make_aspect_comparison(comp):
    def compare_aspect(self, other):
        return comp(self.width * other[1], self.height * other[0])
    return compare_aspect

def point_in_rect(point, rect):
    return (rect.x + rect.width > point.x >= rect.x and
            rect.y + rect.height > point.y >= rect.y)

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
Rectangle.__nonzero__ = lambda self: self.width > 0 and self.height > 0
Rectangle.__str__ = lambda self: "%ux%u" % self
Rectangle.__unicode__ = lambda self: u"%u×%u" % self

Geometry = namedtuple("Geometry", "x, y, width, height, border_width")
Geometry.__add__ = Geometry.__radd__ = make_geometry_adder(add)
Geometry.__sub__ = make_geometry_adder(sub)
Geometry.__nonzero__ = lambda self: self.size().__nonzero__()
Geometry.__and__ = Geometry.__rand__ = lambda self, other: \
    ((other if point_in_rect(other, self) else None)
     if isinstance(other, Position) else
     (lambda x, y:
          Geometry(x, y,
                   min(self.x + self.width, other.x + other.width) - x,
                   min(self.y + self.height, other.y + other.height) - y,
                   0)) \
         (max(self.x, other.x), (max(self.y, other.y))) or None
     if isinstance(other, Geometry) else NotImplemented)
Geometry.__contains__ = lambda self, other: \
    (point_in_rect(other, self) if isinstance(other, Position) else
     (point_in_rect(other.position(), self) and
      point_in_rect(other.position() + other.size(), self))
     if isinstance(other, Geometry) else False)
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
Geometry.midpoint = lambda self: \
    self.position() + self.size() // 2
Geometry.right_edge = lambda self: \
    self.x + self.width + 2 * self.border_width
Geometry.bottom_edge = lambda self: \
    self.y + self.height + 2 * self.border_width
Geometry.edge = lambda self, direction: \
    (self.x if direction[0] < 0 and direction[1] == 0 else
     self.y if direction[0] == 0 and direction[1] < 0 else
     self.right_edge() if direction[0] > 0 and direction[1] == 0 else
     self.bottom_edge() if direction[0] == 0 and direction[1] > 0 else
     None)

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

origin = Position(0, 0)
empty_rectangle = Rectangle(0, 0)
empty_geometry = Geometry(0, 0, 0, 0, 0)
null_aspect_ratio = AspectRatio(0, 0)

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
offset_gravities = {Position(-1, -1): Gravity.NorthWest,
                    Position(+0, -1): Gravity.North,
                    Position(+1, -1): Gravity.NorthEast,
                    Position(-1, +0): Gravity.West,
                    Position(+0, +0): Gravity.Center,
                    Position(+1, +0): Gravity.East,
                    Position(-1, +1): Gravity.SouthWest,
                    Position(+0, +1): Gravity.South,
                    Position(+1, +1): Gravity.SouthEast}
gravity_offsets = dict((v, k) for k, v in offset_gravities.items())

def offset_gravity(offset):
    return (offset_gravities[offset]
            if offset is not None
            else offset_gravities.keys())

def gravity_offset(gravity):
    return (gravity_offsets[gravity]
            if gravity is not None
            else gravity_offsets.keys())

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
        offset = gravity_offset(gravity)
        dx = (dw + 2 * db) * (offset.x + 1) // 2
        dy = (dh + 2 * db) * (offset.y + 1) // 2
    return (geometry.reborder(border_width) -
            Position(dx, dy) +
            Rectangle(dw, dh))

gravity_names = dict((getattr(Gravity, name), name)
                     for name in dir(Gravity)
                     if not name.startswith("_"))
gravity_names.update(dict((offset, gravity_names[offset_gravity(offset)])
                          for offset in offset_gravities))
