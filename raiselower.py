# -*- mode: Python; coding: utf-8 -*-

import logging

from xcb.xproto import *

from event import handler
from manager import WindowManager
from xutil import GrabButtons

__all__ = ["RaiseLower"]

log = logging.getLogger("raiselower")

class RaiseLower(WindowManager):
    __grab_event_mask = EventMask.ButtonPress

    def __init__(self, display=None, screen=None,
                 raise_lower_mods=ModMask.Shift | ModMask._1,
                 raise_button=1, lower_button=3,
                 grab_buttons=GrabButtons(),
                 **kwargs):
        assert raise_lower_mods != 0, "Invalid modifiers for raise/lower"
        assert raise_button != lower_button, \
            "Can't have raise and lower on the same button"
        self.__modifiers = raise_lower_mods
        self.__buttons = {
            raise_button: lambda client: client.restack(StackMode.TopIf),
            lower_button: lambda client: client.restack(StackMode.BottomIf)
        }

        kwargs.update(grab_buttons=grab_buttons.merge({
            (raise_button, raise_lower_mods): self.__grab_event_mask,
            (lower_button, raise_lower_mods): self.__grab_event_mask
        }))
        super(RaiseLower, self).__init__(display, screen, **kwargs)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        modifiers = event.state & 0xff
        client = self.get_client(event.child)
        if (not client or
            modifiers != self.__modifiers or
            button not in self.__buttons):
            return
        self.__buttons[button](client)
