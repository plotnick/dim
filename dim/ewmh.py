# -*- mode: Python; coding: utf-8 -*-

"""Support for the Extended Window Manager Hints (EWMH) specification."""

import logging

import xcb
from xcb.xproto import *

from client import Client
from decorator import Decorator
from event import handler
from focus import FocusPolicy
from geometry import Position, Rectangle, Geometry
from manager import WindowManager
from properties import *
from xutil import *

log = logging.getLogger("net")

class EWMHCapability(WindowManager):
    net_supported = PropertyDescriptor("_NET_SUPPORTED", AtomList, [])

    def start(self):
        properties = (set(self.properties) |
                      set(self.default_client_class.properties))
        try:
            # Not all of the EWMH atoms that we wish to advertise as
            # supported have property descriptors (e.g., the various
            # _NET_WM_STATE_* atoms), so we'll use a client class method
            # to collect the rest.
            properties |= set(self.default_client_class.net_supported_extras())
        except AttributeError:
            pass
        self.net_supported = [self.atoms[name]
                              for name in sorted(properties)
                              if name.startswith("_NET")]
        super(EWMHCapability, self).start()

class CheckWindowProperties(PropertyManager):
    net_wm_name = PropertyDescriptor("_NET_WM_NAME", UTF8StringProperty, "")
    net_supporting_wm_check = PropertyDescriptor("_NET_SUPPORTING_WM_CHECK",
                                                 WindowProperty)

class NetSupportingWMCheck(EWMHCapability, FocusPolicy):
    net_supporting_wm_check = PropertyDescriptor("_NET_SUPPORTING_WM_CHECK",
                                                 WindowProperty)

    def start(self):
        # We'll use the default focus window as the supporting WM check
        # window. This is the only reason we inherit from FocusPolicy.
        window = self.default_focus_window
        self.net_supporting_wm_check = window
        window_properties = CheckWindowProperties(self.conn, window, self.atoms)
        window_properties.net_wm_name = "Dim"
        window_properties.net_supporting_wm_check = window

        super(NetSupportingWMCheck, self).start()

class NetClientList(EWMHCapability):
    net_client_list = PropertyDescriptor("_NET_CLIENT_LIST", WindowList, [])

    def start(self):
        self.net_client_list = WindowList([])
        super(NetClientList, self).start()

    def manage(self, window, adopted=False):
        client = super(NetClientList, self).manage(window, adopted)
        if client:
            self.net_client_list += [client.window]
        return client

    def unmanage(self, client, **kwargs):
        self.net_client_list = [window
                                for window in self.net_client_list
                                if window != client.window]
        super(NetClientList, self).unmanage(client, **kwargs)

class NetActiveWindow(EWMHCapability, FocusPolicy):
    net_active_window = PropertyDescriptor("_NET_ACTIVE_WINDOW", WindowProperty)

    def focus(self, *args, **kwargs):
        try:
            return super(NetActiveWindow, self).focus(*args, **kwargs)
        finally:
            if (not self.current_focus or
                self.current_focus is self.default_focus_window):
                self.net_active_window = Window._None
            else:
                self.net_active_window = self.current_focus.window

class NetWMNameClient(Client):
    net_wm_name = PropertyDescriptor("_NET_WM_NAME", UTF8StringProperty, "")
    net_wm_icon_name = PropertyDescriptor("_NET_WM_ICON_NAME",
                                          UTF8StringProperty, "")

    @property
    def title(self):
        return self.net_wm_name or super(NetWMNameClient, self).title

    def register_title_change_handler(self, handler):
        super(NetWMNameClient, self).register_title_change_handler(handler)
        self.register_property_change_handler("_NET_WM_NAME", handler)

    def unregister_title_change_handler(self, handler):
        super(NetWMNameClient, self).unregister_title_change_handler(handler)
        self.unregister_property_change_handler("_NET_WM_NAME", handler)

@client_message("_NET_WM_STATE")
class NetWMState(ClientMessage):
    """A request to change the state of a mapped window."""
    pass

# _NET_WM_STATE contains a list of (mostly) independent hints; we'll use a
# separate class for each one (or set of closely related states).
net_wm_state_classes = {}
def net_wm_state(state_name):
    """A class decorator factory that registers a state change class."""
    def register_state_class(cls):
        net_wm_state_classes[state_name] = cls
        return cls
    return register_state_class

class NetWMStateChange(object):
    """Changes to the _NET_WM_STATE property take one of three basic forms:
    remove, add, or toggle a state or set of (at most two) states. In almost
    all cases, only one state is changed at a time; the notable counterexample
    is horizontal and vertical maximization, which are often changed together.
    But handling state changes either one at a time or as a set adds
    considerable complexity for minimal gain (viz., slightly more efficient
    maximization), so we simply don't bother.

    This class only does dispatch; subclasses should define enable and
    disable methods that actually enact the state changes. We try to ensure
    that those methods are never called spuriously: i.e., if the client is
    already in state X, we will not call enable(X). This relieves the
    underlying methods of the burden of being idempotent."""

    # Valid actions in a _NET_WM_STATE client message.
    _NET_WM_STATE_REMOVE = 0
    _NET_WM_STATE_ADD = 1
    _NET_WM_STATE_TOGGLE = 2

    def __init__(self, manager, client, action, state, source):
        self.manager = manager
        self.client = client
        self.log = client.log
        self.atoms = manager.atoms

        method = {self._NET_WM_STATE_REMOVE: self.remove,
                  self._NET_WM_STATE_ADD: self.add,
                  self._NET_WM_STATE_TOGGLE: self.toggle}.get(action)
        if method:
            method(state, source)
        else:
            self.log.warning("Bad action %d in _NET_WM_STATE client message.",
                             action)

    def in_state(self, state):
        return state in self.client.net_wm_state

    def remove(self, state, source):
        if self.in_state(state):
            self.disable(state, source)
            self.log.debug("Removing EWMH state %s.", self.atoms.name(state))
            self.client.net_wm_state = [atom
                                        for atom in self.client.net_wm_state
                                        if atom != state]

    def add(self, state, source):
        if not self.in_state(state):
            self.enable(state, source)
            self.log.debug("Adding EWMH state %s.", self.atoms.name(state))
            self.client.net_wm_state += [state]

    def toggle(self, state, source):
        if self.in_state(state):
            self.remove(state, source)
        else:
            self.add(state, source)

@net_wm_state("_NET_WM_STATE_FULLSCREEN")
class NetWMStateFullscreen(NetWMStateChange):
    def enable(self, state, source):
        self.client.fullscreen()

    def disable(self, state, source):
        self.client.unfullscreen()

class NetWMStateMaximized(NetWMStateChange):
    vertical = horizontal = True

    def enable(self, state, source):
        self.client.maximize(vertical=self.vertical,
                             horizontal=self.horizontal)

    def disable(self, state, source):
        self.client.unmaximize(vertical=self.vertical,
                               horizontal=self.horizontal)

@net_wm_state("_NET_WM_STATE_MAXIMIZED_VERT")
class NetWMStateMaximizedVert(NetWMStateMaximized):
    vertical, horizontal = True, False

@net_wm_state("_NET_WM_STATE_MAXIMIZED_HORZ")
class NetWMStateMaximizedHorz(NetWMStateMaximized):
    vertical, horizontal = False, True

class FullscreenDecorator(Decorator):
    """A trivial decorator for fullscreen windows."""
    def __init__(self, conn, client, border_width=0, **kwargs):
        super(FullscreenDecorator, self).__init__(conn, client, border_width,
                                                  **kwargs)

class GeometryProperty(PropertyValueStruct):
    """A property value that represents a window geometry."""
    property_format = 16
    property_type = "_DIM_GEOMETRY"
    fields = (("x", INT16),
              ("y", INT16),
              ("width", CARD16),
              ("height", CARD16),
              ("border_width", CARD16))

class NetWMStateClient(Client):
    net_wm_state = PropertyDescriptor("_NET_WM_STATE", AtomList, [])
    dim_saved_geometry = PropertyDescriptor("_DIM_SAVED_GEOMETRY",
                                            GeometryProperty)

    @classmethod
    def net_supported_extras(cls):
        return net_wm_state_classes.keys()

    def in_net_wm_state(self, name):
        return self.atoms[name] in self.net_wm_state

    def frame(self, decorator, geometry):
        if self.in_net_wm_state("_NET_WM_STATE_FULLSCREEN"):
            self.log.debug("Restoring fullscreen mode.")
            assert decorator, "Need decorator to save."
            self.saved_decorator = decorator
            decorator = FullscreenDecorator(self.conn, self)
        super(NetWMStateClient, self).frame(decorator, geometry)

    def fullscreen(self):
        """Fill the screen with the trivially-decorated client window."""
        decorator = FullscreenDecorator(self.conn, self)
        self.saved_decorator, self.saved_geometry = self.redecorate(decorator)
        self.configure(self.manager.fullscreen_geometry(self),
                       stack_mode=StackMode.TopIf)
        assert self.absolute_geometry == self.frame_geometry

    def unfullscreen(self):
        """Restore the non-fullscreen geometry."""
        self.redecorate(self.saved_decorator)
        self.configure(self.saved_geometry)
        self.saved_decorator = self.saved_geometry = None

    @property
    def maximized_horizontally(self):
        return self.in_net_wm_state("_NET_WM_STATE_MAXIMIZED_HORZ")

    @property
    def maximized_vertically(self):
        return self.in_net_wm_state("_NET_WM_STATE_MAXIMIZED_VERT")

    @property
    def maximized(self):
        return self.maximized_horizontally or self.maximized_vertically

    @staticmethod
    def maxmessage(positive, horizontal, vertical):
        return ("%simizing %s." %
                ("Max" if positive else "Unmax",
                 ", ".join(filter(None, [horizontal and "horizontally",
                                         vertical and "vertically"]))))

    def maximize(self, horizontal=True, vertical=True):
        """Fill the screen horizontally, vertically, or completely with the
        decorated client window."""
        self.log.debug(self.maxmessage(True, horizontal, vertical))
        if not self.saved_geometry:
            self.saved_geometry = self.absolute_geometry

        frame = self.frame_geometry
        max = (self.manager.fullscreen_geometry(self) -
               Rectangle(2 * frame.border_width, 2 * frame.border_width))
        if horizontal:
            frame = Geometry(max.x, frame.y, max.width, frame.height, 0)
        if vertical:
            frame = Geometry(frame.x, max.y, frame.width, max.height, 0)
        self.configure(self.frame_to_absolute_geometry(frame))

    def unmaximize(self, horizontal=True, vertical=True):
        self.log.debug(self.maxmessage(False, horizontal, vertical))
        if not self.saved_geometry:
            self.log.warning("No saved geometry to restore.")
            return
        frame = self.frame_geometry
        saved = self.absolute_to_frame_geometry(self.saved_geometry)
        if horizontal:
            frame = Geometry(saved.x, frame.y, saved.width, frame.height, 0)
        if vertical:
            frame = Geometry(frame.x, saved.y, frame.width, saved.height, 0)
        self.configure(self.frame_to_absolute_geometry(frame))

        if ((horizontal and self.maximized_horizontally and
             not self.maximized_vertically) or
            (vertical and self.maximized_vertically and
             not self.maximized_horizontally)):
            self.saved_geometry = None

    @property
    def saved_geometry(self):
        """Retrieve the saved geometry."""
        g = self.dim_saved_geometry
        if g:
            return Geometry(g.x, g.y, g.width, g.height, g.border_width)

    @saved_geometry.setter
    def saved_geometry(self, geometry):
        """Update or erase the saved geometry."""
        if geometry:
            self.dim_saved_geometry = GeometryProperty(*geometry)
        else:
            del self.dim_saved_geometry

    @handler(NetWMState)
    def handle_state_change(self, client_message):
        # A state change message consists of an action (add, remove, toggle),
        # one or two states, and a source indication (application or user).
        # We always treat the states as independent.
        action, first, second, source, _ = client_message.data.data32
        for atom in first, second:
            if atom:
                handler = net_wm_state_classes.get(self.atoms.name(atom))
                if handler:
                    handler(self.manager, self, action, atom, source)

class NetWMState(EWMHCapability):
    default_client_class = NetWMStateClient

# Top-level classes: combine all of the above.

class EWMHClient(NetWMNameClient, NetWMStateClient):
    pass

class EWMHManager(NetSupportingWMCheck,
                  NetClientList,
                  NetActiveWindow,
                  NetWMState):
    default_client_class = EWMHClient
