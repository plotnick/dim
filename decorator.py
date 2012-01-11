# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

from collections import deque
import logging
from threading import Timer

from xcb.xproto import *

from bindings import *
from client import *
from event import *
from geometry import *
from keysym import *
from stringbuffer import *
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

    def __init__(self, client=None, **kwargs):
        super(Titlebar, self).__init__(**kwargs)

        self.client = client

    def create_window(self, **kwargs):
        kwargs["event_mask"] = self.event_mask
        kwargs["override_redirect"] = True
        return super(Titlebar, self).create_window(**kwargs)

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

class AbortEdit(Exception):
    pass

class InputFieldTitlebar(Titlebar):
    """A one-line, editable input field."""

    event_mask = (EventMask.StructureNotify |
                  EventMask.Exposure |
                  EventMask.ButtonPress |
                  EventMask.KeyPress |
                  EventMask.FocusChange)

    key_bindings = KeyBindingMap({XK_Return: "commit",
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
    button_bindings = ButtonBindingMap({})
    kill_ring = deque([], 10)

    def __init__(self,
                 prompt="",
                 initial_value="",
                 commit=lambda value: None,
                 rollback=lambda: None,
                 time=Time.CurrentTime,
                 key_bindings=key_bindings,
                 button_bindings=button_bindings,
                 **kwargs):
        super(InputFieldTitlebar, self).__init__(**kwargs)
        self.prompt = unicode(prompt)
        self.buffer = StringBuffer(initial_value, self.kill_ring)
        self.commit = lambda: commit(unicode(self.buffer))
        self.rollback = rollback
        self.time = time
        self.key_bindings = KeyBindings(key_bindings,
                                        self.manager.keymap,
                                        self.manager.modmap)
        self.button_bindings = ButtonBindings(button_bindings,
                                              self.manager.keymap,
                                              self.manager.modmap,
                                              self.manager.butmap)

    def draw(self, x=5):
        super(InputFieldTitlebar, self).draw()
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
        # Draw an xor rectangle over the non-relief portion of the titlebar.
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
    def handle_key_press(self, event, shift=frozenset(["shift"])):
        self.time = event.time
        try:
            action = self.key_bindings[event]
        except KeyError as e:
            # No binding; assume a self-inserting character unless any
            # interesting modifiers are present.
            symbol, state = e.args
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
            self.conn.core.DestroyWindow(self.titlebar.window)
            self.conn.core.MapWindow(titlebar.window)
            self.titlebar = titlebar
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
