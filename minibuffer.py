# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

from bindings import *
from geometry import Geometry
from inputfield import InputField
from widget import *
from xutil import get_window_geometry

__all__ = ["MinibufferConfig", "Minibuffer"]

class MinibufferConfig(FontConfig, HighlightConfig):
    def __init__(self, manager, **kwargs):
        super(MinibufferConfig, self).__init__(manager, **kwargs)

        ascent = self.font_info.font_ascent
        descent = self.font_info.font_descent
        pad = descent
        self.height = 2 * pad + ascent + descent
        self.baseline = pad + ascent

class Minibuffer(InputField):
    keys = KeyBindingMap({("meta", "p"): "previous-history-element",
                          ("meta", "n"): "next-history-element"},
                         parent=InputField.keys)

    def __init__(self, history=[], **kwargs):
        super(Minibuffer, self).__init__(**kwargs)
        self.history = history
        self.history_index = len(history)

    def create_window(self, **kwargs):
        if not kwargs.get("geometry"):
            root_geometry = get_window_geometry(self.conn, self.screen.root)
            w = int(root_geometry.width * 0.8)
            h = self.config.height
            x = (root_geometry.width - w) // 2
            y = root_geometry.height - h
            bw = 1
            kwargs["geometry"] = Geometry(x - bw, y - 2 * bw, w, h, bw)
        return super(Minibuffer, self).create_window(**kwargs)

    def map(self, time=Time.CurrentTime):
        super(Minibuffer, self).map()
        self.conn.core.GrabKeyboard(False, self.window, time,
                                    GrabMode.Async, GrabMode.Async)

    def draw(self):
        # Fill with the background color.
        w = self.geometry.width - 1
        h = self.geometry.height - 1
        self.conn.core.PolyFillRectangle(self.window, self.config.bg_gc,
                                         1, [0, 0, w, h])

        # Add a subtle relief effect.
        self.conn.core.PolyLine(CoordMode.Origin, self.window,
                                self.config.highlight_gc,
                                3, [0, h, 0, 0, w, 0])
        self.conn.core.PolyLine(CoordMode.Origin, self.window,
                                self.config.lowlight_gc,
                                3, [w, 1, w, h, 1, h])

        super(Minibuffer, self).draw()

    def previous_history_element(self, incr=lambda x: x - 1):
        self.history_element(incr)

    def next_history_element(self, incr=lambda x: x + 1):
        self.history_element(incr)

    def history_element(self, incr):
        if not self.history:
            self.flash()
            return
        self.history_index = incr(self.history_index) % len(self.history)
        self.buffer[:] = self.history[self.history_index]
        self.draw()
        
