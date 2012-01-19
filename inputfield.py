# -*- mode: Python; coding: utf-8 -*-

from collections import deque
from threading import Timer

from xcb.xproto import *

from bindings import *
from event import *
from keysym import *
from stringbuffer import *
from widget import *
from xutil import textitem16

__all__ = ["InputField"]

class AbortEdit(Exception):
    pass

class InputField(Widget):
    """A one-line, editable input field with an optional prompt."""

    kill_ring = deque([], 10)
    buttons = ButtonBindingMap({})
    keys = KeyBindingMap({XK_Return: "commit",
                          XK_Escape: "rollback",
                          XK_BackSpace: "delete-backward-char",
                          ("meta", XK_BackSpace): "backward-kill-word",
                          XK_Delete: "delete-forward-char",
                          XK_Left: "backward-char",
                          XK_Right: "forward-char",
                          XK_Home: "beginning-of-buffer",
                          XK_End: "end-of-buffer",
                          ("control", "f"): "forward-char",
                          ("control", "b"): "backward-char",
                          ("control", "a"): "beginning-of-buffer",
                          ("control", "e"): "end-of-buffer",
                          ("meta", "f"): "forward-word",
                          ("meta", "b"): "backward-word",
                          ("control", "d"): "delete-forward-char",
                          ("meta", "d"): "kill-word",
                          ("control", "k"): "kill-line",
                          ("control", "u"): "kill-whole-line",
                          ("control", "y"): "yank",
                          ("meta", "y"): "yank-pop"},
                         aliases=keypad_aliases)

    def __init__(self,
                 prompt="",
                 initial_value="",
                 commit=lambda value: None,
                 rollback=lambda: None,
                 **kwargs):
        super(InputField, self).__init__(**kwargs)

        assert isinstance(self.config, FontConfig)
        assert callable(commit)
        assert callable(rollback)

        self.prompt = unicode(prompt)
        self.buffer = StringBuffer(initial_value, self.kill_ring)
        self.commit = lambda: commit(unicode(self.buffer))
        self.rollback = rollback
        self.key_bindings = KeyBindings(self.keys,
                                        self.manager.keymap,
                                        self.manager.modmap)
        self.button_bindings = ButtonBindings(self.buttons,
                                              self.manager.keymap,
                                              self.manager.modmap)

    def draw(self, x=5):
        super(InputField, self).draw()

        y = self.config.baseline
        def draw_string(x, string):
            text_items = list(textitem16(string))
            self.conn.core.PolyText16(self.window, self.config.fg_gc,
                                      x, y,
                                      len(text_items), "".join(text_items))
            return self.config.text_width(string)
        if self.prompt:
            x += draw_string(x, self.prompt)
        if self.buffer:
            x += draw_string(x, self.buffer)

        # Draw an xor rectangle as a cursor.
        c = self.buffer.point
        n = len(self.buffer)
        x -= self.config.text_width(self.buffer[c:])
        w = self.config.text_width(" " if c >= n else self.buffer[c])
        a = self.config.font_info.font_ascent
        d = self.config.font_info.font_descent
        self.conn.core.PolyFillRectangle(self.window, self.config.xor_gc,
                                         1, [x, y - a, w, a + d])

    def flash(self):
        # Draw an xor rectangle over the entire top-level window, excepting
        # a one-pixel interior border.
        w = self.geometry.width
        h = self.geometry.height
        self.conn.core.PolyFillRectangle(self.window, self.config.xor_gc,
                                         1, [1, 1, w - 2, h - 2])
        def refresh():
            self.draw()
            self.conn.flush()
        timer = Timer(0.15, refresh)
        timer.daemon = True
        timer.start()

    @handler(KeyPressEvent)
    def handle_key_press(self, event,
                         shift=frozenset(["shift"]),
                         modifiers=(XK_Shift_L, XK_Shift_R,
                                    XK_Control_L, XK_Control_R,
                                    XK_Caps_Lock, XK_Shift_Lock,
                                    XK_Meta_L, XK_Meta_R,
                                    XK_Alt_L, XK_Alt_R,
                                    XK_Super_L, XK_Super_R,
                                    XK_Hyper_L, XK_Hyper_R)):
        try:
            action = self.key_bindings[event]
        except KeyError as e:
            # No binding; assume a self-inserting character unless any
            # interesting modifiers are active or the key is itself a
            # modifier.
            symbol, state, press = e.args
            if symbol in modifiers:
                return
            modset = next(self.key_bindings.modsets(state))
            if modset and modset != shift:
                self.flash()
            else:
                char = keysym_to_string(symbol)
                if char:
                    self.buffer.insert_char(char)
                    self.draw()
        else:
            # Actions are strings naming attributes of either ourself or
            # our buffer. The values must be zero-argument functions.
            name = action.replace("-", "_")
            method = getattr(self, name, None)
            if method:
                method()
            else:
                method = getattr(self.buffer, name)
                try:
                    method()
                except (IndexError, CommandError):
                    self.flash()
                else:
                    self.draw()
        raise StopPropagation(event)
