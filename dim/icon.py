# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

from client import Client
from geometry import Geometry, Position, origin, empty_geometry
from widget import Widget
from xutil import get_geometry

__all__ = ["Icon"]

class Icon(Widget):
    """A widget with a pixmap that represents a client."""

    def __init__(self, client=None, config=None, **kwargs):
        assert config, "Need a widget configuration."
        super(Icon, self).__init__(client=client, config=config, **kwargs)

        self.icon_gc = None
        self.icon = client

    @property
    def margin(self):
        return self.config.margin if hasattr(self.config, "margin") else 0

    @margin.setter
    def margin(self, margin):
        self.config.margin = margin

    @property
    def icon(self):
        return (self.icon_pixmap,
                self.icon_mask,
                self.icon_geometry,
                self.icon_depth)

    @icon.setter
    def icon(self, client):
        (self.icon_pixmap,
         self.icon_mask,
         self.icon_geometry,
         self.icon_depth) = (client.icon
                             if client
                             else (Pixmap._None,
                                   Pixmap._None,
                                   empty_geometry,
                                   0))
        if self.icon_pixmap:
            margin = self.margin
            if self.icon_geometry.height > 2 * (self.geometry.height - margin):
                # The icon is too tall to display.
                self.offset = origin
                self.icon_pixmap = Pixmap._None
                self.icon_geometry = empty_geometry
                return
            elif self.icon_geometry.height > self.geometry.height - margin:
                # Clip the icon vertically.
                self.offset = Position(margin, margin // 2)
                self.icon_geometry &= Geometry(0, 0,
                                               self.geometry.width,
                                               self.geometry.height - margin,
                                               0)
            else:
                # Center the icon vertically.
                self.offset = Position(margin,
                                       (self.geometry.height - margin // 2 -
                                        self.icon_geometry.height) // 2)

            # Create or change the icon GC.
            value_mask = (GC.Foreground |
                          GC.Background |
                          GC.ClipOriginX |
                          GC.ClipOriginY |
                          GC.ClipMask)
            value_list = [self.screen.black_pixel,
                          self.screen.white_pixel,
                          self.offset.x,
                          self.offset.y,
                          self.icon_mask]
            if self.icon_gc:
                self.conn.core.ChangeGC(self.icon_gc, value_mask, value_list)
            else:
                self.icon_gc = self.conn.generate_id()
                self.conn.core.CreateGC(self.icon_gc, self.screen.root,
                                        value_mask, value_list)

    def destroy(self):
        if self.icon_gc:
            self.conn.core.FreeGC(self.icon_gc)

        super(Icon, self).destroy()

    def draw(self):
        # Temporarily adjust the margin to make room for the icon
        # while we draw the rest of the widget.
        margin = self.margin
        self.margin += (self.icon_geometry.width + self.offset.x
                        if self.icon_geometry
                        else 0)
        try:
            super(Icon, self).draw()
        finally:
            self.margin = margin

        if self.icon_pixmap:
            # ICCCM §4.1.2.4 requires that icon pixmaps be 1 bit deep,
            # suggesting that "[c]lients that need more capabilities
            # from the icons than a simple two-color bitmap should use
            # icon windows." Many clients (including xterm) ignore
            # both the requirement and the suggestion.
            if self.icon_depth == 1:
                self.conn.core.CopyPlane(self.icon_pixmap, self.window,
                                         self.icon_gc, 0, 0,
                                         self.offset.x, self.offset.y,
                                         self.icon_geometry.width,
                                         self.icon_geometry.height,
                                         1)
            elif self.icon_depth == self.screen.root_depth:
                self.conn.core.CopyArea(self.icon_pixmap, self.window,
                                        self.icon_gc, 0, 0,
                                        self.offset.x, self.offset.y,
                                        self.icon_geometry.width,
                                        self.icon_geometry.height)
