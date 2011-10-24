#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

from color import RGBi
from decorator import TitlebarConfig, TitleDecorator
from event import handler
from focus import FocusFollowsMouse, SloppyFocus, ClickToFocus
from manager import ReparentingWindowManager, compress
from moveresize import MoveResize
from raiselower import RaiseLower

class BaseWM(ReparentingWindowManager, MoveResize, RaiseLower):
    title_font = "fixed"

    def init_graphics(self):
        super(BaseWM, self).init_graphics()
        self.focused_title_config = TitlebarConfig(self,
                                                   RGBi(1.0, 1.0, 1.0),
                                                   RGBi(0.0, 0.0, 0.0),
                                                   self.title_font)
        self.unfocused_title_config = TitlebarConfig(self,
                                                     RGBi(0.0, 0.0, 0.0),
                                                     RGBi(0.75, 0.75, 0.75),
                                                     self.title_font)

    def decorator(self, client):
        return TitleDecorator(self.conn, client, 1,
                              self.focused_title_config,
                              self.unfocused_title_config)

if __name__ == "__main__":
    from optparse import OptionParser
    import logging
    import sys
    import xcb

    focus_modes = {"pointer": FocusFollowsMouse,
                   "sloppy": SloppyFocus,
                   "click": ClickToFocus}

    optparser = OptionParser("Usage: %prog [OPTIONS]")
    optparser.add_option("-D", "--debug", action="store_true", dest="debug",
                         help="show debugging messages")
    optparser.add_option("-V", "--verbose", action="store_true", dest="verbose",
                         help="be prolix, loquacious, and multiloquent")
    optparser.add_option("-v", "--version", action="store_true", dest="version",
                         help="output version information and exit")
    optparser.add_option("-d", "--display", dest="display",
                         help="the X server display name")
    optparser.add_option("-f", "--focus-mode", dest="focus_mode",
                         type="choice", choices=focus_modes.keys(),
                         default="pointer",
                         help='focus mode: pointer, sloppy, or click')
    optparser.add_option("-t", "--title-font", dest="title_font",
                         default="fixed",
                         help="client window title font")
    (options, args) = optparser.parse_args()
    if options.version:
        print "Python Window Manager version 0.0"
        sys.exit(0)
    logging.basicConfig(level=logging.DEBUG if options.debug else \
                              logging.INFO if options.verbose else \
                              logging.WARNING,
                        format="%(levelname)s: %(message)s")

    conn = xcb.connect(options.display)
    wm = type("WM",
              (focus_modes[options.focus_mode], BaseWM),
              dict(title_font=options.title_font))(conn)
    try:
        wm.event_loop()
    except KeyboardInterrupt:
        wm.shutdown()
