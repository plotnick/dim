# -*- mode: Python; coding: utf-8 -*-

"""A window manager manages the children of the root window of a screen."""

from logging import basicConfig as logconfig, debug, info, warning, error
from select import select

import xcb
from xcb.xproto import *

from client import *
from event import *
from xutil import *

class WindowManager(EventHandler):
    """A window manager for one X screen.

    This class provides only the most basic window management functionality.
    Subclasses are expected to override or augment many of its methods and
    add their own management protocols."""

    ROOT_EVENT_MASK = (EventMask.StructureNotify |
                       EventMask.SubstructureNotify |
                       EventMask.SubstructureRedirect)

    def __init__(self, conn, screen=None):
        self.conn = conn
        self.clients = {} # managed clients, indexed by window ID
        self.atoms = AtomCache(conn)
        self.screen = conn.get_setup().roots[screen if screen is not None
                                                    else conn.pref_screen]

        # Make this client a window manager by selecting (at least)
        # SubstructureRedirect events on the root window. If another client
        # has already done so (i.e., there's already a window manager
        # running on this screen), the check will raise an exception.
        assert self.ROOT_EVENT_MASK & EventMask.SubstructureRedirect, \
            "A window manager must select for SubstructureRedirect."
        self.conn.core.ChangeWindowAttributesChecked(self.screen.root,
            CW.EventMask, [self.ROOT_EVENT_MASK]).check()

        # Adopt any suitable top-level windows.
        self.scan()

    def scan(self):
        """Scan for top-level windows to manage."""
        tree = self.conn.core.QueryTree(self.screen.root).reply()
        for child in tree.children:
            self.manage(child)

    def manage(self, window):
        """Manage a window and return the client instance."""
        # Since we're not a compositing manager, we can simply ignore
        # override-redirect windows.
        attrs = self.conn.core.GetWindowAttributes(window).reply()
        if attrs.override_redirect:
            return None

        if window in self.clients:
            return self.clients[window]
        else:
            debug("Managing window 0x%x" % window)

            # Add the client window to the server's save-set so that it gets
            # reparented when we die. The server automatically removes windows
            # from the save-set when they are destroyed.
            self.conn.core.ChangeSaveSet(SetMode.Insert, window)

            client = ClientWindow(window, self)
            self.clients[window] = client
            return client
            
    def unmanage(self, window):
        """Unmanage the client with the given top-level window."""
        debug("Unmanaging window 0x%x" % window)
        return self.clients.pop(window, None)

    def place(self, client, geometry):
        """Place a client window and return the geometry actually configured,
        which may or may not be influenced or determined by the requested
        geometry. The geometry recorded in the client instance will be updated
        only when we receive the corresponding ConfigureNotify event."""
        if geometry == client.geometry:
            return
        debug("Placing client 0x%x at %s" % (client.window, geometry))
        self.conn.core.ConfigureWindowChecked(client.window,
                                              (ConfigWindow.X |
                                               ConfigWindow.Y |
                                               ConfigWindow.Width |
                                               ConfigWindow.Height |
                                               ConfigWindow.BorderWidth),
                                              geometry).check()
        return geometry

    def event_loop(self):
        """The main event loop of the window manager."""
        self.conn.flush()

        # We use a select-based loop instead of XCB's wait_for_event because
        # (a) select handles signals correctly, and (b) wait_for_event blocks
        # the entire interpreter, not just the current thread.
        rlist = [self.conn.get_file_descriptor()]
        wlist = []
        xlist = []
        while True:
            while True:
                # Process all pending events from XCB.
                event = self.conn.poll_for_event()
                if event:
                    self.handle_event(event)
                else:
                    break
            select(rlist, wlist, xlist)

    def unhandled_event(self, event):
        debug("Ignoring unhandled %s" % event.__class__.__name__)
        pass

    @handler(ConfigureRequestEvent)
    def handle_configure_request(self, event):
        """Handle a ConfigureWindow request from a top-level window.
        See ICCCM §4.1.5 for details."""
        if event.window in self.clients:
            client = self.clients[event.window]
            requested_geometry = Geometry(event.x, event.y,
                                          event.width, event.height,
                                          event.border_width)
            debug("Client 0x%x requested geometry %s" %
                  (client.window, requested_geometry))
            old_geometry = client.geometry
            new_geometry = self.place(client, requested_geometry)
            if (new_geometry == old_geometry or
                is_move_only(old_geometry, new_geometry)):
                debug("Sending synthetic ConfigureNotify to client 0x%x" %
                      client.window)
                configure_notify(self.conn, client.window, *client.geometry)
        else:
            # Just grant the request.
            debug("Granting ConfigureWindow request for unmanaged window 0x%x" %
                  event.window)
            self.conn.core.ConfigureWindowChecked(event.window,
                event.value_mask,
                select_values(event.value_mask,
                              [event.x, event.y,
                               event.width, event.height,
                               event.border_width,
                               event.sibling,
                               event.stack_mode])).check()

    @handler(ConfigureNotifyEvent)
    def handle_configure_notify(self, event):
        """Update our record of a client's geometry."""
        if event.override_redirect:
            return
        if event.window in self.clients:
            client = self.clients[event.window]
            client.geometry = Geometry(event.x, event.y,
                                       event.width, event.height,
                                       event.border_width)
            debug("Noting geometry for client 0x%x as %s" %
                  (client.window, client.geometry))

    @handler(MapRequestEvent)
    def handle_map_request(self, event):
        """Map a top-level window."""
        debug("Granting MapRequest from client 0x%x" % event.window)
        self.conn.core.MapWindowChecked(event.window).check()
        client = self.manage(event.window)
        if client:
            client.wm_state = WMState.NormalState

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        """Note the withdraw of a top-level window and update the client's
        state appropriately."""
        if event.window in self.clients:
            # It's entirely possible that by the time we receive this
            # event, the window will already have been destroyed. But
            # that's fine; we'll just ignore any BadWindow errors.
            try:
                # See ICCCM §4.1.3.1, 4.1.4.
                self.clients[event.window].wm_state = WMState.WithdrawnState
            except BadWindow:
                pass

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        """Note the destruction of a top-level window, and unmanage the
        corresponding client."""
        self.unmanage(event.window)

if __name__ == "__main__":
    from optparse import OptionParser
    import logging
    import sys

    optparser = OptionParser("Usage: %prog [OPTIONS]")
    optparser.add_option("-D", "--debug", action="store_true", dest="debug",
                         help="show debugging messages")
    optparser.add_option("-V", "--verbose", action="store_true", dest="verbose",
                         help="be prolix, loquacious, and multiloquent")
    optparser.add_option("-v", "--version", action="store_true", dest="version",
                         help="output version information and exit")
    optparser.add_option("-d", "--display", dest="display",
                         help="the X server display name")
    (options, args) = optparser.parse_args()
    if options.version:
        print "Python Window Manager version 0.0"
        sys.exit(0)
    logconfig(level=logging.DEBUG if options.debug else \
                    logging.INFO if options.verbose else \
                    logging.WARNING,
              format="%(levelname)s: %(message)s")

    manager = WindowManager(xcb.connect(options.display))
    manager.event_loop()
