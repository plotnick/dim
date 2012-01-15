#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

from collections import deque
from os import fork, execv
import re
import sys

from xcb.xproto import *

from color import RGBi
from daemon import daemon
from decorator import TitlebarConfig, TitlebarDecorator
from event import handler
from focus import SloppyFocus, ClickToFocus
from keysym import *
from minibuffer import *
from moveresize import MoveResize
from properties import AtomList
from raiselower import RaiseLower
from tags import *

def spawn(command):
    """Execute command (a string) in the background via a shell."""
    if fork():
        return
    daemon(True, True)
    execv("/bin/sh",
          ["/bin/sh", "-c", command.encode(sys.stdin.encoding, "ignore")])

class BaseWM(TagManager, MoveResize, RaiseLower):
    title_font = "fixed"
    minibuffer_font = "10x20"

    def init_graphics(self):
        super(BaseWM, self).init_graphics()
        self.focused_config = TitlebarConfig(self,
                                             fg_color=RGBi(1.0, 1.0, 1.0),
                                             bg_color=RGBi(0.0, 0.0, 0.0),
                                             font=self.title_font)
        self.unfocused_config = TitlebarConfig(self,
                                               fg_color=RGBi(0.0, 0.0, 0.0),
                                               bg_color=RGBi(0.75, 0.75, 0.75),
                                               font=self.title_font)
        self.minibuffer_config = MinibufferConfig(self,
                                                  fg_color=RGBi(0.0, 0.0, 0.0),
                                                  bg_color=RGBi(1.0, 1.0, 1.0),
                                                  font=self.minibuffer_font)

    def decorator(self, client):
        def tags_changed(value, sep=re.compile(r",\s*")):
            def atom(name):
                # ICCCM note 1: "The comment in the protocol specification
                # for InternAtom that ISO Latin-1 encoding should be used
                # is in the nature of a convention; the server treats the
                # string as a byte sequence." We'll ignore that convention
                # here and always use UTF-8 for tag names.
                return self.atoms[name.encode("UTF-8", "replace")]
            client.properties.dim_tags = AtomList(map(atom, sep.split(value)))
        def change_tags(widget, event):
            def name(atom):
                return self.atoms.name(atom, "UTF-8", "replace")
            tags = map(name, client.properties.dim_tags)
            decorator.read_from_user("Tags: ",
                                     ", ".join(tags),
                                     tags_changed,
                                     time=event.time)
        decorator = TitlebarDecorator(self.conn, client,
                                      focused_config=self.focused_config,
                                      unfocused_config=self.unfocused_config,
                                      button_bindings={2: change_tags})
        return decorator

    def shell_command(self, event):
        def execute(command):
            spawn(command)
            dismiss()
        def dismiss():
            minibuffer.destroy()
        minibuffer = Minibuffer(manager=self,
                                parent=self.screen.root,
                                config=self.minibuffer_config,
                                prompt="Shell command: ",
                                commit=execute,
                                rollback=dismiss)
        minibuffer.map(event.time)

    def tagset(self, event):
        def execute(spec):
            try:
                expr = parse_tagset_spec(spec)
            except SpecSyntaxError as err:
                log.warning("Syntax error in tagset specification '%s': %s.",
                            spec, err.args[0])
            else:
                send_tagset_expr(self.conn, expr,
                                 screen=self.screen_number,
                                 atoms=self.atoms)
            dismiss()
        def dismiss():
            minibuffer.destroy()
        minibuffer = Minibuffer(manager=self,
                                parent=self.screen.root,
                                config=self.minibuffer_config,
                                prompt="Tagset: ",
                                commit=execute,
                                rollback=dismiss)
        minibuffer.map(event.time)

def terminal(*args):
    spawn("xterm")

key_bindings = {
    ("control", "meta", XK_Return): terminal,
    ("control", "meta", XK_Tab): BaseWM.tagset,
    ("control", "meta", XK_space): BaseWM.shell_command
}

button_bindings = {
    ("meta", 1): MoveResize.move_window,
    ("meta", 3): MoveResize.resize_window,
    ("shift", "meta", 1): RaiseLower.raise_window,
    ("shift", "meta", 3): RaiseLower.lower_window,
}

if __name__ == "__main__":
    from optparse import OptionParser
    import logging
    import pdb
    import sys
    import traceback
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
    try:
        wm_class = type("WM",
                        (focus_modes[options.focus_mode], BaseWM),
                        dict(title_font=options.title_font))
        wm = wm_class(options.display,
                      key_bindings=key_bindings,
                      button_bindings=button_bindings)
        wm.start()
    except KeyboardInterrupt:
        log.info("Interrupt caught; shutting down.")
        wm.shutdown()
    except:
        conn = xcb.connect()
        conn.core.SetInputFocus(InputFocus.PointerRoot,
                                InputFocus.PointerRoot,
                                Time.CurrentTime)
        conn.flush()

        traceback.print_exc()
        pdb.post_mortem()
