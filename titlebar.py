# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

from event import *
from inputfield import *
from widget import *
from xutil import textitem16

__all__ = ["TitlebarConfig", "Titlebar", "SimpleTitlebar", "InputFieldTitlebar"]


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

    def create_window(self, *args, **kwargs):
        window = super(Titlebar, self).create_window(*args, **kwargs)
        self.config.button_bindings.establish_grabs(window)
        return window

    def draw(self):
        # Fill the titlebar with the background color.
        w = max(self.geometry.width - 1, 0)
        h = max(self.geometry.height - 2, 0)
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
