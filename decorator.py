# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

import logging

from xcb.xproto import *
import xcb.shape

from bindings import *
from client import *
from event import *
from geometry import *
from inputfield import InputField
from widget import FontConfig, HighlightConfig, Widget
from xutil import textitem16

__all__ = ["Decorator", "BorderHighlightFocus", "FrameDecorator",
           "TitlebarConfig", "TitlebarDecorator"]

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
        """Update the shape of a non-rectangular frame for decorations."""
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

class TitlebarConfig(FontConfig, HighlightConfig):
    def __init__(self, manager, **kwargs):
        super(TitlebarConfig, self).__init__(manager, **kwargs)

        # Padding is based on the font descent, plus 2 pixels for the relief
        # edge, with a small scaling factor.
        ascent = self.font_info.font_ascent
        descent = self.font_info.font_descent
        pad = (descent + 2) * 6 // 5
        self.height = 2 * pad + ascent + descent
        self.baseline = pad + ascent

class Titlebar(Widget):
    """A widget which displays a line of text. A titlebar need not display
    a window title; it can be used for other purposes."""

    event_mask = (EventMask.Exposure |
                  EventMask.ButtonPress)
    override_redirect = True

    def __init__(self, client=None, **kwargs):
        super(Titlebar, self).__init__(**kwargs)
        self.client = client

    def draw(self):
        # Fill the titlebar with the background color.
        w = self.geometry.width - 1
        h = self.geometry.height - 2
        self.conn.core.PolyFillRectangle(self.window, self.config.bg_gc,
                                         1, [0, 0, w, h])

        # Give the titlebar a subtle relief effect.
        self.conn.core.PolyLine(CoordMode.Origin, self.window,
                                self.config.highlight_gc,
                                3, [0, h, 0, 0, w, 0])
        self.conn.core.PolyLine(CoordMode.Origin, self.window,
                                self.config.lowlight_gc,
                                3, [w, 1, w, h, 1, h])

        # Draw a dividing line between the titlebar and the window.
        self.conn.core.PolyLine(CoordMode.Origin, self.window,
                                self.config.black_gc,
                                2, [0, h + 1, w, h + 1])

class SimpleTitlebar(Titlebar):
    """A titlebar that displays the window title."""

    event_mask = (EventMask.StructureNotify |
                  EventMask.Exposure |
                  EventMask.ButtonPress)

    def __init__(self, title="", **kwargs):
        super(SimpleTitlebar, self).__init__(**kwargs)
        self.title = title

    def draw(self, x=5):
        super(SimpleTitlebar, self).draw()

        if not self.title:
            self.title = self.client_name()
        text_items = list(textitem16(self.title))
        self.conn.core.PolyText16(self.window, self.config.fg_gc,
                                  x, self.config.baseline,
                                  len(text_items), "".join(text_items))

    def name_changed(self, window, *args):
        assert window is self.client.window
        self.title = self.client_name()
        self.draw()

    def client_name(self):
        return (self.client.properties.net_wm_name or
                self.client.properties.wm_name)

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        for property_name in ("WM_NAME", "_NET_WM_NAME"):
            self.client.properties.register_change_handler(property_name,
                                                           self.name_changed)

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        for property_name in ("WM_NAME", "_NET_WM_NAME"):
            self.client.properties.unregister_change_handler(property_name,
                                                             self.name_changed)

class InputFieldTitlebar(InputField, Titlebar):
    event_mask = (EventMask.StructureNotify |
                  EventMask.Exposure |
                  EventMask.ButtonPress |
                  EventMask.KeyPress |
                  EventMask.FocusChange)

    def __init__(self, time=Time.CurrentTime, **kwargs):
        super(InputFieldTitlebar, self).__init__(**kwargs)
        self.time = time

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        self.client.focus_override = self.window
        try:
            self.manager.focus(self.client, self.time)
        except AttributeError:
            pass

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        self.client.focus_override = None
        self.manager.ensure_focus(self.client, self.time)

    @handler(KeyPressEvent)
    def handle_key_press(self, event):
        self.time = event.time

class TitlebarDecorator(Decorator):
    """Decorate a client with a multi-purpose titlebar."""

    def __init__(self, conn, client,
                 focused_config=None, unfocused_config=None, button_bindings={},
                 **kwargs):
        assert isinstance(focused_config, TitlebarConfig)
        assert isinstance(unfocused_config, TitlebarConfig)
        self.titlebar = None
        self.titlebar_configs = (unfocused_config, focused_config)
        self.button_bindings = button_bindings
        super(TitlebarDecorator, self).__init__(conn, client, **kwargs)

    def decorate(self):
        assert self.titlebar is None
        super(TitlebarDecorator, self).decorate()

        config = self.titlebar_configs[0]
        geometry = Geometry(0, 0, self.client.geometry.width, config.height, 0)
        self.titlebar = SimpleTitlebar(client=self.client,
                                       manager=self.client.manager,
                                       parent=self.client.frame,
                                       button_bindings=self.button_bindings,
                                       geometry=geometry,
                                       config=config)
        if self.client.shaped:
            self.update_frame_shape()
        self.titlebar.map()

    def undecorate(self):
        assert self.titlebar is not None
        self.conn.core.DestroyWindow(self.titlebar.window)
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
        self.conn.core.UnmapWindow(titlebar.window)
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
