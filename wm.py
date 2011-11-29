#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

import re

from xcb.xproto import *

from color import RGBi
from decorator import TitlebarConfig, TitlebarDecorator
from event import handler
from focus import SloppyFocus, ClickToFocus
from manager import ReparentingWindowManager, compress
from moveresize import MoveResize
from properties import AtomList
from raiselower import RaiseLower
from tags import TagManager

class BaseWM(TagManager, ReparentingWindowManager, MoveResize, RaiseLower):
    title_font = "fixed"

    def init_graphics(self):
        super(BaseWM, self).init_graphics()
        self.focused_config = TitlebarConfig(self,
                                             RGBi(1.0, 1.0, 1.0),
                                             RGBi(0.0, 0.0, 0.0),
                                             self.title_font)
        self.unfocused_config = TitlebarConfig(self,
                                               RGBi(0.0, 0.0, 0.0),
                                               RGBi(0.75, 0.75, 0.75),
                                               self.title_font)

    def decorator(self, client):
        def tags_changed(value, sep=re.compile(r",\s*")):
            def atom(name):
                # ICCCM note 1: "The comment in the protocol specification
                # for InternAtom that ISO Latin-1 encoding should be used
                # is in the nature of a convention; the server treats the
                # string as a byte sequence." We'll ignore that convention
                # here and always use UTF-8 for tag names.
                return self.atoms[name.encode("UTF-8", "replace")]
            client.dim_tags = AtomList(map(atom, sep.split(value)))
        def change_tags(event):
            def name(atom):
                return self.atoms.name(atom, "UTF-8", "replace")
            tags = map(name, client.dim_tags)
            decorator.read_from_user("Tags: ", ", ".join(tags), tags_changed)
        decorator = TitlebarDecorator(self.conn, client,
                                      focused_config=self.focused_config,
                                      unfocused_config=self.unfocused_config,
                                      button_press_handlers={2: change_tags})
        return decorator

if __name__ == "__main__":
    from optparse import OptionParser
    import logging
    import sys
    import xcb

    focus_modes = {"sloppy": SloppyFocus, "click": ClickToFocus}

    optparser = OptionParser("Usage: %prog [OPTIONS]")
    optparser.add_option("-D", "--debug", action="store_true", dest="debug",
                         help="show debugging messages")
    optparser.add_option("-V", "--verbose", action="store_true", dest="verbose",
                         help="be prolix, loquacious, and multiloquent")
    optparser.add_option("-L", "--log", action="append", dest="log",
                         help="enable logging for the specified module")
    optparser.add_option("-v", "--version", action="store_true", dest="version",
                         help="output version information and exit")
    optparser.add_option("-d", "--display", dest="display",
                         help="the X server display name")
    optparser.add_option("-f", "--focus-mode", dest="focus_mode",
                         type="choice", choices=focus_modes.keys(),
                         default="sloppy",
                         help="focus mode: sloppy or click")
    optparser.add_option("-t", "--title-font", dest="title_font",
                         default="fixed",
                         help="client window title font")
    (options, args) = optparser.parse_args()

    if options.version:
        print "Python Window Manager version 0.0"
        sys.exit(0)

    tty = logging.StreamHandler()
    tty.setFormatter(logging.Formatter("%(levelname)s: %(name)s: %(message)s"))
    logging.getLogger("").addHandler(tty)
    log_level = (logging.DEBUG if options.debug else
                 logging.INFO if options.verbose else
                 logging.WARNING)
    for name in ([""] if options.log is None or "*" in options.log
                 else options.log):
        logging.getLogger(name).setLevel(log_level)

    log = logging.getLogger("wm")
    log.debug("Using %s focus policy.", options.focus_mode)
    wm = type("WM",
              (focus_modes[options.focus_mode], BaseWM),
              dict(title_font=options.title_font))(options.display)
    try:
        wm.start()
    except KeyboardInterrupt:
        log.info("Interrupt caught; shutting down.")
        wm.shutdown()
