# -*- mode: Python; coding: utf-8 -*-

"""The clients of a window manager are top-level windows. This module provides
classes and routines for dealing with those as such."""

from array import array
from codecs import decode
from fractions import Fraction
from logging import debug, info, warning, error
from struct import Struct

from xcb.xproto import *

from xutil import MAX_CARD32, Geometry

class WMState(object):
    """A representation of the WM_STATE type (ICCCM §5.1.1.3)"""
    WithdrawnState = 0
    NormalState = 1
    ZoomState = 2
    IconicState = 3
    InactiveState = 4

    @classmethod
    def unpack_property(cls, buf, prop_struct=Struct("=II")):
        return cls(*prop_struct.unpack_from(buf))

    def __init__(self, state, icon):
        (self.state, self.icon) = (state, icon)

class WMSizeHints(object):
    """A representation of the WM_SIZE_HINTS type (ICCCM §4.1.2.3)."""

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

    @classmethod
    def unpack_property(cls, buf, prop_struct=Struct("=I16xiiiiiiiiiiiii")):
        (flags,
         min_width, min_height, max_width, max_height,
         width_inc, height_inc,
         min_aspect_numerator, min_aspect_denominator,
         max_aspect_numerator, max_aspect_denominator,
         base_width, base_height,
         win_gravity) = prop_struct.unpack_from(buf)
        min_aspect = Fraction(min_aspect_numerator, min_aspect_denominator) \
            if flags & cls.PAspect and min_aspect_denominator != 0 \
            else None
        max_aspect = Fraction(max_aspect_numerator, max_aspect_denominator) \
            if flags & cls.PAspect and max_aspect_denominator != 0 \
            else None
        return cls(flags, min_width, min_height, max_width, max_height,
                   width_inc, height_inc, min_aspect, max_aspect,
                   base_width, base_height, win_gravity)

    def __init__(self, flags, min_width, min_height, max_width, max_height,
                 width_inc, height_inc, min_aspect, max_aspect,
                 base_width, base_height, win_gravity):
        self.flags = flags
        self.min_width = min_width if self.flags & self.PMinSize \
            else base_width if self.flags & self.PBaseSize \
            else 0
        self.min_height = min_height if self.flags & self.PMinSize \
            else base_height if self.flags & self.PBaseSize \
            else 0
        self.max_width = max_width if self.flags & self.PMaxSize else None
        self.max_height = max_height if self.flags & self.PMaxSize else None
        self.width_inc = width_inc if self.flags & self.PResizeInc else 1
        self.height_inc = height_inc if self.flags & self.PResizeInc else 1
        self.min_aspect = min_aspect if self.flags & self.PAspect else None
        self.max_aspect = max_aspect if self.flags & self.PAspect else None
        self.base_width = base_width if self.flags & self.PBaseSize \
            else self.min_width
        self.base_height = base_height if self.flags & self.PBaseSize \
            else self.min_height
        self.win_gravity = win_gravity if self.flags & self.PWinGravity \
            else Gravity.NorthWest

_default_size_hints = WMSizeHints(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

class WMHints(object):
    """A representation of the WM_HINTS type (ICCCM §4.1.2.4)."""

    # Flags
    InputHint = 1
    StateHint = 2
    IconPixmapHint = 4
    IconWindowHint = 8
    IconPositionHint = 16
    IconMaskHint = 32
    WindowGroupHint = 64
    MessageHint = 128
    UrgencyHint = 256

    @classmethod
    def unpack_property(cls, buf, prop_struct=Struct("=IIIIIIIII")):
        return cls(*prop_struct.unpack_from(buf))

    def __init__(self, flags, input, initial_state,
                 icon_pixmap, icon_window, icon_x, icon_y, icon_mask,
                 window_group):
        self.flags = flags
        self.input = bool(input) if self.flags & self.InputHint \
            else None
        self.initial_state = initial_state if self.flags & self.StateHint \
            else None
        self.icon_pixmap = icon_pixmap if self.flags & self.IconPixmapHint \
            else None
        self.icon_window = icon_window if self.flags & self.IconWindowHint \
            else None
        self.icon_x = icon_x if self.flags & self.IconPositionHint \
            else None
        self.icon_y = icon_y if self.flags & self.IconPositionHint \
            else None
        self.icon_mask = icon_mask if self.flags & self.IconMaskHint \
            else None
        self.window_group = window_group if self.flags & self.WindowGroupHint \
            else None

_default_wm_hints = WMHints(0, 0, 0, 0, 0, 0, 0, 0, 0)

class ClientWindow(object):
    """All top-level windows (other than those with override-redirect set) will
    be wrapped with an instance of this class."""

    def __init__(self, window, manager, decorator=None):
        self.window = window
        self.manager = manager
        self.decorator = decorator
        self._geometry = None

    @property
    def geometry(self):
        if self._geometry is None:
            debug("Fetching geometry for client 0x%x" % self.window)
            geometry = self.manager.conn.core.GetGeometry(self.window).reply()
            if geometry:
                self._geometry = Geometry(geometry.x, geometry.y,
                                          geometry.width, geometry.height,
                                          geometry.border_width)
        return self._geometry

    @geometry.setter
    def geometry(self, geometry):
        assert isinstance(geometry, Geometry), "Invalid geometry %r" % geometry
        self._geometry = geometry

    def atom(self, x):
        return self.manager.atoms[x] if isinstance(x, basestring) else x

    def get_property(self, name, type):
        reply = self.manager.conn.core.GetProperty(False, self.window,
                                                   self.atom(name),
                                                   self.atom(type),
                                                   0, MAX_CARD32).reply()
        if reply.type:
            return reply.value.buf()

    def set_property(self, name, type, format, value, mode=PropMode.Replace,
                     format_map={32: "I", 16: "H", 8: "B"}):
        if isinstance(value, unicode):
            assert format == 8
            data = value.encode("UTF-8")
        else:
            data = array(format_map[format], value)
        self.manager.conn.core.ChangeProperty(mode,
                                              self.window,
                                              self.atom(name),
                                              self.atom(type),
                                              format,
                                              len(data),
                                              data.tostring())

    def get_ewmh_name(self, name):
        """The EWMH specification defines two application window properties,
        _NET_WM_NAME and _NET_WM_ICON_NAME, that should be used in preference
        to the ICCCM equivalents, WM_NAME and WM_ICON_NAME. They differ only
        in type: the newer properties are always UTF-8 encoded, whereas the
        older properties use the polymorphic TEXT type."""
        assert name.startswith("_NET_")

        net_name = self.get_property(name, "UTF8_STRING")
        if net_name:
            return decode(net_name, "UTF-8", "replace")

        # Fall back to the ICCM property. Note that we currently only
        # support the Latin-1 STRING type, and not the COMPOUND_TEXT type.
        icccm_name = self.get_property(name[len("_NET_"):], "STRING")
        if icccm_name:
            return decode(icccm_name, "Latin-1", "replace")

    @property
    def wm_name(self):
        """Retrieve the window name property (EWMH and ICCCM §4.1.2.1)."""
        return self.get_ewmh_name("_NET_WM_NAME")

    @property
    def wm_icon_name(self):
        """Retrieve the window icon name property (EWMH and ICCCM §4.1.2.2)."""
        return self.get_ewmh_name("_NET_WM_ICON_NAME")

    @property
    def wm_normal_hints(self):
        """Retrieve the WM_NORMAL_HINTS property (ICCCM §4.1.2.3)."""
        wm_normal_hints = self.get_property("WM_NORMAL_HINTS", "WM_SIZE_HINTS")
        if wm_normal_hints:
            return WMSizeHints.unpack_property(wm_normal_hints)
        else:
            return _default_size_hints

    @property
    def wm_hints(self):
        """Retrieve the WM_HINTS property (ICCCM §4.1.2.4)."""
        wm_hints = self.get_property("WM_HINTS", "WM_HINTS")
        if wm_hints:
            return WMHints.unpack_property(wm_hints)
        else:
            return _default_wm_hints

    @property
    def wm_class(self):
        """Retrieve the WM_CLASS property (ICCCM §4.1.2.5)."""
        wm_class = self.get_property("WM_CLASS", "STRING")
        if wm_class:
            # The WM_CLASS property contains two consecutive null-terminated
            # strings naming the client instance and class, respectively.
            class_and_instance = decode(wm_class, "Latin-1", "replace")
            i = class_and_instance.find("\0")
            j = class_and_instance.find("\0", i+1)
            return (class_and_instance[0:i], class_and_instance[i+1:j])
        else:
            return (None, None)

    @property
    def wm_transient_for(self, prop_struct=Struct("=I")):
        """Retrieve the WM_TRANSIENT_FOR property (ICCCM §4.1.2.6)."""
        window = self.get_property("WM_TRANSIENT_FOR", "WINDOW")
        if window:
            return prop_struct.unpack_from(window)[0]

    @property
    def wm_state(self):
        """Retrieve the WM_STATE property (ICCCM §4.1.3.1)."""
        wm_state = self.get_property("WM_STATE", "WM_STATE")
        if wm_state:
            return WMState.unpack_property(wm_state)

    @wm_state.setter
    def wm_state(self, wm_state):
        """Set the WM_STATE property (ICCCM §4.1.3.1)."""
        assert isinstance(wm_state, (WMState, int))
        self.set_property("WM_STATE", "WM_STATE", 32,
                          [wm_state.state, wm_state.icon] \
                              if isinstance(wm_state, WMState) \
                              else [wm_state, 0])
