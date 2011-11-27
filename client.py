# -*- mode: Python; coding: utf-8 -*-

"""The clients of a window manager are top-level windows. This module provides
classes and routines for dealing with those as such."""

from collections import defaultdict
import logging

from xcb.xproto import *

from geometry import *
from properties import *
from xutil import *

__all__ = ["ClientWindow", "FramedClientWindow"]

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
            cookie = instance.request_property(self.name)

        # Construct a new value from the reply data and cache it.
        try:
            reply = cookie.reply()
        except BadWindow:
            instance.log.warning("Error fetching property %s.", self.name)
            return self.default
        value = owner.properties[self.name].unpack(reply.value.buf()) \
            if reply.type else self.default
        instance.property_values[self.name] = value
        return value

    def __set__(self, instance, value):
        if instance.property_values.get(self.name, None) != value:
            instance.set_property(self.name, self.type.property_type, value)

    def __delete__(self, instance):
        instance.delete_property(self.name)

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
        for superclass in reversed(cls.__mro__):
            if hasattr(superclass, "properties"):
                cls.properties.update(superclass.properties)
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
        self.offset = None # determined and set by our decorator
        self.focus_override = None
        self.property_values = {}
        self.property_cookies = {}
        self.property_change_handlers = defaultdict(set)
        self.conn.core.ChangeWindowAttributes(self.window, CW.EventMask,
                                              [self.client_event_mask])
        self.__log = logging.getLogger("client.0x%x" % self.window)
        self.init(self.screen.root)

    def init(self, parent):
        """Initialize a client window instance. Called during instance
        initialization and whenever an instance's class is changed."""
        self.parent = parent
        self.reparenting = None
        self._geometry = None

    @property
    def geometry(self):
        """Return the client window geometry relative to its parent's origin."""
        if self._geometry is None:
            self._geometry = window_geometry(self.conn, self.window)
        return self._geometry

    @geometry.setter
    def geometry(self, geometry):
        assert isinstance(geometry, Geometry), "invalid geometry %r" % geometry
        self._geometry = geometry

    @property
    def frame_geometry(self):
        """Return the client frame geometry. For non-reparented client windows,
        this will just be the window geometry."""
        return self.geometry

    @property
    def absolute_geometry(self):
        """Return the client window geometry relative to the root's origin."""
        return self.geometry

    def absolute_to_frame_geometry(self, geometry):
        """Convert an absolute client window geometry to a frame geometry."""
        return geometry

    def frame_to_absolute_geometry(self, geometry):
        """Convert a frame geometry to an absolute client geometry."""
        return geometry

    def move(self, position):
        """Move the client window and return its new position."""
        position = self.manager.constrain_position(self, position)
        self.conn.core.ConfigureWindow(self.window,
                                       ConfigWindow.X | ConfigWindow.Y,
                                       map(int16, position))
        self.geometry = self.geometry.move(position) # provisional
        return position

    def resize(self, size, border_width=None, gravity=None):
        """Resize the client window and return the new geometry, which may
        differ in both size and position due to size constraints and gravity."""
        geometry = self.manager.constrain_size(self, self.absolute_geometry,
                                               size, border_width, gravity)
        return self.configure(geometry)

    def moveresize(self, geometry, gravity=None):
        """Change the client window geometry, respecting size hints and using
        the specified gravity. Returns the new geometry."""
        return self.configure(self.manager.constrain_size(self,
                                                          geometry,
                                                          gravity=gravity))

    def configure(self, geometry):
        """Change the client window geometry."""
        self.conn.core.ConfigureWindow(self.window,
                                       (ConfigWindow.X |
                                        ConfigWindow.Y |
                                        ConfigWindow.Width |
                                        ConfigWindow.Height |
                                        ConfigWindow.BorderWidth),
                                       [int16(geometry.x),
                                        int16(geometry.y),
                                        card16(geometry.width),
                                        card16(geometry.height),
                                        card16(geometry.border_width)])
        self.decorator.configure(geometry)
        self.geometry = geometry # provisional update
        return geometry

    def restack(self, stack_mode):
        self.conn.core.ConfigureWindow(self.window,
                                       ConfigWindow.StackMode,
                                       [stack_mode])

    def focus(self, time=Time.CurrentTime):
        """Offer the input focus to the client."""
        # We'll occasionally want to preempt focus of a client window
        # (e.g., for user input in a titlebar).
        if self.focus_override:
            self.__log.debug("Redirecting focus to window 0x%x.",
                             self.focus_override)
            self.conn.core.SetInputFocus(InputFocus.PointerRoot,
                                         self.focus_override, time)
            return True

        # See ICCCM §4.1.7.
        focused = False
        if (self.wm_hints.flags & WMHints.InputHint == 0 or
            self.wm_hints.input):
            self.__log.debug("Setting input focus at time %d.", time)
            self.conn.core.SetInputFocus(InputFocus.PointerRoot,
                                         self.window, time)
            focused = True
        if self.atoms["WM_TAKE_FOCUS"] in self.wm_protocols:
            self.__log.debug("Taking input focus at time %d.", time)
            send_client_message(self.conn, self.window, self.window, 0,
                                32, self.atoms["WM_PROTOCOLS"],
                                [self.atoms["WM_TAKE_FOCUS"], time, 0, 0, 0])
            focused = True
        return focused

    def unfocus(self):
        self.decorator.unfocus()

    def map(self):
        self.conn.core.MapWindow(self.window)

    def unmap(self):
        self.conn.core.UnmapWindow(self.window)

    def request_property(self, name, type=None):
        """Request the value of a property of the client window, and return
        a cookie for the request. Does not wait for a reply."""
        if type is None:
            type = (self.properties[name].property_type
                    if name in self.properties
                    else GetPropertyType.Any)
        self.__log.debug("Requesting property %s.", name)
        name = self.atoms[name] if isinstance(name, str) else name
        type = self.atoms[type] if isinstance(type, str) else type
        return self.conn.core.GetProperty(False, self.window, name, type,
                                          0, 0xffffffff)

    def set_property(self, name, type, value, mode=PropMode.Replace):
        """Change the value of a property on the client window."""
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
        self.conn.core.ChangeProperty(mode, self.window,
                                      self.atoms[name], self.atoms[type],
                                      format, data_len, data)

        # We'll accept the given value as provisionally correct until a
        # PropertyNotify comes in to inform us that the server has a new,
        # canonical value.
        self.property_values[name] = value

        # Any pending request for the property value should be canceled.
        self.property_cookies.pop(name, None)

    def request_properties(self):
        """Request the client properties for which we don't have a cached
        value or a pending request. Does not wait for any of the replies."""
        for name in self.properties:
            if (name not in self.property_values and
                name not in self.property_cookies):
                self.property_cookies[name] = self.request_property(name)

    def delete_property(self, name):
        """Remove the given property from the client window."""
        self.__log.debug("Deleting property %s.", name)
        self.conn.core.DeleteProperty(self.window, self.atoms[name])
        self.invalidate_cached_property(name)

    def property_changed(self, name, deleted):
        """Handle a change or deletion of a property."""
        self.__log.debug("Property %s %s.",
                         name, ("deleted" if deleted else "changed"))
        if deleted:
            self.invalidate_cached_property(name)
        else:
            # Dump our cached value and, if it's a property that we care
            # about, request (but do not wait for) the new value.
            self.property_values.pop(name, None)
            if name in self.properties:
                self.property_cookies[name] = self.request_property(name)

        # Invoke any handlers registered for this property change.
        for handler in self.property_change_handlers.get(name, []):
            handler(self, name, deleted)

    def invalidate_cached_property(self, name):
        """Invalidate any cached request or value for the given property."""
        if name in self.property_values:
            del self.property_values[name]
        if name in self.property_cookies:
            del self.property_cookies[name]

    def register_property_change_handler(self, name, handler):
        self.property_change_handlers[name].add(handler)

    def unregister_property_change_handler(self, name, handler):
        self.property_change_handlers[name].discard(handler)

    # ICCCM properties
    wm_name = ClientProperty("WM_NAME", String, "")
    wm_icon_name = ClientProperty("WM_ICON_NAME", String, "")
    wm_normal_hints = ClientProperty("WM_NORMAL_HINTS",
                                     WMSizeHints,
                                     WMSizeHints())
    wm_hints = ClientProperty("WM_HINTS", WMHints, WMHints())
    wm_class = ClientProperty("WM_CLASS", WMClass, (None, None))
    wm_transient_for = ClientProperty("WM_TRANSIENT_FOR", WMTransientFor)
    wm_protocols = ClientProperty("WM_PROTOCOLS", WMProtocols, [])
    wm_state = ClientProperty("WM_STATE", WMState, WMState())

    # EWMH properties
    net_wm_name = ClientProperty("_NET_WM_NAME", UTF8String, "")
    net_wm_icon_name = ClientProperty("_NET_WM_ICON_NAME", UTF8String, "")

    # Dim-specific properties
    dim_tags = ClientProperty("_DIM_TAGS", AtomList, [])

class FramedClientWindow(ClientWindow):
    """A framed client window represents a client window that has been
    reparented to a new top-level window.

    Instances of this class are never created directly; a reparenting
    window manager will change the class of ClientWindow instances to
    this class upon receipt of a ReparentNotify event."""

    def init(self, parent):
        assert self.frame and self.frame == parent
        assert self.offset is not None
        super(FramedClientWindow, self).init(parent)
        self._frame_geometry = None

    @property
    def frame_geometry(self):
        if self._frame_geometry is None:
            self._frame_geometry = window_geometry(self.conn, self.frame)
        return self._frame_geometry

    @frame_geometry.setter
    def frame_geometry(self, geometry):
        assert isinstance(geometry, Geometry), "invalid geometry %r" % geometry
        self._frame_geometry = geometry

    @property
    def absolute_geometry(self):
        return self.geometry.move(self.frame_geometry.position() +
                                  self.offset.position())

    def absolute_to_frame_geometry(self, geometry):
        return (geometry.reborder(self.frame_geometry.border_width) -
                self.offset.position() +
                self.offset.size())

    def frame_to_absolute_geometry(self, geometry):
        return (geometry.reborder(0) +
                self.offset.position() -
                self.offset.size())

    def move(self, position):
        position = self.manager.constrain_position(self, position)
        self.conn.core.ConfigureWindow(self.frame,
                                       ConfigWindow.X | ConfigWindow.Y,
                                       map(int16, position))
        self.frame_geometry = self.frame_geometry.move(position) # provisional
        return position

    def configure(self, geometry):
        # Geometry is the requested client window geometry in the root
        # coordinate system.
        frame_geometry = self.absolute_to_frame_geometry(geometry)
        self.conn.core.ConfigureWindow(self.frame,
                                       (ConfigWindow.X |
                                        ConfigWindow.Y |
                                        ConfigWindow.Width |
                                        ConfigWindow.Height |
                                        ConfigWindow.BorderWidth),
                                       [int16(frame_geometry.x),
                                        int16(frame_geometry.y),
                                        card16(frame_geometry.width),
                                        card16(frame_geometry.height),
                                        card16(frame_geometry.border_width)])
        self.conn.core.ConfigureWindow(self.window,
                                       (ConfigWindow.Width |
                                        ConfigWindow.Height),
                                       [card16(geometry.width),
                                        card16(geometry.height)])
        self.decorator.configure(frame_geometry)
        # Provisionally set new geometry.
        self.frame_geometry = frame_geometry
        self.geometry = self.geometry.resize(geometry.size())
        return geometry

    def restack(self, stack_mode):
        self.conn.core.ConfigureWindow(self.frame,
                                       ConfigWindow.StackMode,
                                       [stack_mode])

    def map(self):
        super(FramedClientWindow, self).map()
        self.conn.core.MapWindow(self.frame)

    def unmap(self):
        self.conn.core.UnmapWindow(self.frame)
        super(FramedClientWindow, self).unmap()
