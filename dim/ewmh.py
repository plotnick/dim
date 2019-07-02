# -*- mode: Python; coding: utf-8 -*-

"""Support for the Extended Window Manager Hints (EWMH) specification:
<http://standards.freedesktop.org/wm-spec/wm-spec-latest.html>.

The EWMH specification defines a set of extensions to the ICCCM targeted
at users and implementors of so-called "desktop environments" for the
X window system (e.g., GNOME and KDE). It defines a number of "hints"
(in the generic sense of the ICCCM) and simple protocols, all of which
are named by atoms whose names start with the prefix "_NET". (Why not
"_EWMH"? Dunno. Maybe nobody could remember how to spell it.)

One of its core features is an extended set of client states which go
beyond the simple Withdrawn/Iconic/Normal triplet defined by the ICCCM.
For example, it defines states for horizontal and vertical maximization,
fullscreen mode, shading & hiding, &c. We implement some, but not all,
of these states, and treat them as basically independent of the ICCCM states.

The specification also defines a largish set of hints and protocols related
to virtual desktops, pagers, taskbars, and other related features of many
modern (i.e., post-TWM) X window managers and desktop environments. Many of
these are simply inapplicable to Dim in its current form (e.g., tags are not
virtual desktops), and so we make no attempt to support them. There are also
a host of other hints that we don't support simply because we haven't gotten
around to implementing them.

In particular, we should attach to the move/resize module and implement the
hints _NET_MOVERESIZE_WINDOW and _NET_WM_MOVERESIZE. Other miscellaneous
hints we should implement include _NET_CLOSE_WINDOW, _NET_RESTACK_WINDOW,
_NET_REQUEST_FRAME_EXTENTS.

Happily, the EWMH was designed to be implemented piecemeal. It defines a
property that a conforming window manager should place on the root window
(_NET_SUPPORTED) which lists all of the hints that it supports. Clients may
use this property to decide which hints to use. If a hint does not appear
in the list, it must be assumed to be unsupported.

Our implementation strategy for supporting EWMH hints is to use individual
classes (or small groups of related classes) to support each hint or feature,
and then to mix all of these classes together at the end. We call a subclass
of WindowManager that implements an EWMH hint (or set of related hints) a
"capability". Such classes may also depend on related subclasses of Client
or specific auxiliary classes, but should, in general, be independent of
one another. One exception is the _NET_SUPPORTED hint, which is implemented
so that capability classes can advertise the hints they support in an
almost totally automatic fasion."""

import logging

import xcb
from xcb.xproto import *

from client import Client
from decorator import Decorator
from event import StopPropagation, handler
from focus import FocusPolicy
from geometry import Position, Rectangle, Geometry
from manager import WindowManager
from properties import *
from xutil import *

__all__ = ["_NET_WM_STATE_REMOVE", "_NET_WM_STATE_ADD", "_NET_WM_STATE_TOGGLE",
           "EWMHClient", "EWMHManager"]

log = logging.getLogger("net")

class NetClient(Client):
    def net_supported_extras(self):
        """Return a list of non-property atoms that should be advertised
        in the _NET_SUPPORTED property."""
        return []

class NetCapability(WindowManager):
    """Automatically advertise EWMH hints via the _NET_SUPPORTED property.
    A single capability may involve multiple hints."""

    net_supported = PropertyDescriptor("_NET_SUPPORTED", AtomList, [])

    default_client_class = NetClient

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
        super(NetCapability, self).start()

class CheckWindowProperties(PropertyManager):
    """A property manager for the EWMH supporting WM check window."""
    net_wm_name = PropertyDescriptor("_NET_WM_NAME", UTF8StringProperty, "")
    net_supporting_wm_check = PropertyDescriptor("_NET_SUPPORTING_WM_CHECK",
                                                 WindowProperty)

class NetSupportingWMCheck(NetCapability, FocusPolicy):
    """Advertise support for the EWMH via a check window."""
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

class NetClientList(NetCapability):
    """Advertise a list of managed clients."""
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

class NetActiveWindow(NetCapability, FocusPolicy):
    """Advertise the currently active (focused) window."""
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

class NetWMNameClient(NetClient):
    """Unicode versions of the window and icon names."""
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
class NetWMStateMessage(ClientMessage):
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

# Valid actions in a _NET_WM_STATE client message.
_NET_WM_STATE_REMOVE = 0
_NET_WM_STATE_ADD = 1
_NET_WM_STATE_TOGGLE = 2

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
    underlying methods of the burden of being idempotent. State changes
    may also be rejected, so enable and disable should return boolean
    success values."""

    def __init__(self, manager, client, action, state, source):
        self.manager = manager
        self.client = client
        self.log = client.log
        self.atoms = manager.atoms

        method = {_NET_WM_STATE_REMOVE: self.remove,
                  _NET_WM_STATE_ADD: self.add,
                  _NET_WM_STATE_TOGGLE: self.toggle}.get(action)
        if method:
            method(state, source)
        else:
            self.log.warning("Bad action %d in _NET_WM_STATE client message.",
                             action)

    def in_state(self, state):
        return state in self.client.net_wm_state

    def remove(self, state, source):
        if self.in_state(state) and self.disable(state, source):
            self.log.debug("Removing state %s.", self.atoms.name(state))
            self.client.net_wm_state = [atom
                                        for atom in self.client.net_wm_state
                                        if atom != state]

    def add(self, state, source):
        if not self.in_state(state) and self.enable(state, source):
            self.log.debug("Adding state %s.", self.atoms.name(state))
            self.client.net_wm_state += [state]

    def toggle(self, state, source):
        if self.in_state(state):
            self.remove(state, source)
        else:
            self.add(state, source)

@net_wm_state("_NET_WM_STATE_FULLSCREEN")
class NetWMStateFullscreen(NetWMStateChange):
    def enable(self, state, source):
        return self.client.fullscreen()

    def disable(self, state, source):
        return self.client.unfullscreen()

class NetWMStateMaximized(NetWMStateChange):
    vertical = horizontal = True

    def enable(self, state, source):
        return self.client.maximize(vertical=self.vertical,
                                    horizontal=self.horizontal)

    def disable(self, state, source):
        return self.client.unmaximize(vertical=self.vertical,
                                      horizontal=self.horizontal)

@net_wm_state("_NET_WM_STATE_MAXIMIZED_VERT")
class NetWMStateMaximizedVert(NetWMStateMaximized):
    vertical, horizontal = True, None

@net_wm_state("_NET_WM_STATE_MAXIMIZED_HORZ")
class NetWMStateMaximizedHorz(NetWMStateMaximized):
    vertical, horizontal = None, True

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

class NetWMStateClient(NetClient):
    net_wm_state = PropertyDescriptor("_NET_WM_STATE", AtomList, [])
    dim_saved_geometry = PropertyDescriptor("_DIM_SAVED_GEOMETRY",
                                            GeometryProperty)

    def __init__(self, *args, **kwargs):
        super(NetWMStateClient, self).__init__(*args, **kwargs)

        self.saved_decorator = None

    def frame(self, decorator, geometry):
        if self.is_fullscreen():
            self.log.debug("Restoring fullscreen mode.")
            assert decorator, "need a decorator to save"
            self.saved_decorator = decorator
            decorator = FullscreenDecorator(self.conn, self)
        super(NetWMStateClient, self).frame(decorator, geometry)

    @classmethod
    def net_supported_extras(cls):
        return net_wm_state_classes.keys()

    def in_net_wm_state(self, name):
        return self.atoms[name] in self.net_wm_state

    def is_fullscreen(self):
        return self.in_net_wm_state("_NET_WM_STATE_FULLSCREEN")

    def is_maximized_horizontally(self):
        return self.in_net_wm_state("_NET_WM_STATE_MAXIMIZED_HORZ")

    def is_maximized_vertically(self):
        return self.in_net_wm_state("_NET_WM_STATE_MAXIMIZED_VERT")

    def is_maximized(self):
        return (self.is_maximized_horizontally() or
                self.is_maximized_vertically())

    def withdraw(self):
        """According to the EWMH, the _NET_WM_STATE property should be removed
        whenever a window is withdrawn. This can lead to funny results, such
        as being able to obtain a window only a fullscreen decorator if it's
        re-normalized before being unmanaged. But that's probably not a common
        thing to do."""
        del self.net_wm_state
        super(NetWMStateClient, self).withdraw()

    def fullscreen(self):
        """Fill the screen with the trivially-decorated client window."""
        decorator = FullscreenDecorator(self.conn, self)
        self.saved_decorator, old_geometry = self.redecorate(decorator)
        if not self.saved_geometry:
            self.saved_geometry = old_geometry
        try:
            return self.configure(self.manager.fullscreen_geometry(self),
                                  stack_mode=StackMode.TopIf)
        finally:
            assert self.absolute_geometry == self.frame_geometry
            self.manager.ensure_focus(self)

    def unfullscreen(self):
        """Restore the non-fullscreen geometry."""
        if self.saved_decorator:
            self.redecorate(self.saved_decorator)
            self.saved_decorator = None
        if self.is_maximized():
            return self.maximize(check_fullscreen=False)
        else:
            try:
                return self.configure(self.saved_geometry)
            finally:
                self.saved_geometry = None

    @staticmethod
    def maxmessage(positive, horizontal, vertical):
        return ("%simizing %s." %
                ("Max" if positive else "Unmax",
                 "completely" if horizontal and vertical else
                 "horizontally" if horizontal else
                 "vertically" if vertical else
                 "trivially"))

    def maximize(self, horizontal=None, vertical=None, constrain_size=True,
                 check_fullscreen=True):
        """Fill the screen horizontally, vertically, or completely with the
        decorated client window. If either of the horizontal or vertical
        arguments are None, they default to the current corresponding state.

        If constrain_size is true (the default), then the maximum size will
        be constrained according to the manager's constrain_size method.
        Unless the latter is overridden, maximization will thus obey the
        client's size hints. This behavior differs from that of some other
        window managers, but seems to be allowed (or at least not prohibited)
        by the EWMH specification.

        Maximization requests in fullscreen mode are honored, but trivially.
        When we leave fullscreen mode, we'll restore the saved geometry
        according to the current maximization state. The check_fullscreen
        argument is used only by unfullscreen in this context."""
        if check_fullscreen and self.is_fullscreen():
            return True

        horizontal = (self.is_maximized_horizontally()
                      if horizontal is None else horizontal)
        vertical = (self.is_maximized_vertically()
                    if vertical is None else vertical)
        self.log.debug(self.maxmessage(True, horizontal, vertical))

        if not self.saved_geometry:
            self.saved_geometry = self.absolute_geometry
        frame = self.absolute_to_frame_geometry(self.saved_geometry)
        full = self.manager.fullscreen_geometry(self)
        if not frame or not full:
            self.log.warning("Can't determine maximum geometry.")
            return False

        max = (full - Rectangle(2 * frame.border_width, 2 * frame.border_width))
        if horizontal:
            frame = Geometry(max.x, frame.y, max.width, frame.height, 0)
        if vertical:
            frame = Geometry(frame.x, max.y, frame.width, max.height, 0)
        geometry = self.frame_to_absolute_geometry(frame)
        return self.configure(self.manager.constrain_size(self, geometry)
                              if constrain_size else geometry)

    def unmaximize(self, horizontal=True, vertical=True):
        """Revert to the saved geometry horizontally, vertically,
        or completely."""
        # Trivially honor request in fullscreen mode.
        if self.is_fullscreen():
            return True

        self.log.debug(self.maxmessage(False, horizontal, vertical))
        if not self.saved_geometry:
            self.log.warning("No saved geometry to restore.")
            return False
        frame = self.frame_geometry
        saved = self.absolute_to_frame_geometry(self.saved_geometry)
        if horizontal:
            frame = Geometry(saved.x, frame.y, saved.width, frame.height, 0)
        if vertical:
            frame = Geometry(frame.x, saved.y, frame.width, saved.height, 0)
        try:
            return self.configure(self.frame_to_absolute_geometry(frame))
        finally:
            # Clear the saved geometry, but only if nobody needs it.
            if ((horizontal and vertical) or
                (horizontal and not self.is_maximized_vertically()) or
                (vertical and not self.is_maximized_horizontally())):
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
            self.log.debug("Saving geometry %s.", geometry)
            self.dim_saved_geometry = GeometryProperty(*geometry)
        else:
            self.log.debug("Clearing saved geometry.")
            del self.dim_saved_geometry

    @handler(NetWMStateMessage)
    def handle_state_change(self, client_message):
        # A state change message consists of an action (add, remove, toggle),
        # one or two states, and a source indication (application or user).
        # We always treat the states as independent.
        action, first, second, source, _ = client_message.data.data32
        for atom in first, second:
            if atom:
                name = self.atoms.name(atom)
                handler = net_wm_state_classes.get(name)
                if handler:
                    assert issubclass(handler, NetWMStateChange)
                    handler(self.manager, self, action, atom, source)
                else:
                    self.log.debug("Ignoring hint %s.", name)
        raise StopPropagation

class NetWMState(NetCapability):
    default_client_class = NetWMStateClient

    def send_net_wm_state(self, window, action, first, second=0, source=0):
        "Send a _NET_WM_STATE client message to the root window."
        if isinstance(window, Client):
            window = client.window
        send_client_message(self.conn, self.screen.root, False,
                            (EventMask.SubstructureRedirect |
                             EventMask.SubstructureNotify),
                            window, self.atoms["_NET_WM_STATE"],
                            32, [action, first, second, source, 0])


# Top-level classes: combine all of the above.

class EWMHClient(NetWMNameClient, NetWMStateClient):
    pass

class EWMHManager(NetSupportingWMCheck,
                  NetClientList,
                  NetActiveWindow,
                  NetWMState):
    default_client_class = EWMHClient
