# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

from bindings import *
from color import *
from event import *
from font import text_width
from geometry import *

__all__ = ["Config", "FontConfig", "HighlightConfig", "Widget"]

class Config(object):
    """A shared configuration object used by widget instances."""

    def __init__(self, manager, **kwargs):
        self.manager = manager
        self.conn = manager.conn
        self.screen = manager.screen

        self.black_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.black_gc, self.screen.root,
                                GC.Foreground | GC.Background,
                                [self.screen.black_pixel,
                                 self.screen.white_pixel])

        self.white_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.white_gc, self.screen.root,
                                GC.Foreground | GC.Background,
                                [self.screen.white_pixel,
                                 self.screen.black_pixel])

class FontConfig(Config):
    def __init__(self, manager, **kwargs):
        super(FontConfig, self).__init__(manager, **kwargs)

        fg_color = kwargs["fg_color"]
        bg_color = kwargs["bg_color"]
        font = kwargs["font"]
        self.font = manager.fonts[font] if isinstance(font, str) else font
        self.font_info = manager.fonts.info(self.font)

        colors = manager.colors

        self.fg_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.fg_gc, self.screen.root,
                                GC.Foreground | GC.Background | GC.Font,
                                [colors[fg_color],
                                 colors[bg_color],
                                 self.font])

        self.bg_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.bg_gc, self.screen.root,
                                GC.Foreground | GC.Background | GC.Font,
                                [colors[bg_color],
                                 colors[fg_color],
                                 self.font])

        self.xor_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.xor_gc, self.screen.root,
                                GC.Function | GC.Foreground | GC.Font,
                                [GX.xor,
                                 colors[fg_color] ^ colors[bg_color],
                                 self.font])

    def text_width(self, string):
        return text_width(self.font_info, string)

class HighlightConfig(Config):
    def __init__(self, manager, **kwargs):
        super(HighlightConfig, self).__init__(manager, **kwargs)

        high, low = self.highlight(kwargs["bg_color"])
        colors = manager.colors

        self.highlight_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.highlight_gc, self.screen.root,
                                GC.Foreground,
                                [colors[high]])

        self.lowlight_gc = self.conn.generate_id()
        self.conn.core.CreateGC(self.lowlight_gc, self.screen.root,
                                GC.Foreground,
                                [colors[low]])

    @staticmethod
    def highlight(color):
        h, s, v = color.hsv()
        return (HSVColor(h, s, (2.8 + v) / 4.0),
                HSVColor(h, s, (2.0 + v) / 5.0))

class Widget(EventHandler):
    event_mask = EventMask.Exposure
    override_redirect = False

    def __init__(self, manager=None, config=None,
                 key_bindings={}, button_bindings={},
                 **kwargs):
        self.manager = manager
        self.conn = manager.conn
        self.screen = manager.screen
        self.config = config
        self.key_bindings = KeyBindings(key_bindings,
                                        manager.keymap,
                                        manager.modmap)
        self.button_bindings = ButtonBindings(button_bindings,
                                              manager.keymap,
                                              manager.modmap,
                                              manager.butmap)
        self.window = self.create_window(**kwargs)

    def create_window(self,
                      parent=None,
                      geometry=None,
                      event_mask=None,
                      override_redirect=None):
        """Create a top-level window for this widget."""
        assert parent
        assert isinstance(geometry, Geometry)

        self.parent = parent if parent else self.screen.root
        self.geometry = geometry
        self.window = self.conn.generate_id()
        self.conn.core.CreateWindow(self.screen.root_depth,
                                    self.window, self.parent,
                                    geometry.x, geometry.y,
                                    geometry.width, geometry.height,
                                    geometry.border_width,
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    CW.OverrideRedirect | CW.EventMask,
                                    [(override_redirect
                                      if override_redirect is not None
                                      else self.override_redirect),
                                     (event_mask
                                      if event_mask is not None
                                      else self.event_mask)])
        self.manager.register_window_handler(self.window, self)
        return self.window

    def map(self):
        """Map the widget's top-level window."""
        self.conn.core.MapWindow(self.window)

    def unmap(self):
        """Unmap the widget's top-level window."""
        self.conn.core.UnmapWindow(self.window)

    def destroy(self):
        """Destroy the widget and all of its windows."""
        self.conn.core.DestroyWindow(self.window)

    def configure(self, geometry):
        """Update the widget for a new geometry."""
        self.geometry = geometry
        self.conn.core.ConfigureWindow(self.window,
                                       ConfigWindow.Width,
                                       [geometry.width])
        return geometry

    def draw(self):
        """Draw the widget contents."""
        pass

    @handler(ExposeEvent)
    def handle_expose(self, event):
        if event.count == 0:
            self.draw()

    @handler(KeyPressEvent)
    def handle_key_press(self, event):
        try:
            action = self.key_bindings[event]
        except KeyError:
            return
        action(self, event)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        try:
            action = self.button_bindings[event]
        except KeyError:
            return
        action(self, event)
