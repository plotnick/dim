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
        black_pixel = self.client.manager.screen.black_pixel
        self.conn.core.ChangeWindowAttributes(self.client.window,
                                              CW.BorderPixel,
                                              [black_pixel])

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
        window = self.client.window

        self.save_border()
        self.conn.core.ConfigureWindow(window, ConfigWindow.BorderWidth, [0])

        # We'll set a flag on the client so that the event handlers can
        # distinguish events generated as a result of the ReparentWindow
        # request.
        self.client.reparenting = True

        frame = self.client.frame = self.conn.generate_id()
        screen = self.client.manager.screen
        geometry, self.offset = self.frame_geometry()
        debug("Creating frame 0x%x for client window 0x%x." % (frame, window))
        self.conn.core.CreateWindow(screen.root_depth, frame, screen.root,
                                    geometry.x, geometry.y,
                                    geometry.width, geometry.height,
                                    geometry.border_width,
                                    WindowClass.CopyFromParent,
                                    screen.root_visual,
                                    (CW.BorderPixel |
                                     CW.OverrideRedirect |
                                     CW.EventMask),
                                    [self.unfocused_color,
                                     True,
                                     self.frame_event_mask])
        self.conn.core.ReparentWindow(window, frame,
                                      self.offset.x, self.offset.y)
        self.conn.core.ChangeSaveSet(SetMode.Insert, window)

    def undecorate(self):
        self.conn.core.UnmapWindow(self.client.frame)
        offset = -1 * self.offset
        self.conn.core.ReparentWindow(self.client.window,
                                      self.client.manager.screen.root,
                                      offset.x, offset.y)
        self.conn.core.ChangeSaveSet(SetMode.Delete, self.client.window)
        self.restore_border()

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
