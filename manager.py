# -*- mode: Python; coding: utf-8 -*-

"""A window manager manages the children of the root window of a screen."""

from logging import debug, info, warning, error
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

__all__ = ["ExitWindowManager", "NoSuchClient", "compress",
           "WindowManager", "ReparentingWindowManager"]

class ExitWindowManager(Exception):
    """An event handler may raise an exception of this type in order to break
    out of the main event loop."""
    pass

class NoSuchClient(UnhandledEvent):
    """Raised to indicate that there is no client currentlly being managed
    with the given top-level window."""
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
                       EventMask.SubstructureRedirect)

    def __init__(self, display=None, screen=None, grab_buttons=GrabButtons()):
        self.conn = xcb.connect(display)
        if screen is None:
            screen = self.conn.pref_screen
        self.screen = self.conn.get_setup().roots[screen]
        self.grab_buttons = grab_buttons

        self.clients = {} # managed clients, indexed by window ID
        self.atoms = AtomCache(self.conn)
        self.colors = ColorCache(self.conn, self.screen.default_colormap)
        self.cursors = FontCursor(self.conn)
        self.fonts = FontCache(self.conn)
        self.keymap = KeyboardMap(self.conn)
        self.next_event = None
        self.subwindow_handlers = {}
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

    def start(self):
        """Start the window manager. This method must only be called once."""
        # Make this client a window manager by selecting (at least)
        # SubstructureRedirect events on the root window. If another client
        # has already done so (i.e., there's already a window manager
        # running on this screen), the check will raise an exception.
        assert self.root_event_mask & EventMask.SubstructureRedirect, \
            "A window manager must select for SubstructureRedirect."
        self.conn.core.ChangeWindowAttributesChecked(self.screen.root,
            CW.EventMask, [self.root_event_mask]).check()

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
            self.manage(window)

    def manage(self, window):
        """Manage a window and return the client instance."""
        try:
            attrs = self.conn.core.GetWindowAttributes(window).reply()
        except BadWindow:
            warning("Error fetching attributes for window 0x%x." % window)
            return None

        # Since we're not a compositing manager, we can simply ignore
        # override-redirect windows.
        if attrs.override_redirect:
            return None

        if window in self.clients:
            return self.clients[window]

        debug("Managing window 0x%x." % window)

        client = self.clients[window] = ClientWindow(self.conn, window, self)
        client.decorator.decorate()
        client.decorator.unfocus()

        if attrs.map_state != MapState.Unmapped:
            self.normalize(client)

        return client

    def normalize(self, client):
        """Complete the transition of a client from Withdrawn → Normal state."""
        debug("Client window 0x%x entering Normal state." % client.window)
        client.wm_state = WMState(WMState.NormalState)
        client.request_properties()
        return client

    def withdraw(self, client):
        """Complete the transition of a client to the Withdrawn state."""
        debug("Client window 0x%x entering Withdrawn state." % client.window)
        client.wm_state = WMState(WMState.WithdrawnState)
        client.decorator.undecorate()
        return client
            
    def unmanage(self, client):
        """Unmanage the given client."""
        debug("Unmanaging client window 0x%x." % client.window)
        client.decorator.undecorate()
        return self.clients.pop(client.window)

    def place(self, client, geometry):
        """Place a client window and return the geometry actually configured,
        which may or may not be influenced or determined by the requested
        geometry. The geometry recorded in the client instance will be updated
        only when we receive the corresponding ConfigureNotify event."""
        if geometry != client.geometry:
            debug("Placing client 0x%x at %s." % (client.window, geometry))
            self.conn.core.ConfigureWindow(client.window,
                                           (ConfigWindow.X |
                                            ConfigWindow.Y |
                                            ConfigWindow.Width |
                                            ConfigWindow.Height |
                                            ConfigWindow.BorderWidth),
                                           (int16(geometry.x),
                                            int16(geometry.y),
                                            int16(geometry.width),
                                            int16(geometry.height),
                                            int16(geometry.border_width)))
        return geometry

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

    def get_client(self, window, client_only=False):
        """Retrieve the client with the given top-level window, or raise an
        UnhandledEvent exception if there is no such client. Intended for
        use only in event handlers.

        The second (optional) argument controls whether the window must
        be a client window, or if it is permissible to return a client
        instance from its frame. This is used only in subclasses that
        support reparenting."""
        try:
            return self.clients[window]
        except KeyError:
            raise NoSuchClient

    def register_subwindow_handler(self, event_class, window, handler):
        debug("Registering %s handler for subwindow 0x%x." %
              (event_class.__name__, window))
        if event_class not in self.subwindow_handlers:
            self.subwindow_handlers[event_class] = {}
        self.subwindow_handlers[event_class][window] = handler

    def unhandled_event(self, event):
        def event_window(event):
            # This is totally wrong.
            return event.event if hasattr(event, "event") else event.window
        window = event_window(event)
        event_class = type(event)
        if event_class in self.subwindow_handlers:
            if window in self.subwindow_handlers[event_class]:
                self.subwindow_handlers[event_class][window](event)
        else:
            debug("Ignoring unhandled %s on window 0x%x." %
                  (event.__class__.__name__, window))

    @handler(ConfigureRequestEvent)
    def handle_configure_request(self, event):
        """Handle a ConfigureWindow request from a top-level window.
        See ICCCM §4.1.5 for details."""
        if event.window in self.clients:
            client = self.clients[event.window]
            requested_geometry = Geometry(event.x, event.y,
                                          event.width, event.height,
                                          event.border_width)
            debug("Client 0x%x requested geometry %s." %
                  (client.window, requested_geometry))
            old_geometry = client.geometry
            new_geometry = self.place(client, requested_geometry)
            if (new_geometry == old_geometry or
                is_move_only(old_geometry, new_geometry)):
                debug("Sending synthetic ConfigureNotify to client 0x%x." %
                      client.window)
                configure_notify(self.conn, client.window, *new_geometry)
        else:
            # Just grant the request.
            debug("Granting ConfigureWindow request for unmanaged window 0x%x." %
                  event.window)
            self.conn.core.ConfigureWindow(event.window, event.value_mask,
                select_values(event.value_mask,
                              [int16(event.x),
                               int16(event.y),
                               int16(event.width),
                               int16(event.height),
                               int16(event.border_width),
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
        debug("Noting geometry for client 0x%x as %s." %
              (client.window, client.geometry))

    @handler(MapRequestEvent)
    def handle_map_request(self, event):
        """Map a top-level window on behalf of a client."""
        debug("Granting MapRequest for client 0x%x." % event.window)
        client = self.manage(event.window)
        self.conn.core.MapWindow(event.window)

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        """Note the mapping of a top-level window."""
        if event.override_redirect:
            raise UnhandledEvent(event)
        debug("Window 0x%x mapped." % event.window)
        try:
            self.normalize(self.get_client(event.window, True))
        except BadWindow:
            pass

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        """Note the unmapping of a top-level window."""
        if event.from_configure:
            raise UnhandledEvent(event)
        debug("Window 0x%x unmapped." % event.window)
        try:
            self.withdraw(self.get_client(event.window, True))
        except BadWindow:
            pass

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        """Note the destruction of a managed window."""
        for event_class, handlers in self.subwindow_handlers.items():
            if handlers.pop(event.window, None):
                debug("Removed %s handler for subwindow 0x%x." %
                      (event_class.__name__, event.window))
        self.unmanage(self.get_client(event.window))

    @handler(MappingNotifyEvent)
    def handle_mapping_notify(self, event):
        """Note the change of an input device mapping and possibly request
        an update from the server."""
        if event.request == Mapping.Keyboard:
            try:
                debug("Refreshing keymap: %d codes starting at %d." %
                      (event.count, event.first_keycode))
                self.keymap.refresh(event.first_keycode, event.count)
            except KeymapError as e:
                warning("Unable to refresh partial keymap: %s." % e)
                # Do a full refresh. If that fails, just bail out.
                self.keymap.refresh()

    @handler(PropertyNotifyEvent)
    def handle_property_notify(self, event):
        """Note the change of a window property."""
        self.get_client(event.window).property_changed(event.atom)

    @handler(ClientMessageEvent)
    def handle_client_message(self, event):
        if event.window != self.screen.root:
            debug("Ignoring client message to non-root window 0x%x." %
                  event.window)
        if event.type == self.atoms["WM_EXIT"]:
            info("Received exit message; shutting down.")
            raise ExitWindowManager

class ReparentingWindowManager(WindowManager):
    def __init__(self, *args, **kwargs):
        self.frames = {} # client frames, indexed by window ID
        super(ReparentingWindowManager, self).__init__(*args, **kwargs)

    def manage(self, window):
        client = super(ReparentingWindowManager, self).manage(window)
        if client:
            self.frames[client.frame] = client
        return client

    def unmanage(self, client):
        self.frames.pop(client.frame)
        return super(ReparentingWindowManager, self).unmanage(client)

    def decorator(self, client):
        return FrameDecorator(self.conn, client)

    def normalize(self, client):
        if not client.reparenting:
            self.conn.core.MapWindow(client.frame)
            return super(ReparentingWindowManager, self).normalize(client)

    def withdraw(self, client):
        if not client.reparenting:
            self.conn.core.UnmapWindow(client.frame)
            return super(ReparentingWindowManager, self).withdraw(client)

    def get_client(self, window, client_only=False):
        if window in self.clients:
            return self.clients[window]
        elif not client_only and window in self.frames:
            return self.frames[window]
        else:
            raise UnhandledEvent

    @handler(ReparentNotifyEvent)
    def handle_reparent_notify(self, event):
        if event.override_redirect:
            raise UnhandledEvent(event)
        client = self.get_client(event.window)
        if client.reparenting:
            debug("Done reparenting window 0x%x." % client.window)
            client.reparenting = False
            client._geometry = None

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        """Update our record of a client's frame's geometry. Once reparented,
        the client window's geometry is essentially useless."""
        try:
            client = self.frames[event.window]
        except KeyError:
            return
        client.geometry = Geometry(event.x, event.y,
                                   event.width, event.height,
                                   event.border_width)
        debug("Noting frame geometry for client 0x%x as %s." %
              (client.window, client.geometry))
