# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

from event import *
from geometry import *
from icon import *
from inputfield import *
from widget import *
from xutil import textitem16

__all__ = ["Titlebar", "SimpleTitlebar", "IconTitlebar", "InputFieldTitlebar"]

class Titlebar(Widget):
    """A widget which displays a line of text. A titlebar need not display
    a window title; it can be used for other purposes."""

    event_mask = (EventMask.Exposure |
                  EventMask.ButtonPress)
    override_redirect = True

    def create_window(self, **kwargs):
        window = super(Titlebar, self).create_window(**kwargs)
        self.config.button_bindings.establish_grabs(window)
        return window

    def draw(self):
        super(Titlebar, self).draw()

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

    def draw(self):
        super(SimpleTitlebar, self).draw()

        if not self.title:
            self.title = self.client.title
        width = self.geometry.width - 2 * self.config.margin
        title = self.config.font_info.truncate(unicode(self.title), width)
        text_items = list(textitem16(title))
        self.conn.core.PolyText16(self.window, self.config.fg_gc,
                                  self.config.margin, self.config.baseline,
                                  len(text_items), "".join(text_items))

    def client_title_changed(self, window, *args):
        assert window is self.client.window
        self.title = self.client.title
        self.draw()

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        self.client.register_title_change_handler(self.client_title_changed)

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        self.client.unregister_title_change_handler(self.client_title_changed)

class IconTitlebar(Icon, SimpleTitlebar):
    """A titlebar that displays an icon along with the title."""
    pass

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
