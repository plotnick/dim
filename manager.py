"""A manager is a concrete implementation of a window management strategy for
a particular screen."""

from logging import basicConfig as logconfig, debug, info, warning, error

import xcb
from xcb.xproto import *

from client import ClientWindow
from xutil import *

class Manager(object):
    def __init__(self, conn, screen=None):
        self.conn = conn
        self.managed = {} # managed clients, indexed by window ID
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

        # Add the client window to the server's save-set so that it gets
        # reparented when we die. The server automatically removes windows
        # from the save-set when they are destroyed.
        self.conn.core.ChangeSaveSet(SetMode.Insert, window)

        if window not in self.managed:
            info('Managing window 0x%x' % window)
            client = ClientWindow(window, self)
            self.managed[window] = client
            return client
            
    def unmanage(self, window):
        return self.managed.pop(window, None)

    def event_loop(self):
        while True:
            event = self.conn.wait_for_event()
            dump_event(event)
            if isinstance(event, MapRequestEvent):
                if event.window in self.managed or self.manage(event.window):
                    self.conn.core.MapWindowChecked(event.window).check()
                    self.conn.flush()
            elif isinstance(event, ConfigureRequestEvent):
                if event.window not in self.managed:
                    # Just grant the request.
                    self.conn.core.ConfigureWindowChecked(event.window,
                        event.value_mask,
                        select_values(event.value_mask,
                                      [event.x, event.y,
                                       event.width, event.height,
                                       event.border_width,
                                       event.sibling,
                                       event.stack_mode])).check()

def dump_event(event):
    print event.__class__.__name__
    for attr, value in event.__dict__.items():
        print "  %s: %s" % (attr, value)

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

    manager = Manager(xcb.connect(options.display))
    manager.event_loop()
