# -*- mode: Python; coding: utf-8 -*-

"""A window manager manages the children of the root window of a screen."""

from collections import deque
import logging
from functools import wraps
from select import select

import xcb
from xcb.xproto import *
import xcb.randr

from atom import AtomCache
from bindings import KeyBindings, ButtonBindings
from client import Client
from color import ColorCache
from cursor import FontCursor
from decorator import Decorator
from event import StopPropagation, UnhandledEvent, EventHandler, handler
from font import FontCache
from geometry import *
from keymap import *
from properties import *
from xutil import *

__all__ = ["ExitWindowManager", "WindowManagerProperties", "compress",
           "WindowManager"]

log = logging.getLogger("manager")

class ExitWindowManager(Exception):
    """An event handler may raise an exception of this type in order to break
    out of the main event loop."""
    pass

@client_message("WM_EXIT")
class WMExit(ClientMessage):
    """Sent by a client that would like the window manager to shut down."""
    pass

class WindowManagerProperties(PropertyManager):
    """Track and manage properties on the root window."""
    pass

def compress(handler):
    """Decorator factory that wraps an event handler method with compression.
    That is, it ignores all but the last available event of the same type and
    on the same window as the original event.

    Depends on the event interface defined by the WindowManager class."""
    @wraps(handler)
    def compressed_handler(self, event):
        window = event_window(event)
        event_type = type(event)
        while True:
            next_event = self.check_typed_window_event(window, event_type)
            if next_event:
                event = next_event
            else:
                break
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

    def __init__(self, display=None, screen=None,
                 key_bindings={}, button_bindings={},
                 focus_new_windows=True):
        self.conn = xcb.connect(display)
        self.screen_number = (screen
                              if screen is not None
                              else self.conn.pref_screen)
        self.screen = self.conn.get_setup().roots[self.screen_number]
        self.screen_geometry = get_window_geometry(self.conn, self.screen.root)
        log.debug("Screen geometry: %s.", self.screen_geometry)

        self.randr = query_extension(self.conn, "RANDR", xcb.randr.key)
        if self.randr:
            self.randr.SelectInput(self.screen.root,
                                   xcb.randr.NotifyMask.CrtcChange)
            self.crtcs = dict(self.get_crtc_info(self.screen))
            log.debug("CRTC geometries: {%s}.",
                      ", ".join("0x%x: %s" % (crtc, geometry)
                                for crtc, geometry in self.crtcs.items()))
        else:
            self.crtcs = {}

        self.shape = query_extension(self.conn, "SHAPE", xcb.shape.key)

        self.clients = {} # managed clients, indexed by window ID
        self.frames = {} # client frames, indexed by window ID
        self.client_update = None # for move/resize
        self.parents = {self.screen.root: None}
        self.atoms = AtomCache(self.conn)
        self.colors = ColorCache(self.conn, self.screen.default_colormap)
        self.cursors = FontCursor(self.conn)
        self.fonts = FontCache(self.conn)
        self.modmap = ModifierMap(self.conn)
        self.keymap = KeyboardMap(self.conn, modmap=self.modmap)
        self.key_bindings = KeyBindings(key_bindings,
                                        self.keymap,
                                        self.modmap)
        self.button_bindings = ButtonBindings(button_bindings,
                                              self.keymap,
                                              self.modmap)
        self.properties = self.property_class(self.conn,
                                              self.screen.root,
                                              self.atoms)
        self.focus_new_windows = focus_new_windows
        self.events = deque([])
        self.window_handlers = {}
        self.init_graphics()

    def get_crtc_info(self, screen):
        """Yield pairs of the form (CRTC, Geometry) for each CRTC connected
        to the given screen, and select for change notification if available."""
        resources = self.randr.GetScreenResources(screen.root).reply()
        timestamp = resources.config_timestamp
        for crtc, cookie in [(crtc, self.randr.GetCrtcInfo(crtc, timestamp))
                             for crtc in resources.crtcs]:
            info = cookie.reply()
            if info.status or not info.mode:
                continue
            yield (crtc, Geometry(info.x, info.y, info.width, info.height, 0))

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
                                 self.colors["#808080"],
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
        assert not self.clients
        assert not self.frames

    def adopt(self, windows):
        """Adopt existing top-level windows."""
        for window in windows:
            try:
                attrs = self.conn.core.GetWindowAttributes(window).reply()
            except BadWindow:
                log.warning("Error fetching attributes for window 0x%x.",
                            window)
                continue
            if attrs.override_redirect:
                continue
            log.debug("Adopting window 0x%x.", window)
            client = self.manage(window)
            if attrs.map_state != MapState.Unmapped:
                client.normalize()

    def manage(self, window):
        """Manage a window and return the client instance."""
        if window in self.clients:
            return self.clients[window]

        log.debug("Managing client window 0x%x.", window)
        client = self.clients[window] = Client(self.conn, window, self)
        self.frames[client.frame] = client
        self.key_bindings.establish_grabs(client.frame)
        self.button_bindings.establish_grabs(client.frame)
        self.place(client, client.absolute_geometry)
        return client

    def unmanage(self, client, **kwargs):
        """Unmanage the given client."""
        log.debug("Unmanaging client window 0x%x.", client.window)
        del self.clients[client.window]
        del self.frames[client.frame]
        client.undecorate(**kwargs)
        return client

    def place(self, client, requested_geometry, resize_only=False):
        """Determine and configure a suitable geometry for the client's frame.
        This may, but need not, utilize the geometry the client requested."""
        if resize_only:
            client.resize(requested_geometry.size(),
                          requested_geometry.border_width)
        else:
            client.configure(requested_geometry)

    def constrain_position(self, client, position):
        """Compute and return a new position for the given client's frame
        based on the requested position."""
        return position

    def constrain_size(self, client, geometry, size=None, border_width=None,
                       gravity=None):
        """Constrain the client geometry using size hints and gravity.
        If a resize is requested, the caller should pass the client's current
        absolute geometry and the requested size and border width; if a move
        with resize is requested, only the requested geometry is required.
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

    @property
    def current_focus(self):
        """Return the client that currently has the input focus."""
        window = get_input_focus(self.conn, self.screen_number)
        while window:
            client = self.get_client(window)
            if client:
                return client
            window = self.conn.core.QueryTree(window).reply().parent

    def ensure_focus(self, client=None, time=Time.CurrentTime):
        """Make a best-effort attempt to ensure that some client has the
        input focus."""
        # Subclasses that deal with focus policy are expected to provide
        # proper implementations.
        if client and client.focus(time):
            return
        self.conn.core.SetInputFocus(InputFocus.PointerRoot,
                                     InputFocus.PointerRoot,
                                     time)

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
            while self.get_pending_events():
                try:
                    self.handle_event(self.events.popleft())
                except ExitWindowManager:
                    self.shutdown()
                    return
            select(rlist, wlist, xlist)

    def get_pending_events(self):
        while True:
            event = self.conn.poll_for_event()
            if event:
                self.events.append(event)
            else:
                break
        self.conn.flush()
        return self.events

    def put_back_event(self, event):
        """Push an event back onto the head of the event queue."""
        self.events.appendleft(event)

    def check_event(self, test):
        """Search the event queue for an event that satisfies the given test,
        which must be a function of one argument. If a match is found, it
        is removed from the queue and returned."""
        for i, event in enumerate(self.get_pending_events()):
            if test(event):
                del self.events[i]
                return event

    def check_typed_event(self, event_type):
        """Search the event queue for an event of the given type."""
        return self.check_event(lambda event: type(event) == event_type)

    def check_typed_window_event(self, window, event_type):
        """Search the event queue for an event on the given window and
        of the given type."""
        return self.check_event(lambda event: (type(event) == event_type and
                                               event_window(event) == window))

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
        window = event_window(event)
        log.debug("Ignoring unhandled %s%s.",
                  event.__class__.__name__,
                  (" on window 0x%x" % window) if window else "")

    def get_client(self, window, client_window_only=False):
        """Retrieve the client with the given top-level window, or None if
        there is no such client.

        The second (optional) argument controls whether the window must
        be a top-level client window, or if it is permissible to return
        a client instance from its frame or a subwindow thereof."""
        if not client_window_only:
            # Walk up the window hierarchy until we come to a frame or a root.
            w = window
            while w:
                try:
                    return self.frames[w]
                except KeyError:
                    w = self.parents.get(w, None)
        return self.clients.get(window, None)

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        if event.window == self.screen.root:
            # The root window size may change due to RandR.
            self.screen_geometry = Geometry(event.x, event.y,
                                            event.width, event.height,
                                            event.border_width)
            log.debug("Root window geometry now %s.", self.screen_geometry)

    @handler(ConfigureRequestEvent)
    def handle_configure_request(self, event,
                                 move_mask=ConfigWindow.X | ConfigWindow.Y):
        """Handle a ConfigureWindow request from a top-level window.
        See ICCCM §4.1.5 for details."""
        client = self.get_client(event.window, True)
        if client:
            client = self.clients[event.window]
            requested_geometry = Geometry(event.x, event.y,
                                          event.width, event.height,
                                          event.border_width)
            log.debug("Client 0x%x requested geometry %s/%d.",
                      client.window,
                      requested_geometry,
                      requested_geometry.border_width)
            self.place(client,
                       requested_geometry,
                       not (event.value_mask & move_mask))
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

    @handler(CreateNotifyEvent)
    def handle_create_notify(self, event):
        self.parents[event.window] = event.parent

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        log.debug("Window 0x%x destroyed.", event.window)
        self.parents.pop(event.window, None)

        # DestroyNotify is generated on all inferiors before being
        # generated on the window being destroyed. We'll wait until
        # the latter happens to remove any registered handlers.
        if event.window == event.event:
            if self.window_handlers.pop(event.window, None):
                log.debug("Removed event handler for window 0x%x.",
                          event.window)

        client = self.get_client(event.window, True)
        if client:
            self.unmanage(client, destroyed=True)

    @handler(ReparentNotifyEvent)
    def handle_reparent_notify(self, event):
        self.parents[event.window] = event.parent
        if event.override_redirect:
            return
        client = self.get_client(event.window, True)
        if client and client.frame != event.parent:
            log.debug("Window 0x%x reparented from its frame.", client.window)
            self.frames.pop(client.frame, None)

    @handler(MapRequestEvent)
    def handle_map_request(self, event):
        """Handle a request to map a top-level window on behalf of a client."""
        client = self.manage(event.window)
        if (client.properties.wm_state == WMState.WithdrawnState and
            client.properties.wm_hints.initial_state == WMState.IconicState):
            # Withdrawn → Iconic state transition (ICCCM §4.1.4).
            client.iconify()
        else:
            # {Withdrawn, Iconic} → Normal state transition (ICCCM §4.1.4).
            client.normalize()
            if self.focus_new_windows:
                log.debug("Ensuring focus of new window 0x%x.", client.window)
                self.ensure_focus(client)

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        """Note the unmapping of a top-level window."""
        if event.from_configure or event.window != event.event:
            return
        client = self.get_client(event.window, True)
        if not client:
            return
        log.debug("Client window 0x%x unmapped.", event.window)
        e = self.check_typed_window_event(event.window, DestroyNotifyEvent)
        if e:
            # Ignore the UnmapNotify.
            self.handle_event(e)
        else:
            # {Normal, Iconic} → Withdrawn state transition (ICCCM §4.1.4).
            client.withdraw()
            reparented = self.check_typed_window_event(event.window,
                                                       ReparentNotifyEvent)
            self.unmanage(client, destroyed=False, reparented=reparented)

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

        # Update our passive grabs for the new mapping.
        for client in self.clients.values():
            self.key_bindings.establish_grabs(client.window)
            self.button_bindings.establish_grabs(client.window)

    @handler(PropertyNotifyEvent)
    def handle_property_notify(self, event):
        """Note the change of a window property."""
        if event.window == self.screen.root:
            properties = self.properties
        else:
            client = self.get_client(event.window)
            if client:
                properties = client.properties
            else:
                return
        properties.property_changed(self.atoms.name(event.atom),
                                    event.state == Property.Delete,
                                    event.time)

    @handler((KeyPressEvent, KeyReleaseEvent))
    def handle_key_press(self, event):
        try:
            action = self.key_bindings[event]
        except KeyError:
            return
        action(self, event)

    @handler((ButtonPressEvent, ButtonReleaseEvent))
    def handle_button_press(self, event):
        try:
            action = self.button_bindings[event]
        except KeyError:
            return
        action(self, event)

    @handler(ClientMessageEvent)
    def handle_client_message(self, event):
        """Handle a client message event by dispatching a new ClientMessage
        instance."""
        try:
            event_type = self.atoms.name(event.type)
        except BadAtom:
            return
        log.debug("Received ClientMessage of type %s on window 0x%x.",
                  event_type, event.window)
        try:
            message_type = client_message_type(event_type)
        except KeyError:
            return
        self.handle_event(message_type(event.window, event.format, event.data))

    @handler(WMExit)
    def handle_wm_exit(self, client_message):
        log.debug("Received exit message; shutting down.")
        raise ExitWindowManager

    @handler(xcb.randr.NotifyEvent)
    def handle_randr_notify(self, event):
        if event.subCode == xcb.randr.Notify.CrtcChange:
            cc = event.u.cc
            if cc.window != self.screen.root:
                return
            if cc.mode:
                geometry = Geometry(cc.x, cc.y, cc.width, cc.height, 0)
                log.debug("CRTC 0x%x changed: %s.", cc.crtc, geometry)
                self.crtcs[cc.crtc] = geometry
            else:
                log.debug("CRTC 0x%x disabled.", cc.crtc)
                del self.crtcs[cc.crtc]
            
