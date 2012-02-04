# -*- mode: Python; coding: utf-8 -*-

from collections import defaultdict, deque

from xcb.xproto import *

from bindings import *
from geometry import Geometry
from inputfield import InputField
from keysym import *
from widget import *
from xutil import query_pointer

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
    keys = KeyBindingMap({XK_Up: "previous-history-element",
                          XK_Down: "next-history-element",
                          ("meta", "p"): "previous-history-element",
                          ("meta", "n"): "next-history-element"},
                         parent=InputField.keys)

    # If no history ring is provided at initialization time, we'll use
    # a shared history, indexed by prompt.
    hist_size = 100
    shared_history = defaultdict(lambda n=hist_size: deque([], n))

    def __init__(self, commit=lambda value: None, history=None, **kwargs):
        def commit_wrapper(value):
            commit(value)
            if (value and (not self.history or
                           (self.history and value != self.history[-1]))):
                self.history.append(value)
        super(Minibuffer, self).__init__(commit=commit_wrapper, **kwargs)

        if history is not None:
            self.history = history
        else:
            self.history = self.shared_history[self.prompt]
        self.history_index = len(self.history)

    def create_window(self, **kwargs):
        if not kwargs.get("geometry"):
            # Center the window along the bottom edge of the screen, taking
            # 80% of the available width.
            screen_geometry = self.manager.current_crtc_geometry
            w = int(screen_geometry.width * 0.8)
            h = self.config.height
            x = screen_geometry.x + (screen_geometry.width - w) // 2
            y = screen_geometry.y + screen_geometry.height - h
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
        n = len(self.history)
        if self.history_index == n:
            self.current_entry = unicode(self.buffer)
        self.history_index = incr(self.history_index) % (n + 1)
        if self.history_index == n:
            self.buffer[:] = self.current_entry
        else:
            self.buffer[:] = self.history[self.history_index]
        self.draw()
        
