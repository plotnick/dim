# -*- mode: Python; coding: utf-8 -*-

"""Support for the Extended Window Manager Hints (EWMH) specification."""

import logging

import xcb
from xcb.xproto import *

from client import Client
from decorator import Decorator
from event import handler
from focus import FocusPolicy
from geometry import Geometry
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
# separate class for each one.
net_wm_state_classes = {}
def net_wm_state(state_name):
    """A class decorator factory that registers a state change class."""
    def register_state_class(cls):
        net_wm_state_classes[state_name] = cls
        return cls
    return register_state_class

# Valid actions in a _NET_WM_STATE client message.
_NET_WM_STATE_REMOVE = 0
_NET_WM_STATE_ADD = 1
_NET_WM_STATE_TOGGLE = 2

class NetWMStateChange(object):
    def __init__(self, manager, client, action, state, source):
        self.manager = manager
        self.client = client
        self.log = client.log
        self.atoms = manager.atoms

        action = {_NET_WM_STATE_REMOVE: self.remove,
                  _NET_WM_STATE_ADD: self.add,
                  _NET_WM_STATE_TOGGLE: self.toggle}.get(action)
        if action:
            action(state, source)
        else:
            self.log.warning("Bad action %d in _NET_WM_STATE client message.",
                             action)

    def add(self, state, source):
        self.log.debug("Adding EWMH state %s.", self.atoms.name(state))
        if state not in self.client.net_wm_state:
            self.client.net_wm_state += [state]

    def remove(self, state, source):
        self.log.debug("Removing EWMH state %s.", self.atoms.name(state))
        self.client.net_wm_state = [atom
                                    for atom in self.client.net_wm_state
                                    if atom != state]

    def toggle(self, state, source):
        if state in self.client.net_wm_state:
            self.remove(state, source)
        else:
            self.add(state, source)

@net_wm_state("_NET_WM_STATE_FULLSCREEN")
class NetWMStateFullscreen(NetWMStateChange):
    def add(self, state, source):
        if state not in self.client.net_wm_state:
            self.client.fullscreen()
            super(NetWMStateFullscreen, self).add(state, source)

    def remove(self, state, source):
        if state in self.client.net_wm_state:
            self.client.unfullscreen()
            super(NetWMStateFullscreen, self).remove(state, source)

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

    def frame(self, decorator, geometry):
        if self.atoms["_NET_WM_STATE_FULLSCREEN"] in self.net_wm_state:
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
        # The dual states are really only there to support simultaneous
        # horizontal & vertical maximization, but since we support those
        # independently, we don't care.
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
