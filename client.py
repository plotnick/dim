# -*- mode: Python; coding: utf-8 -*-

"""The clients of a window manager are top-level windows. This module provides
classes and routines for dealing with those as such."""

from logging import debug, info, warning, error

from xcb.xproto import *

from geometry import *
from properties import *
from xutil import *

__all__ = ["ClientWindow"]

class ClientProperty(object):
    """A descriptor class for client properties."""

    def __init__(self, name, type, default=None):
        assert isinstance(name, basestring), "invalid property name"
        assert issubclass(type, PropertyValue), "invalid property value type"
        self.name = name
        self.type = type
        self.default = default

    def __get__(self, instance, owner):
        # Check the value cache.
        try:
            return instance.property_values[self.name]
        except KeyError:
            pass

        # Check the cookie cache for a pending request, or make a new request
        # if there is none.
        try:
            cookie = instance.property_cookies.pop(self.name)
        except KeyError:
            cookie = instance.get_property(self.name)

        # Construct a new value from the reply data and cache it.
        reply = cookie.reply()
        value = owner.properties[self.name].unpack(reply.value.buf()) \
            if reply and reply.type else self.default
        instance.property_values[self.name] = value

        return value

    def __set__(self, instance, value):
        if instance.property_values.get(self.name, None) != value:
            instance.set_property(self.name, self.type.property_type, value)

    def __delete__(self, instance):
        instance.invalidate_cached_property(self.name)

class ClientWindowClass(type):
    """A metaclass for the ClientWindow class that supports auto-registration
    of client properties."""

    def __new__(metaclass, name, bases, namespace):
        cls = super(ClientWindowClass, metaclass).__new__(metaclass, name,
                                                          bases, namespace)

        # Initialize the client properties map.
        def is_client_property(x):
            return isinstance(x, ClientProperty)
        cls.properties = {}
        for p in filter(is_client_property, namespace.values()):
            cls.properties[p.name] = p.type

        return cls

class ClientWindow(object):
    """All top-level windows (other than those with override-redirect set) will
    be wrapped with an instance of this class."""

    __metaclass__ = ClientWindowClass

    client_event_mask = (EventMask.EnterWindow |
                         EventMask.LeaveWindow |
                         EventMask.FocusChange |
                         EventMask.PropertyChange)

    def __init__(self, conn, window, manager):
        self.conn = conn
        self.window = window
        self.manager = manager
        self.screen = manager.screen
        self.atoms = manager.atoms
        self.colors = manager.colors
        self.cursors = manager.cursors
        self.fonts = manager.fonts
        self.keymap = manager.keymap
        self.decorator = manager.decorator(self)
        self.frame = None
        self.reparenting = False
        self._geometry = None
        self.property_values = {}
        self.property_cookies = {}
        self.conn.core.ChangeWindowAttributes(self.window, CW.EventMask,
                                              [self.client_event_mask])

    @property
    def geometry(self):
        if self._geometry is None:
            cookie = self.conn.core.GetGeometry(self.frame or self.window)
            reply = cookie.reply()
            if reply:
                self._geometry = Geometry(reply.x, reply.y,
                                          reply.width, reply.height,
                                          reply.border_width)
        return self._geometry

    @geometry.setter
    def geometry(self, geometry):
        assert isinstance(geometry, Geometry), "invalid geometry %r" % geometry
        self._geometry = geometry

    def move(self, position, mask=ConfigWindow.X | ConfigWindow.Y):
        self.conn.core.ConfigureWindow(self.frame or self.window, mask,
                                       map(int16, position))

    def resize(self, size, mask=ConfigWindow.Width | ConfigWindow.Height):
        if self.frame:
            self.conn.core.ConfigureWindow(self.frame, mask, map(int16, size))
        self.conn.core.ConfigureWindow(self.window, mask, map(int16, size))

    def update_geometry(self, geometry,
                        frame_mask=(ConfigWindow.X |
                                    ConfigWindow.Y |
                                    ConfigWindow.Width |
                                    ConfigWindow.Height |
                                    ConfigWindow.BorderWidth),
                        window_mask=ConfigWindow.Width | ConfigWindow.Height):
        if self.frame:
            self.conn.core.ConfigureWindow(self.frame, frame_mask,
                                           map(int16, geometry))
            self.conn.core.ConfigureWindow(self.window, window_mask,
                                           [int16(geometry.width),
                                            int16(geometry.height)])
        else:
            self.conn.core.ConfigureWindow(self.window, frame_mask,
                                           map(int16, geometry))

    def restack(self, stack_mode):
        self.conn.core.ConfigureWindow(self.frame or self.window,
                                       ConfigWindow.StackMode,
                                       [stack_mode])

    def focus(self, time=Time.CurrentTime):
        """Offer the input focus to the client. See ICCCM §4.1.7."""
        if self.wm_state.state != WMState.NormalState:
            debug("Ignoring attempt to focus client not in Normal state.")
            return False

        focused = False
        if self.wm_hints.flags & WMHints.InputHint == 0 or self.wm_hints.input:
            debug("Setting input focus to window 0x%x (%d)." %
                  (self.window, time))
            self.conn.core.SetInputFocus(InputFocus.PointerRoot,
                                         self.window, time)
            focused = True
        if self.atoms["WM_TAKE_FOCUS"] in self.wm_protocols:
            send_client_message(self.conn, self.window, 0, 32,
                                self.atoms["WM_PROTOCOLS"],
                                [self.atoms["WM_TAKE_FOCUS"], time, 0, 0, 0])
            focused = True
        return focused

    def unfocus(self):
        self.decorator.unfocus()

    def get_property(self, name, type=None):
        if type is None:
            type = self.properties[name].property_type
        debug("Requesting property %s for window 0x%x." % (name, self.window))
        return self.conn.core.GetProperty(False, self.window,
                                          self.atoms[name], self.atoms[type],
                                          0, 0xffffffff)

    def set_property(self, name, type, value, mode=PropMode.Replace):
        if isinstance(value, unicode):
            format = 8
            data = value.encode("UTF-8")
            data_len = len(data)
        if isinstance(value, str):
            format = 8
            data = value.encode("Latin-1")
            data_len = len(data)
        elif isinstance(value, PropertyValue):
            (format, data_len, data) = value.change_property_args()
        else:
            raise __builtins__.ValueError("unknown property value type")

        # Dump the locally cached value for this property. Only values
        # from the server are canonical, so we'll wait for a new request
        # to update the value.
        self.invalidate_cached_property(name)

        self.conn.core.ChangeProperty(mode, self.window,
                                      self.atoms[name], self.atoms[type],
                                      format, data_len, data)

    def request_properties(self):
        """Request the client properties for which we don't have a cached
        value or a pending request. Does not wait for any of the replies."""
        for name in self.properties:
            if (name not in self.property_values and
                name not in self.property_cookies):
                self.property_cookies[name] = self.get_property(name)

    def invalidate_cached_property(self, name):
        """Invalidate any cached request or value for the given property."""
        if name in self.property_values:
            del self.property_values[name]
        if name in self.property_cookies:
            del self.property_cookies[name]

    def property_changed(self, atom):
        name = self.atoms.name(atom)
        debug("Property %s changed on window 0x%x." % (name, self.window))
        self.invalidate_cached_property(name)

        if name == "WM_NAME" or name == "_NET_WM_NAME":
            self.decorator.name_changed()

    # ICCCM properties
    wm_name = ClientProperty("WM_NAME", String)
    wm_icon_name = ClientProperty("WM_ICON_NAME", String)
    wm_normal_hints = ClientProperty("WM_NORMAL_HINTS",
                                     WMSizeHints,
                                     WMSizeHints())
    wm_hints = ClientProperty("WM_HINTS", WMHints, WMHints())
    wm_class = ClientProperty("WM_CLASS", WMClass, (None, None))
    wm_transient_for = ClientProperty("WM_TRANSIENT_FOR", WMTransientFor)
    wm_protocols = ClientProperty("WM_PROTOCOLS", WMProtocols)
    wm_state = ClientProperty("WM_STATE", WMState)

    # EWMH properties
    net_wm_name = ClientProperty("_NET_WM_NAME", UTF8String)
    net_wm_icon_name = ClientProperty("_NET_WM_ICON_NAME", UTF8String)
