# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

from logging import debug, info, warning, error

from xcb.xproto import *

from color import *
from geometry import *
from xutil import textitem16

__all__ = ["Decorator", "BorderDecorator", "FrameDecorator", "TitleDecorator",
           "TitlebarConfig"]

class Decorator(object):
    def __init__(self, conn, client):
        self.conn = conn
        self.client = client
        self.screen = client.screen

    def decorate(self):
        """Decorate the client window."""
        pass

    def undecorate(self):
        """Remove all decorations from the client window."""
        pass

    def focus(self):
        """Indicate that the client window has the input focus."""
        pass

    def unfocus(self):
        """Indicate that the client window has lost the input focus."""
        pass

    def message(self, message):
        """Display a message on behalf of the client."""
        pass

    def name_changed(self):
        """Update display of the client name."""
        pass

class BorderDecorator(Decorator):
    """Decorate a client window with a simple border."""

    def __init__(self, conn, client,
                 border_width=2,
                 focused_color="black",
                 unfocused_color="lightgrey"):
        super(BorderDecorator, self).__init__(conn, client)
        self.border_width = border_width
        self.focused_color = self.client.colors[focused_color]
        self.unfocused_color = self.client.colors[unfocused_color]

    def decorate(self):
        self.save_border()
        self.conn.core.ConfigureWindow(self.client.window,
                                       ConfigWindow.BorderWidth,
                                       [self.border_width])
        self.unfocus()

    def undecorate(self):
        self.restore_border()

        # X11 offers no way of retrieving the border color or pixmap of
        # a window, so we'll simply assume a black border.
        self.conn.core.ChangeWindowAttributes(self.client.window,
                                              CW.BorderPixel,
                                              [self.screen.black_pixel])

    def focus(self):
        self.conn.core.ChangeWindowAttributes(self.client.window,
                                              CW.BorderPixel,
                                              [self.focused_color])

    def unfocus(self):
        self.conn.core.ChangeWindowAttributes(self.client.window,
                                              CW.BorderPixel,
                                              [self.unfocused_color])

    def save_border(self):
        """Retrieve and store the border width of the client window."""
        self.original_border_width = self.client.geometry.border_width

    def restore_border(self):
        """Restore the client window's original border width."""
        self.conn.core.ConfigureWindow(self.client.window,
                                       ConfigWindow.BorderWidth,
                                       [self.original_border_width])

class FrameDecorator(BorderDecorator):
    """Create a frame (i.e., a new parent) for a client window."""

    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.LeaveWindow)

    def decorate(self):
        # Set the client's border to 0, since we'll put one on the frame.
        self.save_border()
        self.conn.core.ConfigureWindow(self.client.window,
                                       ConfigWindow.BorderWidth, [0])

        # We'll set a flag on the client so that the event handlers can
        # distinguish events generated as a result of the ReparentWindow
        # request.
        self.client.reparenting = True

        self.client.frame = self.conn.generate_id()
        self.geometry, self.offset = self.frame_geometry()
        debug("Creating frame 0x%x for client window 0x%x." %
              (self.client.frame, self.client.window))
        self.conn.core.CreateWindow(self.screen.root_depth,
                                    self.client.frame,
                                    self.screen.root,
                                    self.geometry.x, self.geometry.y,
                                    self.geometry.width, self.geometry.height,
                                    self.geometry.border_width,
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    (CW.BorderPixel |
                                     CW.OverrideRedirect |
                                     CW.EventMask),
                                    [self.unfocused_color,
                                     True,
                                     self.frame_event_mask])
        self.conn.core.ReparentWindow(self.client.window,
                                      self.client.frame,
                                      self.offset.x, self.offset.y)
        self.conn.core.ChangeSaveSet(SetMode.Insert, self.client.window)

    def undecorate(self):
        self.conn.core.UnmapWindow(self.client.frame)
        super(FrameDecorator, self).undecorate()
        self.conn.core.ReparentWindow(self.client.window,
                                      self.screen.root,
                                      self.client.geometry.x,
                                      self.client.geometry.y)
        self.conn.core.ChangeSaveSet(SetMode.Delete, self.client.window)
        self.conn.core.DestroyWindow(self.client.frame)

    def frame_geometry(self):
        """Compute and return the geometry for the frame."""
        return (self.client.geometry._replace(border_width=self.border_width),
                Position(0, 0))

class TitlebarConfig(object):
    def __init__(self, manager, fg_color, bg_color, font):
        assert isinstance(fg_color, Color)
        assert isinstance(bg_color, Color)
        assert isinstance(font, (str, int))

        conn = manager.conn
        root = manager.screen.root
        font = manager.fonts[font] if isinstance(font, str) else font
        info = manager.fonts.info(font)

        # Padding is based on the font descent, plus 2 pixels for the relief
        # edge, with a small scaling factor.
        pad = (info.font_descent + 2) * 6 // 5
        self.height = 2 * pad + info.font_ascent + info.font_descent
        self.baseline = pad + info.font_ascent

        self.black_gc = manager.black_gc

        self.fg_gc = conn.generate_id()
        conn.core.CreateGC(self.fg_gc, root,
                           GC.Foreground | GC.Background | GC.Font,
                           [manager.colors[fg_color],
                            manager.colors[bg_color],
                            font])

        self.bg_gc = conn.generate_id()
        conn.core.CreateGC(self.bg_gc, root,
                           GC.Foreground | GC.Background,
                           [manager.colors[bg_color],
                            manager.colors[fg_color]])

        high, low = self.highlight(bg_color)
        self.highlight_gc = conn.generate_id()
        conn.core.CreateGC(self.highlight_gc, root,
                           GC.Foreground, [manager.colors[high]])
        self.lowlight_gc = conn.generate_id()
        conn.core.CreateGC(self.lowlight_gc, root,
                           GC.Foreground, [manager.colors[low]])

    @staticmethod
    def highlight(color):
        h, s, v = color.hsv()
        return (HSVColor(h, s, (3.0 + v) / 4.0),
                HSVColor(h, s, (1.0 + v) / 4.0))

class TitleDecorator(FrameDecorator):
    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.LeaveWindow)

    def __init__(self, conn, client,
                 focused_title_config, unfocused_title_config,
                 **kwargs):
        self.title_configs = (unfocused_title_config, focused_title_config)
        self.config = self.title_configs[0] # reassigned by focus, unfocus
        super(TitleDecorator, self).__init__(conn, client,
                                             unfocused_color="black",
                                             **kwargs)

    def decorate(self):
        super(TitleDecorator, self).decorate()

        self.title = None
        self.titlebar = self.conn.generate_id()
        self.conn.core.CreateWindow(self.screen.root_depth,
                                    self.titlebar,
                                    self.client.frame,
                                    0, 0, self.geometry.width, self.offset.y, 0,
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    CW.EventMask, [EventMask.Exposure])
        self.conn.core.MapWindow(self.titlebar)
        self.client.manager.register_subwindow_handler(ExposeEvent,
                                                       self.titlebar,
                                                       self.refresh)

    def undecorate(self):
        super(TitleDecorator, self).undecorate()
        self.conn.core.DestroyWindow(self.titlebar)

    def focus(self):
        self.config = self.title_configs[1]
        self.refresh()

    def unfocus(self):
        self.config = self.title_configs[0]
        self.refresh()

    def message(self, message):
        self.draw_title(message)

    def name_changed(self):
        self.draw_title(None)

    def refresh(self, event=None):
        if event is None or \
                (isinstance(event, ExposeEvent) and event.count == 0):
            self.draw_title(self.title)

    def draw_title(self, title=None, x=5):
        if title is None:
            title = self.client.net_wm_name or self.client.wm_name

        w = self.geometry.width - 1
        h = self.config.height - 2
        self.conn.core.PolyFillRectangle(self.titlebar, self.config.bg_gc,
                                         1, [0, 0, w, h])

        # Give the titlebar a subtle relief effect.
        self.conn.core.PolyLine(CoordMode.Origin, self.titlebar,
                                self.config.highlight_gc,
                                3, [0, h, 0, 0, w, 0])
        self.conn.core.PolyLine(CoordMode.Origin, self.titlebar,
                                self.config.lowlight_gc,
                                3, [w, 1, w, h, 1, h])
        self.conn.core.PolyLine(CoordMode.Origin, self.titlebar,
                                self.config.black_gc,
                                2, [0, h + 1, w, h + 1])

        if title:
            # Cache the string we're drawing for refresh.
            self.title = title

            text_items = list(textitem16(title))
            self.conn.core.PolyText16(self.titlebar, self.config.fg_gc,
                                      x, self.config.baseline,
                                      len(text_items), "".join(text_items))

    def frame_geometry(self):
        geometry = self.client.geometry._replace(border_width=1)
        geometry += Rectangle(0, self.config.height)
        return (geometry, Position(0, self.config.height))
