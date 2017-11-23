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

        self.icon_gc = self.conn.generate_id()
        self.and_gc = self.conn.generate_id()
        self.xor_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.icon_gc, self.screen.root,
                                (GC.Foreground |
                                 GC.Background),
                                [self.screen.black_pixel,
                                 self.screen.white_pixel])
        self.conn.core.CreateGC(self.and_gc, self.screen.root,
                                (GC.Function |
                                 GC.Foreground |
                                 GC.Background),
                                [GX._and,
                                 self.screen.black_pixel,
                                 self.screen.white_pixel])
        self.conn.core.CreateGC(self.xor_gc, self.screen.root,
                                GC.Function,
                                [GX.xor])

        self.icon = client

    def destroy(self):
        self.conn.core.FreeGC(self.icon_gc)
        self.conn.core.FreeGC(self.and_gc)
        self.conn.core.FreeGC(self.xor_gc)

        super(Icon, self).destroy()

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
            self.conn.core.ChangeGC(self.icon_gc,
                                    (GC.ClipOriginX |
                                     GC.ClipOriginY |
                                     GC.ClipMask),
                                    [self.offset.x,
                                     self.offset.y,
                                     self.icon_mask])

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
            mask = self.icon_mask
            pixmap = self.icon_pixmap
            window = self.window
            (x, y) = self.offset
            (w, h) = self.icon_geometry.size()

            # ICCCM §4.1.2.4 requires that icon pixmaps be 1 bit deep,
            # suggesting that "[c]lients that need more capabilities
            # from the icons than a simple two-color bitmap should use
            # icon windows." Many clients (including xterm) ignore
            # both the requirement and the suggestion.
            if self.icon_depth == 1:
                self.conn.core.CopyPlane(pixmap, window, self.icon_gc,
                                         0, 0, x, y, w, h, 1)
            elif self.icon_depth == self.screen.root_depth:
                # It would be nice if we could use our GC with clip mask
                # for the non-bitmap case, too, but the Intel SNA driver's
                # mask compositing appears to be buggy, and sometimes garbles
                # icons with non-trivial masks. This workaround is from
                # Anthony Thyssen's X programming hints page at
                # <https://www.ict.griffith.edu.au/anthony/info/X/Programing.hints>.
                xor = self.xor_gc
                _and = self.and_gc
                self.conn.core.CopyArea(pixmap, window, xor, 0, 0, x, y, w, h)
                self.conn.core.CopyPlane(mask, window, _and, 0, 0, x, y, w, h, 1)
                self.conn.core.CopyArea(pixmap, window, xor, 0, 0, x, y, w, h)
