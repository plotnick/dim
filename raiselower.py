# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

from manager import WindowManager

__all__ = ["RaiseLower"]

class RaiseLower(WindowManager):
    """A window manager mixin that provides window raise & lower commands."""

    def raise_window(self, event):
        client = self.get_client(event.event)
        if client:
            client.restack(StackMode.TopIf)

    def lower_window(self, event):
        client = self.get_client(event.event)
        if client:
            client.restack(StackMode.BottomIf)
