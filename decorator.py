# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

from logging import debug, info, warning, error

from xcb.xproto import *

from geometry import *

class Decorator(object):
    def __init__(self, conn, client,
                 border_width=2,
                 focused_color="black",
                 unfocused_color="lightgrey"):
        self.conn = conn
        self.client = client
        self.screen = client.manager.screen
        self.border_width = border_width
        self.focused_color = self.client.manager.colors[focused_color]
        self.unfocused_color = self.client.manager.colors[unfocused_color]

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

    def save_border(self):
        """Retrieve and store the border width of the client window."""
        self.original_border_width = self.client.geometry.border_width

    def restore_border(self):
        """Restore the client window's original border."""
        self.conn.core.ConfigureWindow(self.client.window,
                                       ConfigWindow.BorderWidth,
                                       [self.original_border_width])

class BorderDecorator(Decorator):
    """Decorate a client window with a simple border."""
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

class FrameDecorator(Decorator):
    """Create a frame (i.e., a new parent) for a client window."""

    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.LeaveWindow)

    def decorate(self):
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
        self.restore_border()
        self.conn.core.ReparentWindow(self.client.window,
                                      self.screen.root,
                                      self.client.geometry.x,
                                      self.client.geometry.y)
        self.conn.core.ChangeSaveSet(SetMode.Delete, self.client.window)
        self.conn.core.DestroyWindow(self.client.frame)

    def frame_geometry(self):
        return (self.client.geometry._replace(border_width=self.border_width),
                Position(0, 0))

    def focus(self):
        self.conn.core.ChangeWindowAttributes(self.client.frame,
                                              CW.BorderPixel,
                                              [self.focused_color])

    def unfocus(self):
        self.conn.core.ChangeWindowAttributes(self.client.frame,
                                              CW.BorderPixel,
                                              [self.unfocused_color])

class TitleDecorator(FrameDecorator):
    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.LeaveWindow)

    def __init__(self, conn, client, title_gc, title_padding=6, **kwargs):
        super(TitleDecorator, self).__init__(conn, client, **kwargs)
        self.title_gc = title_gc
        info = client.manager.fonts.info(title_gc)
        self.baseline = title_padding // 2 + info.font_ascent
        self.titlebar_height = (info.font_ascent +
                                info.font_descent +
                                title_padding)

    def decorate(self):
        super(TitleDecorator, self).decorate()

        self.title = self.client.wm_name
        self.titlebar = self.conn.generate_id()
        self.conn.core.CreateWindow(self.screen.root_depth,
                                    self.titlebar,
                                    self.client.frame,
                                    0, 0, self.geometry.width, self.offset.y, 0,
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    CW.BackPixel | CW.EventMask,
                                    [self.screen.black_pixel,
                                     EventMask.Exposure])
        self.conn.core.MapWindow(self.titlebar)
        self.client.manager.register_subwindow_handler(ExposeEvent,
                                                       self.titlebar,
                                                       self.refresh)

    def undecorate(self):
        super(TitleDecorator, self).undecorate()
        self.conn.core.DestroyWindow(self.titlebar)

    def refresh(self, event):
        assert isinstance(event, ExposeEvent)
        if event.count == 0:
            self.draw_title(self.title)

    def draw_title(self, title=None, x=5):
        if title is None:
            title = self.client.wm_name
        self.conn.core.ClearArea(False, self.titlebar, 0, 0, 0, 0)
        if title:
            debug('Drawing title "%s".' % title)
            self.title = title
            self.conn.core.ImageText8(len(title), self.titlebar,
                                      self.title_gc, x, self.baseline, title)

    def frame_geometry(self):
        geometry = self.client.geometry._replace(border_width=self.border_width)
        geometry += Rectangle(0, self.titlebar_height)
        return (geometry, Position(0, self.titlebar_height))
