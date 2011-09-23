# -*- mode: Python; coding: utf-8 -*-

"""A window manager manages the children of the root window of a screen."""

from logging import basicConfig as logconfig, debug, info, warning, error

import xcb
from xcb.xproto import *

from client import *
from event import *
from xutil import *

class WindowManager(EventHandler):
    def __init__(self, conn, screen=None):
        self.conn = conn
        self.clients = {} # managed clients, indexed by window ID
        self.atoms = AtomCache(conn)
        self.screen = conn.get_setup().roots[screen if screen is not None
                                                    else conn.pref_screen]

        # Make this client a window manager by selecting SubstructureRedirect
        # events on the root window. If another client has already done so
        # (i.e., there's already a window manager running on this screen),
        # the check will raise an exception.
        self.conn.core.ChangeWindowAttributesChecked(self.screen.root,
            CW.EventMask,
            [EventMask.StructureNotify |
             EventMask.SubstructureNotify |
             EventMask.SubstructureRedirect]).check()

        # Adopt any extant top-level windows.
        tree = self.conn.core.QueryTree(self.screen.root).reply()
        for child in tree.children:
            self.manage(child)

    def manage(self, window):
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
        debug("Unmanaging window 0x%x" % window)
        return self.clients.pop(window, None)

    def event_loop(self):
        while True:
            self.handle_event(self.conn.wait_for_event())

    def unhandled_event(self, event):
        debug("Ignoring unhandled %s" % event.__class__.__name__)
        pass

    @handler(ConfigureRequestEvent)
    def handle_configure_request(self, event):
        if event.window not in self.clients:
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

    @handler(MapRequestEvent)
    def handle_map_request(self, event):
        if self.manage(event.window):
            debug("Granting MapRequest from client 0x%x" % event.window)
            self.conn.core.MapWindowChecked(event.window).check()
            self.conn.flush()

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
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
