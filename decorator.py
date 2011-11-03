# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

from logging import debug, info, warning, error

from xcb.xproto import *

from client import *
from color import *
from geometry import *
from xutil import textitem16

__all__ = ["Decorator", "BorderHighlightFocus", "FrameDecorator",
           "TitlebarConfig", "TitleDecorator"]

class Decorator(object):
    """A decorator is responsible for drawing and maintaining the decoration
    applied to a client window. Such decoration may be as trivial as changing
    the top-level window's border width and color, or as complex as providing
    a new parent frame with a title bar and other such amenities.

    Subclasses may in general be composed to provide composite decorations."""

    def __init__(self, conn, client, border_width=1, **kwargs):
        self.conn = conn
        self.client = client
        self.screen = client.screen
        self.border_window = client.window
        self.border_width = border_width

    def decorate(self):
        """Decorate the client window."""
        self.client.offset = self.compute_client_offset()
        self.original_border_width = self.client.geometry.border_width
        self.conn.core.ConfigureWindow(self.border_window,
                                       ConfigWindow.BorderWidth,
                                       [self.border_width])

    def undecorate(self):
        """Remove all decorations from the client window."""
        self.conn.core.ConfigureWindow(self.border_window,
                                       ConfigWindow.BorderWidth,
                                       [self.original_border_width])

        # X11 offers no way of retrieving the border color or pixmap of
        # a window, so we'll simply assume a black border.
        self.conn.core.ChangeWindowAttributes(self.border_window,
                                              CW.BorderPixel,
                                              [self.screen.black_pixel])

    def configure(self, geometry):
        """Update decorations for a new client/frame geometry."""
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
            info(message)

    def name_changed(self):
        """Update display of the client name."""
        pass

    def compute_client_offset(self):
        """Compute and return a geometry whose position represents the
        offset of the client window with respect to the inside corner of
        the containing frame (which may be the client window itself), and
        whose size is the total additional size required for the desired
        decorations. The border_width attribute is unused."""
        return Geometry(0, 0, 0, 0, None)

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

class FrameDecorator(Decorator):
    """Create a frame (i.e., a new parent) for a client window. This class
    requires a reparenting window manager."""

    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.LeaveWindow)

    def __init__(self, *args, **kwargs):
        super(FrameDecorator, self).__init__(*args, **kwargs)
        self.frame_border_width = self.border_width
        self.border_width = 0

    def decorate(self):
        super(FrameDecorator, self).decorate()

        # Determine the frame geometry based on the current client window
        # geometry and gravity together with the offsets needed for the
        # actual decoration.
        offset = self.client.offset
        gravity = self.client.wm_normal_hints.win_gravity
        geometry = self.client.absolute_geometry
        frame_geometry = geometry.resize(geometry.size() + offset.size(),
                                         self.frame_border_width,
                                         gravity)

        frame = self.conn.generate_id()
        window = self.client.window
        debug("Creating frame 0x%x for client window 0x%x." % (frame, window))
        self.conn.core.CreateWindow(self.screen.root_depth, frame,
                                    self.screen.root,
                                    frame_geometry.x, frame_geometry.y,
                                    frame_geometry.width, frame_geometry.height,
                                    frame_geometry.border_width,
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    (CW.OverrideRedirect | CW.EventMask),
                                    [True, self.frame_event_mask])
        self.conn.core.ReparentWindow(window, frame, offset.x, offset.y)
        self.conn.core.ChangeSaveSet(SetMode.Insert, window)

        # When the reparenting is complete, the manager will update the
        # class of the client to reflect its new status. We'll set the
        # frame attribute now, though, so that interested parties can
        # use it immediately.
        self.client.reparenting = FramedClientWindow
        self.client.frame = frame

        # Changes to the border should now be applied to the frame.
        self.border_window = frame

    def undecorate(self):
        if isinstance(self.client, FramedClientWindow):
            self.conn.core.UnmapWindow(self.client.frame)
            self.border_window = self.client.window

            super(FrameDecorator, self).undecorate()

            # Determine the new window geometry based on the current frame
            # geometry, the original border width, and the window gravity.
            size = self.client.geometry.size()
            bw = self.original_border_width
            gravity = self.client.wm_normal_hints.win_gravity
            geometry = self.client.frame_geometry.resize(size, bw, gravity)

            self.client.reparenting = ClientWindow
            self.conn.core.ReparentWindow(self.client.window, self.screen.root,
                                          geometry.x, geometry.y)
            self.conn.core.ChangeSaveSet(SetMode.Delete, self.client.window)
            self.conn.core.DestroyWindow(self.client.frame)

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
                HSVColor(h, s, (2.0 + v) / 5.0))

class TitleDecorator(FrameDecorator):
    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.LeaveWindow)

    def __init__(self, conn, client, border_width=1,
                 focused_title_config=None, unfocused_title_config=None,
                 **kwargs):
        assert (isinstance(focused_title_config, TitlebarConfig) and
                isinstance(unfocused_title_config, TitlebarConfig))
        self.title_configs = (unfocused_title_config, focused_title_config)
        self.config = self.title_configs[0] # reassigned by focus, unfocus
        self.title = None
        super(TitleDecorator, self).__init__(conn, client, border_width,
                                             **kwargs)

    def decorate(self):
        super(TitleDecorator, self).decorate()

        self.titlebar = self.conn.generate_id()
        self.conn.core.CreateWindow(self.screen.root_depth,
                                    self.titlebar,
                                    self.client.frame,
                                    0, 0, # x, y
                                    self.client.geometry.width, # width
                                    self.client.offset.y, # height
                                    0, # border_width
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    CW.EventMask, [EventMask.Exposure])
        self.conn.core.MapWindow(self.titlebar)
        self.client.manager.register_subwindow_handler(ExposeEvent,
                                                       self.titlebar,
                                                       self.refresh)

    def undecorate(self):
        if self.titlebar:
            self.conn.core.DestroyWindow(self.titlebar)
            self.titlebar = None
            super(TitleDecorator, self).undecorate()

    def configure(self, geometry):
        self.conn.core.ConfigureWindow(self.titlebar,
                                       ConfigWindow.Width,
                                       [geometry.width])

    def focus(self):
        self.config = self.title_configs[1]
        self.refresh()
        super(TitleDecorator, self).focus()

    def unfocus(self):
        self.config = self.title_configs[0]
        self.refresh()
        super(TitleDecorator, self).unfocus()

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
        assert title is not None
        title = unicode(title)

        w = self.client.geometry.width - 1
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

    def compute_client_offset(self):
        return Geometry(0, self.config.height, 0, self.config.height, None)
