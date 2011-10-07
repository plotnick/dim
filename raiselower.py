# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error

import xcb
from xcb.xproto import *

from client import ClientWindow
from event import handler, EventHandler, UnhandledEvent
from manager import WindowManager, GrabButtons

class RaiseLower(WindowManager):
    __grab_event_mask = EventMask.ButtonPress

    def __init__(self, conn, screen=None,
                 raise_lower_mods=ModMask.Shift | ModMask._1,
                 raise_button=1, lower_button=3,
                 grab_buttons=GrabButtons(),
                 **kwargs):
        assert raise_lower_mods != 0, "Invalid modifiers for raise/lower"
        assert raise_button != lower_button, \
            "Can't have raise and lower on the same button"
        self.raise_lower_mods = raise_lower_mods
        self.raise_button = raise_button
        self.lower_button = lower_button

        kwargs.update(grab_buttons=grab_buttons.merge({
            (self.raise_button, self.raise_lower_mods): self.__grab_event_mask,
            (self.lower_button, self.raise_lower_mods): self.__grab_event_mask
        }))
        super(RaiseLower, self).__init__(conn, screen, **kwargs)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        modifiers = event.state & 0xff
        window = event.child

        if not window or \
                modifiers != self.raise_lower_mods or \
                button not in (self.raise_button, self.lower_button):
            raise UnhandledEvent(event)

        try:
            client = self.clients[window]
        except KeyError:
            raise UnhandledEvent(event)

        if button == self.raise_button:
            client.restack(StackMode.TopIf)
        elif button == self.lower_button:
            client.restack(StackMode.BottomIf)
        raise UnhandledEvent(event)
