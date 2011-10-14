# -*- mode: Python; coding: utf-8 -*-

"""Classes and utilites for managing various X properties."""

from array import array
from codecs import decode
from struct import Struct

from xcb.xproto import Gravity

from geometry import *

__all__ = ["PropertyValue", "PropertyValueList", "StringValue", "UTF8String",
           "WMClass", "WMTransientFor", "WMProtocols", "WMColormapWindows",
           "WMClientMachine", "WMState", "WMSizeHints", "WMHints"]

# Translate between X property formats and Python's struct & array type codes.
type_codes = {8: "B", 16: "H", 32: "I"}

class PropertyValueClass(type):
    """Metaclass for X property values."""

    def __new__(metaclass, name, bases, namespace):
        cls = super(PropertyValueClass, metaclass).__new__(metaclass, name,
                                                           bases, namespace)

        # Use the declared property format in conjunction with the names of
        # the fields to produce a Struct object which can pack and unpack
        # the property data.
        try:
            fields = namespace["__slots__"]
            format = namespace["__propformat__"]
        except KeyError:
            raise TypeError("property values must specify format and fields")
        assert format in type_codes, "invalid property format %r" % format
        cls.formatter = Struct(type_codes[format] * len(fields))
        return cls

class PropertyValueListClass(PropertyValueClass):
    """Metaclass for list-like X property values."""

    def __new__(metaclass, name, bases, namespace):
        cls = type.__new__(metaclass, name, bases, namespace)
        try:
            format = namespace["__propformat__"]
        except KeyError:
            raise TypeError("property value lists must specify format")
        assert (isinstance(format, (list, tuple)) and
                len(format) == 1 and format[0] in type_codes), \
                "invalid property format %r" % format
        return cls

class PropertyValue(object):
    """Base class for representations of X property values.

    X property values are treated by the server as lists of 8-bit, 16-bit,
    or 32-bit quantities. This class provides a representation of such
    lists as instances with named attributes (i.e., fields or slots),
    and offers convenience methods for translating to and from the
    binary representation.

    Subclassess should set their __propformat__ attribute to either 8, 16,
    or 32, and their __slots__ attribute to a sequence of attribute names
    whose values comprise the property data."""

    __metaclass__ = PropertyValueClass
    __slots__ = ()
    __propformat__ = 32

    def __init__(self, *args, **kwargs):
        for field, value in zip(self.__slots__, args):
            setattr(self, field, value)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __eq__(self, other):
        if isinstance(other, PropertyValue):
            return self.pack() == other.pack()
        elif isinstance(other, (str, buffer)):
            return self.pack() == other
        else:
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    @classmethod
    def unpack(cls, data):
        """Create and return a new instance by unpacking the property data."""
        return cls(*cls.formatter.unpack_from(data))

    def pack(self):
        """Return the property data as a byte string."""
        data = self.formatter.pack(*(getattr(self, slot, 0)
                                     for slot in self.__slots__))
        assert len(self.__slots__) == len(data) // (self.__propformat__ // 8), \
            "invalid property data"
        return data

    def change_property_args(self):
        """Return a (format, data-length, data) tuple."""
        return (self.__propformat__, len(self.__slots__), self.pack())

class PropertyValueList(PropertyValue):
    """Base class for representations of list-like X property values."""

    __metaclass__ = PropertyValueListClass
    __slots__ = ("elements")
    __propformat__ = [32]

    def __init__(self, elements):
        self.elements = elements

    @classmethod
    def unpack(cls, data):
        return cls(array(type_codes[cls.__propformat__[0]], str(data)))

    def pack(self):
        return array(type_codes[self.__propformat__[0]],
                     self.elements).tostring()

    def change_property_args(self):
        format = self.__propformat__[0]
        data = self.pack()
        return (format, len(data) // (format // 8), data)

    def __getitem__(self, index):
        return self.elements[index]

    def __setitem__(self, index, value):
        self.elements[index] = value

    def __len__(self):
        return len(self.elements)

    def __iter__(self):
        return iter(self.elements)

    def __eq__(self, other):
        return list(self.elements) == list(other)

class StringValue(PropertyValueList):
    __slots__ = ()
    __propformat__ = [8]
    encoding = "Latin-1"

    def __init__(self, elements):
        if isinstance(elements, basestring):
            self.elements = array("B", elements.encode(self.encoding))
        else:
            super(StringValue, self).__init__(elements)

    def __str__(self):
        return decode(buffer(self.elements), self.encoding)

    def __eq__(self, other):
        if isinstance(other, basestring):
            return str(self) == other
        else:
            return super(StringValue, self).__eq__(other)

class UTF8String(StringValue):
    __slots__ = ()
    __propformat__ = [8]
    encoding = "UTF-8"

class WMClass(StringValue):
    """A representation of the WM_STATE property (ICCCM §4.1.2.5)"""

    __slots__ = ()
    __propformat__ = [8]

    def instance_and_class(self):
        """Return a tuple of the form (client-instance, client-class)."""
        # The WM_CLASS property contains two consecutive null-terminated
        # strings naming the client instance and class, respectively.
        s = str(self)
        i = s.find("\0")
        j = s.find("\0", i + 1)
        return (s[0:i], s[i + 1:j])

class WMTransientFor(PropertyValue):
    """A representation of the WM_TRANSIENT_FOR property (ICCCM §4.1.2.6)"""

    __slots__ = ("window")
    __propformat__ = 32

class WMProtocols(PropertyValueList):
    """A representation of the WM_PROTOCOLS property (ICCCM §4.1.2.7)"""

    __slots__ = ()
    __propformat__ = [32]

class WMColormapWindows(PropertyValueList):
    """A representation of the WM_COLORMAP_WINDOWS property (ICCCM §4.1.2.8)"""

    __slots__ = ()
    __propformat__ = [32]

class WMClientMachine(StringValue):
    """A representation of the WM_CLIENT_MACHINE property (ICCCM §4.1.2.9)"""

    __slots__ = ()
    __propformat__ = [8]

class WMState(PropertyValue):
    """A representation of the WM_STATE type (ICCCM §4.1.3.1)"""

    __propformat__ = 32
    __slots__ = ("state", "icon")

    # State values
    WithdrawnState = 0
    NormalState = 1
    ZoomState = 2
    IconicState = 3
    InactiveState = 4

    def __init__(self, state, icon=0):
        self.state = state
        self.icon = icon

class PropertyField(object):
    """A descriptor class for property value fields whose presence or absence
    is specified by a flag. A single field may be comprised of more than one
    attribute; such fields are automatically converted to and from a tuple
    representation."""

    def __init__(self, flag, type, slots, defaults=None):
        assert flag != 0, "invalid flag for property field"
        self.flag = flag
        self.type = type
        self.slots = slots if isinstance(slots, (list, tuple)) else (slots,)
        self.defaults = defaults if defaults is not None \
            else (0,) * len(self.slots)

    def __get__(self, instance, owner):
        if not instance:
            return None
        if instance.flags & self.flag:
            return self.type(*(getattr(instance, s) for s in self.slots))
        else:
            if callable(self.defaults):
                return self.type(*self.defaults(instance))
            elif isinstance(self.defaults, (list, tuple)):
                return self.type(*self.defaults)                
            else:
                return self.type(self.defaults)

    def __set__(self, instance, value):
        if isinstance(value, (list, tuple)):
            if len(value) != len(self.slots):
                raise AttributeError("attribute value must have %d elements" % \
                                         len(slots))
            for slot, slot_value in zip(self.slots, value):
                setattr(instance, slot, slot_value)
        elif len(self.slots) == 1:
            setattr(instance, self.slots[0], value)
        else:
            raise AttributeError("don't know how to set attribute")
        instance.flags |= self.flag

    def __delete__(self, instance):
        for slot in self.slots:
            delattr(instance, slot)
        instance.flags &= ~self.flag

class WMSizeHints(PropertyValue):
    """A representation of the WM_SIZE_HINTS type (ICCCM §4.1.2.3)."""

    __propformat__ = 32
    __slots__ = ("flags",
                 "_pad1", "_pad2", "_pad3", "_pad4",
                 "_min_width", "_min_height",
                 "_max_width", "_max_height",
                 "_width_inc", "_height_inc",
                 "_min_aspect_numerator", "_min_aspect_denominator",
                 "_max_aspect_numerator", "_max_aspect_denominator",
                 "_base_width", "_base_height",
                 "_win_gravity")

    # Flags
    USPosition = 1
    USSize = 2
    PPosition = 4
    PSize = 8
    PMinSize = 16
    PMaxSize = 32
    PResizeInc = 64
    PAspect = 128
    PBaseSize = 256
    PWinGravity = 512

    def __init__(self, *args, **kwargs):
        self.flags = 0
        super(WMSizeHints, self).__init__(*args, **kwargs)

    min_size = PropertyField(PMinSize, Rectangle,
                             ("_min_width", "_min_height"),
                             lambda self: self.base_size \
                                 if self.flags & self.PBaseSize \
                                 else (1, 1))
    max_size = PropertyField(PMaxSize, Rectangle,
                             ("_max_width", "_max_height"),
                             (0x7fffffff, 0x7fffffff))
    resize_inc = PropertyField(PResizeInc, Rectangle,
                               ("_width_inc", "_height_inc"),
                               (1, 1))
    min_aspect = PropertyField(PAspect, AspectRatio,
                               ("_min_aspect_numerator",
                                "_min_aspect_denominator"),
                               (None, None))
    max_aspect = PropertyField(PAspect, AspectRatio,
                               ("_max_aspect_numerator",
                                "_max_aspect_denominator"),
                               (None, None))
    base_size = PropertyField(PBaseSize, Rectangle,
                              ("_base_width", "_base_height"),
                              lambda self: self.min_size \
                                  if self.flags & self.PMinSize \
                                  else (1, 1))
    win_gravity = PropertyField(PWinGravity, int,
                                "_win_gravity",
                                Gravity.NorthWest)

class WMHints(PropertyValue):
    """A representation of the WM_HINTS type (ICCCM §4.1.2.4)."""

    __propformat__ = 32
    __slots__ = ("flags",
                 "_input",
                 "_initial_state",
                 "_icon_pixmap",
                 "_icon_window",
                 "_icon_x", "_icon_y",
                 "_icon_mask",
                 "_window_group")

    # Flags
    InputHint = 1
    StateHint = 2
    IconPixmapHint = 4
    IconWindowHint = 8
    IconPositionHint = 16
    IconMaskHint = 32
    WindowGroupHint = 64
    MessageHint = 128 # this bit is obsolete
    UrgencyHint = 256

    def __init__(self, *args, **kwargs):
        self.flags = 0
        super(WMHints, self).__init__(*args, **kwargs)

    input = PropertyField(InputHint, bool, "_input")
    initial_state = PropertyField(StateHint, int, "_initial_state")
    icon_pixmap = PropertyField(IconPixmapHint, int, "_icon_pixmap")
    icon_window = PropertyField(IconWindowHint, int, "_icon_window")
    icon_position = PropertyField(IconPositionHint, Position,
                                  ("_icon_x", "_icon_y"))
    icon_mask = PropertyField(IconMaskHint, int, "_icon_mask")
    window_group = PropertyField(WindowGroupHint, int, "_window_group")
