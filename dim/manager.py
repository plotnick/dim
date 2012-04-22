# -*- mode: Python; coding: utf-8 -*-

"""A window manager manages the children of the root window of a screen."""

from collections import deque
import logging
from functools import wraps
from os import execvp
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
from fontinfo import FontInfoCache
from geometry import *
from keymap import *
from properties import *
from xutil import *

__all__ = ["WindowManager"]

log = logging.getLogger("manager")

class ExitWindowManager(Exception):
    """An event handler may raise an exception of this type in order to break
    out of the main event loop."""
    pass

@client_message("_DIM_WM_EXIT")
class WMExit(ClientMessage):
    """Sent by a client that would like the window manager to shut down."""
    pass

class WindowManagerProperties(PropertyManager):
    """Track and manage properties on the root window."""
    wm_command = PropertyDescriptor("WM_COMMAND", WMCommand, [])

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
                 key_bindings={}, button_bindings={}):
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
        self.font_infos = FontInfoCache(self.conn, self.atoms)
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
        self.events = deque([])
        self.window_handlers = {}
        self.init_graphics()

    def get_crtc_info(self, screen):
        """Yield pairs of the form (CRTC, Geometry) for each CRTC connected
        to the given screen."""
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
        # Stash the argument vector used to start the manager in the
        # WM_COMMAND property on the root window. We'll assume that
        # the arguments are encoded according to the current locale.
        self.properties.wm_command = WMCommand(decode_argv())

        # Make this client a window manager by selecting (at least)
        # SubstructureRedirect events on the root window. If another client
        # has already done so (i.e., there's already a window manager
        # running on this screen), the check will raise an exception.
        event_mask = self.root_event_mask
        assert event_mask & EventMask.SubstructureRedirect, \
            "A window manager must select for SubstructureRedirect."
        try:
            self.conn.core.ChangeWindowAttributesChecked(self.screen.root,
                                                         CW.EventMask,
                                                         [event_mask]).check()
        except BadAccess:
            log.error("Can't select for SubstructureRedirect on screen %d; "
                      "is another window manager already running?",
                      self.screen_number)
            raise

        # Adopt any suitable top-level windows.
        self.adopt(self.conn.core.QueryTree(self.screen.root).reply().children)

        # Process events from the server.
        self.event_loop()

    def shutdown(self, *args):
        """Unmanage all clients and disconnect from the server. If args
        are supplied, treat them as a command with which to replace the
        current process."""
        log.info("Shutting down.")
        if self.conn:
            with grab_server(self.conn):
                for client in self.clients.values():
                    self.unmanage(client)
            self.conn.flush()
            self.conn.disconnect()
            self.conn = None
        assert not self.clients
        assert not self.frames
        if args:
            log.info("Executing command %s.", " ".join(args))
            argv = encode_argv(args)
            execvp(argv[0], argv)

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
            client = self.manage(window, True)
            if client and attrs.map_state != MapState.Unmapped:
                self.change_state(client,
                                  WMState.WithdrawnState,
                                  WMState.NormalState)

    def manage(self, window, adopted=False):
        """Manage a window and return a (possibly) new client instance."""
        try:
            return self.clients[window]
        except KeyError:
            pass

        log.debug("Managing client window 0x%x.", window)
        geometry = get_window_geometry(self.conn, window)
        if not geometry:
            return None
        client = Client(self.conn, self, window, self.place(geometry))
        self.frames[client.frame] = client
        self.key_bindings.establish_grabs(client.frame)
        self.button_bindings.establish_grabs(client.frame)
        self.clients[window] = client
        return client

    def unmanage(self, client, **kwargs):
        """Unmanage the given client."""
        log.debug("Unmanaging client window 0x%x.", client.window)
        del self.clients[client.window]
        try:
            del self.frames[client.frame]
        except KeyError:
            # The client could have been reparented.
            pass
        client.undecorate(**kwargs)
        return client

    def change_state(self, client, initial, final):
        """Transition a client from initial state to final state."""
        if final == WMState.IconicState:
            client.iconify()
        elif final == WMState.NormalState:
            client.normalize()
        elif final == WMState.WithdrawnState:
            client.withdraw()

    def place(self, geometry):
        """Determine a suitable geometry for a client window. This may, but
        need not, utilize the geometry the client requested."""
        return (geometry
                if geometry & self.screen_geometry
                else geometry.move(Position(0, 0)))

    def constrain_position(self, client, position):
        """Compute and return a new position for the given client's frame
        based on the requested position."""
        return position

    def constrain_size(self, client, geometry,
                       size=None, border_width=None, gravity=None):
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
    def current_crtc_geometry(self):
        """If RandR is available, return the geometry of the CRTC that
        currently contains the pointer. Otherwise, return the geometry
        of the root window."""
        if self.crtcs:
            pointer = query_pointer(self.conn, self.screen)
            for geometry in self.crtcs.values():
                if pointer in geometry:
                    return geometry
        return self.screen_geometry

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
                except ExitWindowManager as e:
                    self.shutdown(*e.args)
                    return
            select(rlist, wlist, xlist)

    def get_pending_events(self):
        """Push all available events onto the event queue and return the queue.
        Flushes all pending requests before returning."""
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
        """Handle an event from the server. If a handler is registered for
        the window the event was reported with respect to, dispatch the
        event to that handler as well."""
        handler = self.window_handlers.get(event_window(event), None)
        if handler:
            try:
                handler.handle_event(event)
            except UnhandledEvent:
                pass
        return super(WindowManager, self).handle_event(event)

    def register_window_handler(self, window, handler):
        log.debug("Registering event handler for window 0x%x.", window)
        self.window_handlers[window] = handler

    def unregister_window_handler(self, window):
        if self.window_handlers.pop(window, None):
            log.debug("Removed event handler for window 0x%x.", window)

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

    def update_for_changed_mapping(self):
        """Update for changed keyboard, modifier, or pointer mapping."""
        for client in self.clients.values():
            self.key_bindings.establish_grabs(client.frame)
            self.button_bindings.establish_grabs(client.frame)

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
        """Handle a ConfigureWindow request from a top-level window."""
        client = self.get_client(event.window, True)
        if client:
            attrs = ["x", "y", "width", "height", "border_width",
                     "sibling", "stack_mode"]
            arg_names = select_values(event.value_mask, attrs)
            arg_values = select_values(event.value_mask, [getattr(event, attr)
                                                          for attr in attrs])
            args = zip(arg_names, arg_values)
            log.debug("Client 0x%x requested %s.", client.window,
                      ", ".join(map(lambda arg: "%s=%s" % arg, args)))
            client.configure_request(**dict(args))
        else:
            log.debug("Granting configure request for unmanaged window 0x%x.",
                      event.window)
            value_list = select_values(event.value_mask,
                                       [int16(event.x),
                                        int16(event.y),
                                        card16(event.width),
                                        card16(event.height),
                                        card16(event.border_width),
                                        event.sibling,
                                        event.stack_mode])
            self.conn.core.ConfigureWindow(event.window,
                                           event.value_mask,
                                           value_list)

    @handler(CreateNotifyEvent)
    def handle_create_notify(self, event):
        self.parents[event.window] = event.parent

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        log.debug("Window 0x%x destroyed.", event.window)
        self.parents.pop(event.window, None)
        self.unregister_window_handler(event.window)

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
        if not client:
            return
        if (client.properties.wm_state == WMState.WithdrawnState and
            client.properties.wm_hints.initial_state == WMState.IconicState):
            # Withdrawn → Iconic state transition (ICCCM §4.1.4).
            self.change_state(client,
                              WMState.WithdrawnState,
                              WMState.IconicState)
        else:
            # {Withdrawn, Iconic} → Normal state transition (ICCCM §4.1.4).
            self.change_state(client,
                              client.properties.wm_state,
                              WMState.NormalState)

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
            self.change_state(client,
                              client.properties.wm_state,
                              WMState.WithdrawnState)
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
                self.keymap.refresh()
        elif event.request == Mapping.Modifier:
            log.debug("Refreshing modifier mapping.")
            self.modmap.refresh()
            self.keymap.scry_modifiers(self.modmap)
        self.update_for_changed_mapping()

    @handler(PropertyNotifyEvent)
    def handle_property_notify(self, event):
        """Note the change of a window property."""
        # Sometimes clients generate little storms of property updates.
        # When that happens, we'll ignore all but the last one available.
        def similar_event(other):
            return (type(other) == PropertyNotifyEvent and
                    other.window == event.window and
                    other.atom == event.atom and
                    other.state == event.state and
                    other.time >= event.time)
        while True:
            next_event = self.check_event(similar_event)
            if next_event:
                event = next_event
            else:
                break

        # Property notifications are dispatched to the appropriate property
        # manager. We have one for the root window, and one for each client.
        if event.window == self.screen.root:
            properties = self.properties
        else:
            client = self.get_client(event.window)
            if client:
                properties = client.properties
            else:
                log.debug("Got PropertyNotify for unmanaged window 0x%x (%s).",
                          event.window, self.atoms.name(event.atom))
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
        argv = []
        timestamp = client_message.data.data32[0]
        if (timestamp and
            compare_timestamps(self.properties.timestamps["WM_COMMAND"],
                               timestamp) <= 0):
            argv = self.properties.wm_command
        raise ExitWindowManager(*argv)

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
