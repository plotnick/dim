# -*- mode: Python; coding: utf-8 -*-

"""A window manager manages the children of the root window of a screen."""

import logging
from functools import wraps
from select import select

from xcb.xproto import *

from atom import AtomCache
from client import ClientWindow
from color import ColorCache
from cursor import FontCursor
from decorator import Decorator, FrameDecorator
from event import UnhandledEvent, EventHandler, handler
from font import FontCache
from geometry import *
from keymap import KeymapError, KeyboardMap
from properties import *
from xutil import *

__all__ = ["ExitWindowManager", "NoSuchClient",
           "client_message_type", "ClientMessage", "WindowManagerProperties",
           "compress", "WindowManager", "ReparentingWindowManager"]

log = logging.getLogger("manager")

class ExitWindowManager(Exception):
    """An event handler may raise an exception of this type in order to break
    out of the main event loop."""
    pass

class NoSuchClient(UnhandledEvent):
    """Raised to indicate that there is no currently-managed client with
    the given top-level window."""
    pass

# Client messages come in via ClientMessageEvent instances. Our handler
# for that event type will generate instances of more specific classes
# based on the "type" field of the events and dispatch those via the
# usual event dispatch mechanism. The following bit of machinery allows
# easy registration of those classes.
client_message_types = {}

def client_message_type(event_type):
    """A class decorator factory that registers a client message type."""
    def register_client_message_type(cls):
        client_message_types[event_type] = cls
        return cls
    return register_client_message_type

class ClientMessage(object):
    def __init__(self, window, format, data):
        self.window = window
        self.format = format
        self.data = data

@client_message_type("WM_CHANGE_STATE")
class WMChangeState(ClientMessage):
    """Sent by a client that would like its state changed (ICCCM §4.1.4)."""
    pass

@client_message_type("WM_EXIT")
class WMExit(ClientMessage):
    """Sent by a client that would like the window manager to shut down."""
    pass

class WindowManagerProperties(PropertyManager):
    """Track and manage properties on the root window."""
    pass

def compress(handler):
    """Decorator factory that wraps an event handler method with compression.
    That is, if the next event is available and of the same type as the current
    event, it is handled by simply returning and waiting for the next event.
    Otherwise, the normal handler is invoked as usual.

    Depends on the event interface defined used by the WindowManager class."""
    @wraps(handler)
    def compressed_handler(self, event):
        if isinstance(self.peek_next_event(), type(event)):
            return
        return handler(self, event)
    return compressed_handler

class WindowManager(EventHandler):
    """A window manager for one X screen.

    This class provides only the most basic window management functionality.
    Subclasses are expected to override or augment many of its methods and
    add their own management protocols."""

    root_event_mask = (EventMask.StructureNotify |
                       EventMask.SubstructureNotify |
                       EventMask.SubstructureRedirect |
                       EventMask.PropertyChange)

    property_class = WindowManagerProperties

    def __init__(self, display=None, screen=None, grab_buttons=GrabButtons()):
        self.conn = xcb.connect(display)
        self.screen_number = (screen
                              if screen is not None
                              else self.conn.pref_screen)
        self.screen = self.conn.get_setup().roots[self.screen_number]
        self.screen_geometry = window_geometry(self.conn, self.screen.root)
        self.grab_buttons = grab_buttons

        self.clients = {} # managed clients, indexed by window ID
        self.atoms = AtomCache(self.conn)
        self.colors = ColorCache(self.conn, self.screen.default_colormap)
        self.cursors = FontCursor(self.conn)
        self.fonts = FontCache(self.conn)
        self.keymap = KeyboardMap(self.conn)
        self.properties = self.property_class(self.conn,
                                              self.screen.root,
                                              self.atoms)
        self.next_event = None
        self.window_handlers = {}
        self.current_focus = None # unused here; see FocusPolicy
        self.init_graphics()

    def init_graphics(self):
        self.black_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.black_gc, self.screen.root,
                                GC.Foreground | GC.Background,
                                [self.screen.black_pixel,
                                 self.screen.white_pixel])

        self.white_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.white_gc, self.screen.root,
                                GC.Foreground | GC.Background,
                                [self.screen.white_pixel,
                                 self.screen.black_pixel])

        self.xor_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.xor_gc, self.screen.root,
                                (GC.Function |
                                 GC.Foreground |
                                 GC.LineStyle |
                                 GC.SubwindowMode |
                                 GC.GraphicsExposures),
                                [GX.xor,
                                 self.colors["#E0E0E0"],
                                 LineStyle.OnOffDash,
                                 SubwindowMode.ClipByChildren,
                                 False])

    def start(self):
        """Start the window manager. This method must only be called once."""
        # Make this client a window manager by selecting (at least)
        # SubstructureRedirect events on the root window. If another client
        # has already done so (i.e., there's already a window manager
        # running on this screen), the check will raise an exception.
        assert self.root_event_mask & EventMask.SubstructureRedirect, \
            "A window manager must select for SubstructureRedirect."
        try:
            self.conn.core.ChangeWindowAttributesChecked(self.screen.root,
                CW.EventMask, [self.root_event_mask]).check()
        except BadAccess:
            log.error("Can't select for SubstructureRedirect on screen %d; "
                      "is another window manager already running?",
                      self.screen_number)
            raise

        # Establish passive grabs for buttons on the root window. Subclasses
        # will add their own entries to the grab_buttons argument.
        for key, mask in self.grab_buttons.items():
            button, modifiers = key
            self.conn.core.GrabButtonChecked(False, self.screen.root, mask,
                                             GrabMode.Async, GrabMode.Async,
                                             self.screen.root, Cursor._None,
                                             button, modifiers).check()

        # Adopt any suitable top-level windows.
        self.adopt(self.conn.core.QueryTree(self.screen.root).reply().children)

        # Process events from the server.
        self.event_loop()

    def shutdown(self):
        """Unmanage all clients and disconnect from the server."""
        if self.conn:
            for client in self.clients.values():
                self.unmanage(client)
            self.conn.flush()
            self.conn.disconnect()
            self.conn = None

    def adopt(self, windows):
        """Adopt existing top-level windows."""
        for window in windows:
            log.debug("Adopting window 0x%x.", window)
            self.manage(window)

    def manage(self, window):
        """Manage a window and return the client instance."""
        try:
            attrs = self.conn.core.GetWindowAttributes(window).reply()
        except BadWindow:
            log.warning("Error fetching attributes for window 0x%x.", window)
            return None

        # Since we're not a compositing manager, we can simply ignore
        # override-redirect windows.
        if attrs.override_redirect:
            return None

        if window in self.clients:
            return self.clients[window]

        log.debug("Managing client window 0x%x.", window)

        client = self.clients[window] = ClientWindow(self.conn, window, self)
        self.place(client, client.geometry)
        client.decorator.decorate()
        client.decorator.unfocus()
        if attrs.map_state != MapState.Unmapped:
            self.normalize(client)
        return client

    def normalize(self, client):
        """Complete the transition of a client to the Normal state."""
        log.debug("Client window 0x%x entering Normal state.", client.window)
        client.properties.wm_state = WMState(WMState.NormalState)
        client.properties.request_properties()
        return client

    def withdraw(self, client):
        """Complete the transition of a client to the Withdrawn state."""
        log.debug("Client window 0x%x entering Withdrawn state.", client.window)
        client.properties.wm_state = WMState(WMState.WithdrawnState)
        client.decorator.undecorate()
        return client

    def iconify(self, client):
        """Complete the transition of a client to the Iconic state."""
        log.debug("Client window 0x%x entering Iconic state.", client.window)
        self.conn.core.UnmapWindow(client.window)
        client.properties.wm_state = WMState(WMState.IconicState)
        return client
            
    def unmanage(self, client):
        """Unmanage the given client."""
        log.debug("Unmanaging client window 0x%x.", client.window)
        client.decorator.undecorate()
        del client.properties.wm_state
        return self.clients.pop(client.window, None)

    def place(self, client, requested_geometry, resize=False):
        """Determine and configure a suitable geometry for the client frame
        (or top-level window, if there is no frame). This may, but need not,
        utilize the geometry the client requested."""
        old_geometry = client.geometry
        new_geometry = (client.resize(requested_geometry.size())
                        if resize
                        else client.moveresize(requested_geometry))
        if is_move_only(old_geometry, new_geometry):
            log.debug("Sending synthetic ConfigureNotify to client 0x%x.",
                      client.window)
            configure_notify(self.conn, client.window, *new_geometry)
        return new_geometry

    def constrain_position(self, client, position):
        """Compute and return a new position for the given client's frame
        based on the requested position."""
        return position

    def constrain_size(self, client, geometry, size=None, border_width=None,
                       gravity=None):
        """Constrain the client geometry using size hints and gravity.
        If a resize is requested, the caller should pass the client's current
        geometry and the requested size and border width; if a move with
        resize is requested, only the requested geometry is required.
        If the gravity argument is supplied, it overrides the win_gravity
        field of the size hints."""
        size_hints = client.properties.wm_normal_hints
        if size is None:
            size = geometry.size()
        if border_width is None:
            border_width = geometry.border_width
        if gravity is None:
            gravity = size_hints.win_gravity
        return geometry.resize(size_hints.constrain_window_size(size),
                               border_width,
                               gravity)

    def decorator(self, client):
        """Return a decorator for the given client."""
        return Decorator(self.conn, client)

    def event_loop(self):
        """The main event loop of the window manager."""
        # We use a select-based loop instead of XCB's wait_for_event because
        # (a) select handles signals correctly, and (b) wait_for_event blocks
        # the entire interpreter, not just the current thread.
        rlist = [self.conn.get_file_descriptor()]
        wlist = []
        xlist = []
        while True:
            while True:
                event = self.get_next_event()
                if event:
                    try:
                        self.handle_event(event)
                    except ExitWindowManager:
                        self.shutdown()
                        return
                else:
                    break
            self.conn.flush()
            select(rlist, wlist, xlist)

    def peek_next_event(self):
        if self.next_event is None:
            self.next_event = self.get_next_event()
        return self.next_event

    def get_next_event(self):
        if self.next_event:
            try:
                return self.next_event
            finally:
                self.next_event = None
        else:
            return self.conn.poll_for_event()

    def handle_event(self, event):
        handler = self.window_handlers.get(event_window(event), None)
        if handler:
            try:
                return handler.handle_event(event)
            except UnhandledEvent:
                pass
        return super(WindowManager, self).handle_event(event)

    def register_window_handler(self, window, handler):
        log.debug("Registering event handler for window 0x%x.", window)
        self.window_handlers[window] = handler

    def unhandled_event(self, event):
        log.debug("Ignoring unhandled %s on window 0x%x.",
                      event.__class__.__name__, event_window(event))

    def get_client(self, window, client_only=False):
        """Retrieve the client with the given top-level window, or raise an
        UnhandledEvent exception if there is no such client. Intended for
        use only in event handlers.

        The second (optional) argument controls whether the window must
        be a client window, or if it is permissible to return a client
        instance from its frame or a subwindow thereof."""
        try:
            return self.clients[window]
        except KeyError:
            raise NoSuchClient

    @handler(ConfigureRequestEvent)
    def handle_configure_request(self, event):
        """Handle a ConfigureWindow request from a top-level window.
        See ICCCM §4.1.5 for details."""
        if event.window in self.clients:
            client = self.clients[event.window]
            requested_geometry = Geometry(event.x, event.y,
                                          event.width, event.height,
                                          event.border_width)
            log.debug("Client 0x%x requested geometry %s.",
                      client.window, requested_geometry)
            resize = (event.value_mask & (ConfigWindow.X | ConfigWindow.Y) == 0)
            self.place(client, requested_geometry, resize)
        else:
            # Just grant the request.
            log.debug("Granting configure request for unmanaged window 0x%x.",
                      event.window)
            self.conn.core.ConfigureWindow(event.window, event.value_mask,
                                           select_values(event.value_mask,
                                                         [event.x,
                                                          event.y,
                                                          event.width,
                                                          event.height,
                                                          event.border_width,
                                                          event.sibling,
                                                          event.stack_mode]))
        self.conn.flush()

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        """Update our record of a client's geometry."""
        if event.override_redirect:
            raise UnhandledEvent(event)
        client = self.get_client(event.window)
        client.geometry = Geometry(event.x, event.y,
                                   event.width, event.height,
                                   event.border_width)
        log.debug("Noting geometry for client 0x%x as %s.",
                  client.window, client.geometry)

    @handler(MapRequestEvent)
    def handle_map_request(self, event):
        """Map a top-level window on behalf of a client."""
        client = self.manage(event.window)
        if (client.properties.wm_state == WMState.WithdrawnState and
            client.properties.wm_hints.initial_state == WMState.IconicState):
            # Withdrawn → Iconic state transition (ICCCM §4.1.4).
            self.iconify(client)
        else:
            self.conn.core.MapWindow(event.window)

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        """Note the mapping of a top-level window."""
        if event.override_redirect:
            raise UnhandledEvent(event)
        log.debug("Window 0x%x mapped.", event.window)
        try:
            self.normalize(self.get_client(event.window, True))
        except BadWindow:
            pass

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        """Note the unmapping of a top-level window."""
        if event.from_configure:
            raise UnhandledEvent(event)
        log.debug("Window 0x%x unmapped.", event.window)
        client = self.get_client(event.window, True)
        try:
            # See ICCCM §4.1.4.
            if is_synthetic_event(event):
                self.withdraw(client)
            else:
                self.iconify(client)
        except BadWindow:
            pass

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        """Note the destruction of a window."""
        log.debug("Window 0x%x destroyed.", event.window)
        # DestroyNotify is generated on all inferiors before being
        # generated on the window being destroyed. We'll wait until
        # the latter happens to remove any registered handlers.
        if event.window == event.event:
            if self.window_handlers.pop(event.window, None):
                log.debug("Removed event handler for window 0x%x.",
                          event.window)
        self.unmanage(self.get_client(event.window, True))

    @handler(MappingNotifyEvent)
    def handle_mapping_notify(self, event):
        """Note the change of an input device mapping and possibly request
        an update from the server."""
        if event.request == Mapping.Keyboard:
            try:
                log.debug("Refreshing keymap: %d codes starting at %d.",
                          event.count, event.first_keycode)
                self.keymap.refresh(event.first_keycode, event.count)
            except KeymapError as e:
                log.warning("Unable to refresh partial keymap: %s.", e)
                # Do a full refresh. If that fails, just bail out.
                self.keymap.refresh()

    @handler(PropertyNotifyEvent)
    def handle_property_notify(self, event):
        """Note the change of a window property."""
        properties = (self.properties
                      if event.window == self.screen.root
                      else self.get_client(event.window).properties)
        properties.property_changed(self.atoms.name(event.atom),
                                    event.state == Property.Delete)

    @handler(ClientMessageEvent)
    def handle_client_message(self, event):
        """Handle a client message event by dispatching a new ClientMessage
        instance."""
        try:
            event_type = self.atoms.name(event.type)
        except BadAtom:
            raise UnhandledEvent(event)
        log.debug("Received ClientMessage of type %s on window 0x%x.",
                  event_type, event.window)
        try:
            message_type = client_message_types[event_type]
        except KeyError:
            raise UnhandledEvent(event)
        self.handle_event(message_type(event.window, event.format, event.data))

    @handler(WMChangeState)
    def handle_wm_change_state(self, client_message):
        log.debug("Received change-state message for client window 0x%x (%d).",
                  client_message.window,
                  client_message.data.data32[0])
        if client_message.data.data32[0] == WMState.IconicState:
            self.iconify(self.get_client(client_message.window, True))
        else:
            raise UnhandledEvent

    @handler(WMExit)
    def handle_wm_exit(self, client_message):
        log.debug("Received exit message; shutting down.")
        raise ExitWindowManager

class ReparentingWindowManager(WindowManager):
    def __init__(self, *args, **kwargs):
        super(ReparentingWindowManager, self).__init__(*args, **kwargs)
        self.frames = {} # client frames, indexed by window ID
        self.parents = {self.screen.root: None}

    def manage(self, window):
        client = super(ReparentingWindowManager, self).manage(window)
        if client:
            self.frames[client.frame] = client
        return client

    def unmanage(self, client):
        if client.frame:
            self.frames.pop(client.frame, None)
        return super(ReparentingWindowManager, self).unmanage(client)

    def decorator(self, client):
        return FrameDecorator(self.conn, client)

    def normalize(self, client):
        if not client.reparenting:
            self.conn.core.MapWindow(client.frame)
            return super(ReparentingWindowManager, self).normalize(client)

    def withdraw(self, client):
        if not client.reparenting:
            frame = client.frame
            self.conn.core.UnmapWindow(client.frame)
            try:
                return super(ReparentingWindowManager, self).withdraw(client)
            finally:
                self.frames.pop(frame, None)

    def iconify(self, client):
        if not client.reparenting:
            self.conn.core.UnmapWindow(client.frame)
            return super(ReparentingWindowManager, self).iconify(client)

    def get_client(self, window, client_only=False):
        if not client_only:
            # Walk up the window hierarchy until we come to a frame or a root.
            w = window
            while w:
                try:
                    return self.frames[w]
                except KeyError:
                    w = self.parents.get(w, None)
        return super(ReparentingWindowManager, self).get_client(window,
                                                                client_only)

    @handler(CreateNotifyEvent)
    def handle_create_notify(self, event):
        self.parents[event.window] = event.parent
        raise UnhandledEvent(event)

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        self.parents.pop(event.window, None)
        raise UnhandledEvent(event)

    @handler(ReparentNotifyEvent)
    def handle_reparent_notify(self, event):
        self.parents[event.window] = event.parent
        if event.override_redirect:
            raise UnhandledEvent(event)
        client = self.get_client(event.window)
        if client.reparenting:
            assert issubclass(client.reparenting, ClientWindow)
            log.debug("Done reparenting window 0x%x.", client.window)
            client.__class__ = client.reparenting
            client.init(event.parent)

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        """Update our record of a frame's geometry."""
        if event.window in self.clients:
            client = self.clients[event.window]
            if not client.reparenting:
                client.geometry = Geometry(event.x, event.y,
                                           event.width, event.height,
                                           event.border_width)
                log.debug(u"Noting geometry for client window 0x%x as %s.",
                          client.window, client.geometry)
        elif event.window in self.frames:
            client = self.frames[event.window]
            client.frame_geometry = Geometry(event.x, event.y,
                                             event.width, event.height,
                                             event.border_width)
            log.debug(u"Noting frame geometry for client 0x%x as %s.",
                      client.window, client.frame_geometry)
