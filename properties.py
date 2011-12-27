# -*- mode: Python; coding: utf-8 -*-

"""Classes and utilites for managing various X properties."""

from array import array
from collections import defaultdict
import logging
from struct import Struct

from xcb.xproto import *

from geometry import *

__all__ = ["PropertyError", "PropertyDescriptor", "PropertyManager",
           "PropertyValue", "PropertyValueList",
           "AtomList", "String", "UTF8String",
           "WMClass", "WMTransientFor", "WMProtocols", "WMColormapWindows",
           "WMClientMachine", "WMState", "WMSizeHints", "WMHints"]

class PropertyError(Exception):
    pass

class PropertyDescriptor(object):
    """A descriptor class for cached properties. To be used as attributes of
    a PropertyManager."""

    def __init__(self, name, type, default=None):
        assert isinstance(name, basestring), "invalid property name"
        assert issubclass(type, PropertyValue), "invalid property value type"
        self.name = name
        self.type = type
        self.default = default

    def __get__(self, instance, owner):
        # Check the value cache.
        try:
            return instance.values[self.name]
        except KeyError:
            pass

        # Request the property, construct a new value from the reply data,
        # and cache it.
        try:
            reply = instance.request_property(self.name).reply()
        except BadWindow:
            instance.log.warning("Error fetching property %s.", self.name)
            return None
        value = (owner.properties[self.name].unpack(reply.value.buf())
                 if reply.type
                 else self.default)
        instance.values[self.name] = value
        return value

    def __set__(self, instance, value):
        if instance.values.get(self.name, None) != value:
            instance.set_property(self.name, self.type.property_type, value)

    def __delete__(self, instance):
        instance.delete_property(self.name)

class PropertyManagerClass(type):
    """A metaclass for PropertyManager that supports auto-registration of
    property descriptors."""

    def __new__(metaclass, name, bases, namespace):
        cls = super(PropertyManagerClass, metaclass).__new__(metaclass, name,
                                                             bases, namespace)
        cls.properties = {}
        for superclass in reversed(cls.__mro__):
            if hasattr(superclass, "properties"):
                cls.properties.update(superclass.properties)
        for attr in namespace.values():
            if isinstance(attr, PropertyDescriptor):
                cls.properties[attr.name] = attr.type
        return cls

class PropertyManager(object):
    """Manages a set of properties on a window."""

    __metaclass__ = PropertyManagerClass

    def __init__(self, conn, window, atoms):
        self.conn = conn
        self.window = window
        self.atoms = atoms
        self.values = {} # cached property values
        self.cookies = {} # pending property request cookies
        self.change_handlers = defaultdict(set)
        self.log = logging.getLogger("properties.0x%x" % self.window)

    def request_property(self, name, type=None):
        """Request the value of a property on the window, and return a cookie
        for the request. Does not wait for a reply."""
        if type is None:
            type = (self.properties[name].property_type
                    if name in self.properties
                    else GetPropertyType.Any)
        try:
            return self.cookies[name]
        except KeyError:
            pass
        self.log.debug("Requesting property %s.", name)
        def atom(x):
            return self.atoms[x] if isinstance(x, basestring) else x
        cookie = self.conn.core.GetProperty(False, self.window,
                                            atom(name), atom(type),
                                            0, 0xffffffff)
        self.cookies[name] = cookie
        return cookie

    def set_property(self, name, type, value, mode=PropMode.Replace):
        """Change the value of a property on the window."""
        if isinstance(value, unicode):
            format = 8
            data = value.encode("UTF-8")
            data_len = len(data)
        elif isinstance(value, str):
            format = 8
            data = value
            data_len = len(data)
        elif isinstance(value, PropertyValue):
            format, data_len, data = value.change_property_args()
        else:
            raise PropertyError("unknown property value type")
        self.conn.core.ChangeProperty(mode, self.window,
                                      self.atoms[name], self.atoms[type],
                                      format, data_len, data)

        # We'll accept the given value as provisionally correct until a
        # PropertyNotify comes in to inform us that the server has a new,
        # canonical value.
        self.values[name] = value

        # Any pending request for the property value should be canceled.
        self.cookies.pop(name, None)

    def request_properties(self):
        """Request the values of all the registered properties for which we
        don't have a cached value or a pending request. Does not wait for
        any of the replies."""
        for name in self.properties:
            if name not in self.values:
                self.request_property(name)

    def delete_property(self, name):
        """Remove the given property from the window."""
        self.log.debug("Deleting property %s.", name)
        self.conn.core.DeleteProperty(self.window, self.atoms[name])
        self.invalidate_cached_property(name)

    def property_changed(self, name, deleted, time):
        """Handle a change or deletion of a property."""
        self.log.debug("Property %s %s.",
                       name, ("deleted" if deleted else "changed"))
        if deleted:
            self.invalidate_cached_property(name)
        else:
            # Dump our cached value and, if it's a property that we care
            # about, request (but do not wait for) the new value.
            self.invalidate_cached_property(name)
            if name in self.properties:
                self.request_property(name)

        # Invoke any handlers registered for this property change.
        for handler in self.change_handlers.get(name, []):
            handler(self.window, name, deleted, time)

    def invalidate_cached_property(self, name):
        """Invalidate any cached request or value for the given property."""
        self.values.pop(name, None)
        self.cookies.pop(name, None)

    def register_change_handler(self, name, handler):
        self.change_handlers[name].add(handler)

    def unregister_change_handler(self, name, handler):
        self.change_handlers[name].discard(handler)

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
        for c in cls.__mro__:
            if hasattr(c, "__slots__") and hasattr(c, "property_format"):
                fields = c.__slots__
                format = c.property_format
                break
        else:
            raise TypeError("property values must specify format and fields")
        assert format in type_codes, "invalid property format %r" % format
        cls.formatter = Struct(type_codes[format] * len(fields))
        return cls

class PropertyValueListClass(PropertyValueClass):
    """Metaclass for list-like X property values."""

    def __new__(metaclass, name, bases, namespace):
        cls = type.__new__(metaclass, name, bases, namespace)
        for c in cls.__mro__:
            if hasattr(c, "property_format"):
                format = c.property_format
                break
        else:
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

    Subclassess should set their property_format attribute to either 8, 16,
    or 32, and their __slots__ attribute to a sequence of attribute names
    whose values comprise the property data."""

    __metaclass__ = PropertyValueClass
    __slots__ = ()
    property_format = 32

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
        if len(self.__slots__) != len(data) // (self.property_format // 8):
            raise PropertyError("invalid property data")
        return data

    def change_property_args(self):
        """Return a (format, data-length, data) tuple."""
        return (self.property_format, len(self.__slots__), self.pack())

class PropertyValueList(PropertyValue):
    """Base class for representations of list-like X property values."""

    __metaclass__ = PropertyValueListClass
    __slots__ = ("elements")
    property_format = [32]

    def __init__(self, elements):
        self.elements = elements

    @classmethod
    def unpack(cls, data):
        return cls(array(type_codes[cls.property_format[0]], str(data)))

    def pack(self):
        return array(type_codes[self.property_format[0]],
                     self.elements).tostring()

    def change_property_args(self):
        format = self.property_format[0]
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

class AtomList(PropertyValueList):
    __slots__ = ()
    property_format = [32]
    property_type = "ATOM"

class String(PropertyValueList):
    """A representation of property values of type STRING.

    Note that we currently only support Latin-1 strings, and not the (obsolete)
    COMPOUND_TEXT type. If you need Unicode support, use UTF8String instead."""

    __slots__ = ()
    property_format = [8]
    property_type = "STRING"
    encoding = "Latin-1"

    def __init__(self, elements):
        if isinstance(elements, basestring):
            self.elements = array("B", elements.encode(self.encoding))
        else:
            super(String, self).__init__(elements)

    def __str__(self):
        return self.elements.tostring()

    def __unicode__(self):
        return self.elements.tostring().decode(self.encoding)

    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        elif isinstance(other, unicode):
            return unicode(self) == other
        else:
            return super(String, self).__eq__(other)

class UTF8String(String):
    __slots__ = ()
    property_format = [8]
    property_type = "UTF8_STRING"
    encoding = "UTF-8"

class WMClass(String):
    """A representation of the WM_STATE property (ICCCM §4.1.2.5)"""

    __slots__ = ()
    property_format = [8]
    property_type = "STRING"

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
    property_format = 32
    property_type = "WINDOW"

class WMProtocols(AtomList):
    """A representation of the WM_PROTOCOLS property (ICCCM §4.1.2.7)"""
    __slots__ = ()

class WMColormapWindows(PropertyValueList):
    """A representation of the WM_COLORMAP_WINDOWS property (ICCCM §4.1.2.8)"""

    __slots__ = ()
    property_format = [32]
    property_type = "WINDOW"

class WMClientMachine(String):
    """A representation of the WM_CLIENT_MACHINE property (ICCCM §4.1.2.9)"""

    __slots__ = ()
    property_format = [8]
    property_type = "STRING"

class WMState(PropertyValue):
    """A representation of the WM_STATE type (ICCCM §4.1.3.1)"""

    __slots__ = ("state", "icon")
    property_format = 32
    property_type = "WM_STATE"

    # State values
    WithdrawnState = 0
    NormalState = 1
    ZoomState = 2
    IconicState = 3
    InactiveState = 4

    def __init__(self, state=WithdrawnState, icon=0):
        self.state = state
        self.icon = icon

    def __eq__(self, other):
        if isinstance(other, WMState):
            return self.state == other.state and self.icon == other.icon
        elif isinstance(other, int):
            return self.state == other
        else:
            return super(WMState, self).__eq__(other)

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
        self.defaults = (defaults if defaults is not None
                         else (0,) * len(self.slots))

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
                raise AttributeError("attribute value must have %d elements" %
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

    __slots__ = ("flags",
                 "_pad1", "_pad2", "_pad3", "_pad4",
                 "_min_width", "_min_height",
                 "_max_width", "_max_height",
                 "_width_inc", "_height_inc",
                 "_min_aspect_width", "_min_aspect_height",
                 "_max_aspect_width", "_max_aspect_height",
                 "_base_width", "_base_height",
                 "_win_gravity")
    property_format = 32
    property_type = "WM_SIZE_HINTS"

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
                             lambda self: (self.base_size
                                           if self.flags & self.PBaseSize
                                           else (1, 1)))
    max_size = PropertyField(PMaxSize, Rectangle,
                             ("_max_width", "_max_height"),
                             (0x7fffffff, 0x7fffffff))
    resize_inc = PropertyField(PResizeInc, Rectangle,
                               ("_width_inc", "_height_inc"),
                               (1, 1))
    min_aspect = PropertyField(PAspect, AspectRatio,
                               ("_min_aspect_width", "_min_aspect_height"),
                               (None, None))
    max_aspect = PropertyField(PAspect, AspectRatio,
                               ("_max_aspect_width", "_max_aspect_height"),
                               (None, None))
    base_size = PropertyField(PBaseSize, Rectangle,
                              ("_base_width", "_base_height"),
                              lambda self: (self.min_size
                                            if self.flags & self.PMinSize
                                            else (1, 1)))
    win_gravity = PropertyField(PWinGravity, int,
                                "_win_gravity",
                                Gravity.NorthWest)

    def constrain_window_size(self, size):
        """Given a potential window size, return the closest allowable size."""
        def constrain_aspect(size):
            if not (self.flags & WMSizeHints.PAspect):
                return size
            if self.flags & WMSizeHints.PBaseSize:
                size -= self.base_size
            max_aspect = self.max_aspect
            min_aspect = self.min_aspect
            if max_aspect and max_aspect < size:
                size = max_aspect.crop(size)
            if min_aspect and min_aspect > size:
                size = min_aspect.crop(size)
            return size
        def constrain_inc(size):
            if not (self.flags & WMSizeHints.PResizeInc):
                return size
            base = self.base_size
            inc = self.resize_inc
            i, j = self.size_increments(size)
            return Rectangle(base.width + (i * inc.width),
                             base.height + (j * inc.height))
        def constrain_min_max(size):
            def min_max(i):
                return min(max(size[i], self.min_size[i]), self.max_size[i])
            return Rectangle(min_max(0), min_max(1))
        return constrain_min_max(constrain_inc(constrain_aspect(size)))

    def size_increments(self, size):
        """Given a rectangle of size width × height, return a pair of
        non-negative integers i and j such that:
            width = base_width + (i × width_inc) and
            height = base_height + (j × height_inc).
        See ICCCM §4.1.2.3 for details."""
        base = self.base_size
        inc = self.resize_inc
        return Rectangle((size.width - base.width) // inc.width,
                         (size.height - base.height) // inc.height)

class WMHints(PropertyValue):
    """A representation of the WM_HINTS type (ICCCM §4.1.2.4)."""

    __slots__ = ("flags",
                 "_input",
                 "_initial_state",
                 "_icon_pixmap",
                 "_icon_window",
                 "_icon_x", "_icon_y",
                 "_icon_mask",
                 "_window_group")
    property_format = 32
    property_type = "WM_HINTS"

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
