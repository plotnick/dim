# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

import logging

from xcb.xproto import *
import xcb.shape

from geometry import *
from titlebar import *

__all__ = ["Decorator", "BorderHighlightFocus", "TitlebarDecorator"]

class Decorator(object):
    """A decorator is responsible for drawing and maintaining the decoration
    applied to a client window.

    Subclasses may in general be composed to provide composite decorations."""

    def __init__(self, conn, client, border_width=1, **kwargs):
        self.conn = conn
        self.client = client
        self.screen = client.screen
        self.border_width = border_width
        self.log = logging.getLogger("decorator.0x%x" % self.client.window)

    def decorate(self):
        """Decorate the client window."""
        pass

    def undecorate(self):
        """Remove all decorations from the client window."""
        pass

    def configure(self, geometry):
        """Update decorations for a new client/frame geometry."""
        pass

    def update_frame_shape(self):
        """Update the shape of a client frame for decorations."""
        pass

    def focus(self):
        """Indicate that the client window has the input focus."""
        pass

    def unfocus(self):
        """Indicate that the client window has lost the input focus."""
        pass

    def message(self, message):
        """Display a message on behalf of the client."""
        if message:
            self.log.info(message)

    def compute_client_offset(self):
        """Compute and return a geometry whose position is the required
        offset of the client window with respect to the inside corner of
        the containing frame and whose size is the total additional size
        required for the desired decorations. The border_width attribute
        is unused.

        This method may be called prior to decoration, and so can rely only
        on data collected or computed during initialization."""
        return empty_geometry

class BorderHighlightFocus(Decorator):
    """Indicate the current focus via changes to the border color."""

    def __init__(self, conn, client, border_width=2,
                 focused_color="black", unfocused_color="lightgrey",
                 **kwargs):
        super(BorderHighlightFocus, self).__init__(conn, client, border_width,
                                                   **kwargs)
        self.focused_color = self.client.colors[focused_color]
        self.unfocused_color = self.client.colors[unfocused_color]

    def focus(self):
        self.conn.core.ChangeWindowAttributes(self.border_window,
                                              CW.BorderPixel,
                                              [self.focused_color])
        super(BorderHighlightFocus, self).focus()

    def unfocus(self):
        self.conn.core.ChangeWindowAttributes(self.border_window,
                                              CW.BorderPixel,
                                              [self.unfocused_color])
        super(BorderHighlightFocus, self).unfocus()

class TitlebarDecorator(Decorator):
    """Decorate a client with a multi-purpose titlebar."""

    def __init__(self, conn, client,
                 focused_config=None, unfocused_config=None,
                 **kwargs):
        super(TitlebarDecorator, self).__init__(conn, client, **kwargs)

        assert isinstance(focused_config, TitlebarConfig)
        assert isinstance(unfocused_config, TitlebarConfig)
        self.titlebar = None
        self.titlebar_configs = (unfocused_config, focused_config)

    def decorate(self):
        assert self.titlebar is None
        super(TitlebarDecorator, self).decorate()

        config = self.titlebar_configs[0]
        geometry = Geometry(0, 0, self.client.geometry.width, config.height, 0)
        self.titlebar = SimpleTitlebar(client=self.client,
                                       manager=self.client.manager,
                                       parent=self.client.frame,
                                       geometry=geometry,
                                       config=config)
        if self.client.shaped:
            self.update_frame_shape()
        self.titlebar.map()

    def undecorate(self):
        assert self.titlebar
        self.titlebar.destroy()
        self.titlebar = None
        super(TitlebarDecorator, self).undecorate()

    def configure(self, geometry):
        if self.titlebar:
            self.titlebar.configure(Geometry(0, 0,
                                             geometry.width,
                                             self.titlebar.config.height, 0))

    def update_frame_shape(self):
        if self.titlebar:
            bw = self.border_width
            rectangles = [-bw, -bw,
                          self.titlebar.geometry.width + 2 * bw,
                          self.titlebar.geometry.height + bw]
            self.client.manager.shape.Rectangles(xcb.shape.SO.Union,
                                                 xcb.shape.SK.Bounding,
                                                 ClipOrdering.YXBanded,
                                                 self.client.frame,
                                                 0, 0,
                                                 len(rectangles),
                                                 rectangles)

    def compute_client_offset(self):
        config = (self.titlebar.config if self.titlebar else
                  self.titlebar_configs[0])
        return Geometry(0, config.height, 0, config.height, None)

    def focus(self):
        if self.titlebar:
            self.titlebar.config = self.titlebar_configs[1]
            self.titlebar.draw()
        super(TitlebarDecorator, self).focus()

    def unfocus(self):
        if self.titlebar:
            self.titlebar.config = self.titlebar_configs[0]
            self.titlebar.draw()
        super(TitlebarDecorator, self).unfocus()

    def message(self, message):
        if self.titlebar:
            self.titlebar.title = message
            self.titlebar.draw()

    def read_from_user(self, prompt, initial_value="",
                       continuation=lambda value: None,
                       config=None,
                       time=Time.CurrentTime):
        if self.titlebar is None:
            return
        if config is None:
            config = self.titlebar.config
        titlebar = self.titlebar
        self.titlebar.unmap()
        def restore_titlebar():
            self.titlebar.destroy()
            self.titlebar = titlebar
            self.titlebar.map()
        def commit(value):
            restore_titlebar()
            continuation(value)
        self.titlebar = InputFieldTitlebar(client=self.client,
                                           manager=self.client.manager,
                                           parent=self.client.frame,
                                           geometry=titlebar.geometry,
                                           config=config,
                                           time=time,
                                           prompt=prompt,
                                           initial_value=initial_value,
                                           commit=commit,
                                           rollback=restore_titlebar)
        self.titlebar.map()
