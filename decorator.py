# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

from xcb.xproto import *

class Decorator(object):
    def __init__(self, conn, client):
        """Decorate the client window."""
        self.conn = conn
        self.client = client

    def undecorate(self):
        """Remove all decorations from the client window."""
        pass

    def focus(self):
        """Indicate that the client window has the input focus."""
        pass

    def unfocus(self):
        """Indicate that the client window has lost the input focus."""
        pass

class BorderDecorator(Decorator):
    """Decorate a client window with a simple border."""

    def __init__(self, conn, client,
                 border_width=2,
                 focused_color="black",
                 unfocused_color="lightgrey"):
        super(BorderDecorator, self).__init__(conn, client)
        self.focused = self.client.manager.colors[focused_color]
        self.unfocused = self.client.manager.colors[unfocused_color]
        self.original_border_width = self.client.geometry.border_width
        self.conn.core.ConfigureWindow(self.client.window,
                                       ConfigWindow.BorderWidth,
                                       [border_width])

    def undecorate(self):
        black_pixel = self.client.manager.screen.black_pixel
        self.conn.core.ChangeWindowAttributes(self.client.window,
                                              CW.BorderPixel,
                                              [black_pixel])
        self.conn.core.ConfigureWindow(self.client.window,
                                       ConfigWindow.BorderWidth,
                                       [self.original_border_width])
        self.conn.flush()

    def focus(self):
        self.conn.core.ChangeWindowAttributes(self.client.window,
                                              CW.BorderPixel,
                                              [self.focused])

    def unfocus(self):
        self.conn.core.ChangeWindowAttributes(self.client.window,
                                              CW.BorderPixel,
                                              [self.unfocused])
