# -*- mode: Python; coding: utf-8 -*-

"""The clients of a window manager are top-level windows. This module provides
classes and routines for dealing with those as such."""

from array import array
from codecs import decode
from fractions import Fraction
from logging import debug, info, warning, error
from struct import Struct

from xcb.xproto import *

from geometry import *
from properties import *
from xutil import *

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
        assert isinstance(geometry, Geometry), "invalid geometry %r" % geometry
        self._geometry = geometry

    def move(self, position):
        self.manager.conn.core.ConfigureWindowChecked(self.window,
            ConfigWindow.X | ConfigWindow.Y,
            map(int16, position)).check()

    def resize(self, size):
        self.manager.conn.core.ConfigureWindowChecked(self.window,
            ConfigWindow.Width | ConfigWindow.Height,
            map(int16, size)).check()

    def update_geometry(self, geometry):
        self.manager.conn.core.ConfigureWindowChecked(self.window,
            (ConfigWindow.X | ConfigWindow.Y |
             ConfigWindow.Width | ConfigWindow.Height |
             ConfigWindow.BorderWidth),
            map(int16, geometry)).check()

    def restack(self, stack_mode):
        self.manager.conn.core.ConfigureWindowChecked(self.window,
            ConfigWindow.StackMode,
            [stack_mode]).check()

    def atom(self, x):
        return self.manager.atoms[x] if isinstance(x, basestring) else x

    def get_property(self, name, type):
        reply = self.manager.conn.core.GetProperty(False, self.window,
                                                   self.atom(name),
                                                   self.atom(type),
                                                   0, 0xffffffff).reply()
        if reply.type:
            return reply.value.buf()

    def set_property(self, name, type, value, mode=PropMode.Replace):
        if isinstance(value, unicode):
            format = 8
            data = value.encode("UTF-8")
            data_len = len(data)
        elif isinstance(value, PropertyValue):
            (format, data_len, data) = value.change_property_args()
        else:
            raise ValueError("unknown property value type")
        self.manager.conn.core.ChangeProperty(mode,
                                              self.window,
                                              self.atom(name),
                                              self.atom(type),
                                              format,
                                              data_len,
                                              data)

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
    def wm_normal_hints(self, default_size_hints=WMSizeHints()):
        """Retrieve the WM_NORMAL_HINTS property (ICCCM §4.1.2.3)."""
        size_hints = self.get_property("WM_NORMAL_HINTS", "WM_SIZE_HINTS")
        if size_hints:
            return WMSizeHints.unpack(size_hints)
        else:
            return default_size_hints

    @property
    def wm_hints(self, default_hints=WMHints()):
        """Retrieve the WM_HINTS property (ICCCM §4.1.2.4)."""
        wm_hints = self.get_property("WM_HINTS", "WM_HINTS")
        if wm_hints:
            return WMHints.unpack(wm_hints)
        else:
            return default_hints

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
    def wm_transient_for(self, formatter=Struct("=I")):
        """Retrieve the WM_TRANSIENT_FOR property (ICCCM §4.1.2.6)."""
        window = self.get_property("WM_TRANSIENT_FOR", "WINDOW")
        if window:
            return formatter.unpack_from(window)[0]

    @property
    def wm_state(self):
        """Retrieve the WM_STATE property (ICCCM §4.1.3.1)."""
        wm_state = self.get_property("WM_STATE", "WM_STATE")
        if wm_state:
            return WMState.unpack(wm_state)

    @wm_state.setter
    def wm_state(self, state):
        """Set the WM_STATE property (ICCCM §4.1.3.1)."""
        self.set_property("WM_STATE", "WM_STATE",
                          state if isinstance(state, WMState) \
                              else WMState(state))
