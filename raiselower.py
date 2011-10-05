# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error

import xcb
from xcb.xproto import *

from client import ClientWindow
from event import handler, EventHandler, UnhandledEvent
from manager import WindowManager

class RaiseLower(WindowManager):
    GRAB_EVENT_MASK = EventMask.ButtonPress | EventMask.ButtonRelease

    def __init__(self, conn, screen=None,
                 modifier=ModMask._1,
                 raise_button=1,
                 lower_button=3):
        assert modifier != 0, "Invalid modifier key for raise/lower"
        assert raise_button != lower_button, \
            "Can't have raise and lower on the same button"

        super(RaiseLower, self).__init__(conn, screen)

        self.raise_button = raise_button
        self.lower_button = lower_button

        for button in (raise_button, lower_button):
            self.conn.core.GrabButtonChecked(False, self.screen.root,
                                             self.GRAB_EVENT_MASK,
                                             GrabMode.Async, GrabMode.Async,
                                             self.screen.root, Cursor._None,
                                             button, modifier).check()

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        if not event.child:
            debug("Ignoring button %d press in root window" % button)
            raise UnhandledEvent(event)
        try:
            client = self.clients[event.child]
        except KeyError:
            raise UnhandledEvent(event)

        if button == self.raise_button:
            client.restack(StackMode.TopIf)
        elif button == self.lower_button:
            client.restack(StackMode.BottomIf)
        else:
            raise UnhandledEvent(event)
