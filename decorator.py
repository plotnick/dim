# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be decorated with a frame, border, title bar, &c."""

import logging

from xcb.xproto import *

from client import *
from color import *
from event import *
from font import text_width
from geometry import *
from keysym import *
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
        self.border_window = client.window
        self.border_width = border_width
        self.log = logging.getLogger("decorator.0x%x" % self.client.window)

    def decorate(self):
        """Decorate the client window."""
        self.client.offset = self.compute_client_offset()
        self.original_border_width = self.client.geometry.border_width
        self.conn.core.ConfigureWindow(self.border_window,
                                       ConfigWindow.BorderWidth,
                                       [self.border_width])

    def undecorate(self):
        """Remove all decorations from the client window."""
        self.conn.core.ConfigureWindow(self.border_window,
                                       ConfigWindow.BorderWidth,
                                       [self.original_border_width])

        # X11 offers no way of retrieving the border color or pixmap of
        # a window, so we'll simply assume a black border.
        self.conn.core.ChangeWindowAttributes(self.border_window,
                                              CW.BorderPixel,
                                              [self.screen.black_pixel])

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
        """Compute and return a geometry whose position represents the
        offset of the client window with respect to the inside corner of
        the containing frame (which may be the client window itself), and
        whose size is the total additional size required for the desired
        decorations. The border_width attribute is unused."""
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

class FrameDecorator(Decorator):
    """Create a frame (i.e., a new parent) for a client window. This class
    requires a reparenting window manager."""

    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.LeaveWindow)

    def __init__(self, *args, **kwargs):
        super(FrameDecorator, self).__init__(*args, **kwargs)
        self.frame_border_width = self.border_width
        self.border_width = 0

    def decorate(self):
        super(FrameDecorator, self).decorate()

        # Determine the frame geometry based on the current client window
        # geometry and gravity together with the offsets needed for the
        # actual decoration.
        offset = self.client.offset
        gravity = self.client.properties.wm_normal_hints.win_gravity
        geometry = self.client.absolute_geometry
        frame_geometry = geometry.resize(geometry.size() + offset.size(),
                                         self.frame_border_width,
                                         gravity)

        frame = self.conn.generate_id()
        window = self.client.window
        self.log.debug("Creating frame 0x%x.", frame)
        self.conn.core.CreateWindow(self.screen.root_depth, frame,
                                    self.screen.root,
                                    frame_geometry.x, frame_geometry.y,
                                    frame_geometry.width, frame_geometry.height,
                                    frame_geometry.border_width,
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    CW.OverrideRedirect | CW.EventMask,
                                    [True, self.frame_event_mask])
        self.conn.core.ReparentWindow(window, frame, offset.x, offset.y)
        self.conn.core.ChangeSaveSet(SetMode.Insert, window)

        # When the reparenting is complete, the manager will update the
        # class of the client to reflect its new status. We'll set the
        # frame attribute now, though, so that interested parties can
        # use it immediately.
        self.client.reparenting = FramedClientWindow
        self.client.frame = frame

        # Changes to the border should now be applied to the frame.
        self.border_window = frame

    def undecorate(self):
        if isinstance(self.client, FramedClientWindow):
            self.conn.core.UnmapWindow(self.client.frame)
            self.border_window = self.client.window

            super(FrameDecorator, self).undecorate()

            # Determine the new window geometry based on the current frame
            # geometry, the original border width, and the window gravity.
            size = self.client.geometry.size()
            bw = self.original_border_width
            gravity = self.client.properties.wm_normal_hints.win_gravity
            geometry = self.client.frame_geometry.resize(size, bw, gravity)

            self.conn.core.ReparentWindow(self.client.window, self.screen.root,
                                          geometry.x, geometry.y)
            self.conn.core.ChangeSaveSet(SetMode.Delete, self.client.window)
            self.conn.core.DestroyWindow(self.client.frame)
            self.client.reparenting = ClientWindow
            self.client.frame = None

class TitlebarConfig(object):
    def __init__(self, manager, fg_color, bg_color, font):
        assert isinstance(fg_color, Color)
        assert isinstance(bg_color, Color)
        assert isinstance(font, (str, int))

        self.manager = manager
        self.fg_color = fg_color
        self.bg_color = bg_color
        self.font = manager.fonts[font] if isinstance(font, str) else font
        self.font_info = manager.fonts.info(self.font)

        conn = manager.conn
        root = manager.screen.root

        # Padding is based on the font descent, plus 2 pixels for the relief
        # edge, with a small scaling factor.
        pad = (self.font_info.font_descent + 2) * 6 // 5
        self.height = (2 * pad +
                       self.font_info.font_ascent +
                       self.font_info.font_descent)
        self.baseline = pad + self.font_info.font_ascent

        self.black_gc = manager.black_gc
        self.fg_gc = conn.generate_id()
        conn.core.CreateGC(self.fg_gc, root,
                           GC.Foreground | GC.Background | GC.Font,
                           [manager.colors[fg_color],
                            manager.colors[bg_color],
                            self.font])
        self.bg_gc = conn.generate_id()
        conn.core.CreateGC(self.bg_gc, root,
                           GC.Foreground | GC.Background | GC.Font,
                           [manager.colors[bg_color],
                            manager.colors[fg_color],
                            self.font])

        high, low = self.highlight(bg_color)
        self.highlight_gc = conn.generate_id()
        conn.core.CreateGC(self.highlight_gc, root,
                           GC.Foreground, [manager.colors[high]])
        self.lowlight_gc = conn.generate_id()
        conn.core.CreateGC(self.lowlight_gc, root,
                           GC.Foreground, [manager.colors[low]])

    @staticmethod
    def highlight(color):
        h, s, v = color.hsv()
        return (HSVColor(h, s, (3.0 + v) / 4.0),
                HSVColor(h, s, (2.0 + v) / 5.0))

    def text_width(self, string):
        return text_width(self.font_info, string)

    def reversed(self):
        rev = self.__class__(self.manager,
                             self.bg_color, self.fg_color,
                             self.font)
        rev.highlight_gc, rev.lowlight_gc = rev.lowlight_gc, rev.highlight_gc
        return rev

class Titlebar(EventHandler):
    """A widget which displays a line of text. A titlebar need not display
    a window title; it can be used for other purposes."""

    event_mask = (EventMask.Exposure |
                  EventMask.ButtonPress)

    def __init__(self,
                 conn=None, client=None, manager=None,
                 parent=None, geometry=None, config=None):
        self.conn = conn
        self.client = client
        self.manager = manager
        self.geometry = geometry
        self.config = config
        self.button_press_handlers = {}

        self.window = self.conn.generate_id()
        self.conn.core.CreateWindow(manager.screen.root_depth,
                                    self.window, parent,
                                    geometry.x, geometry.y,
                                    geometry.width, geometry.height,
                                    geometry.border_width,
                                    WindowClass.InputOutput,
                                    manager.screen.root_visual,
                                    CW.OverrideRedirect | CW.EventMask,
                                    [True, self.event_mask])
        manager.register_window_handler(self.window, self)
        self.conn.core.MapWindow(self.window)

    def configure(self, geometry):
        self.geometry = geometry
        self.conn.core.ConfigureWindow(self.window,
                                       ConfigWindow.Width,
                                       [geometry.width])

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

    @handler(ExposeEvent)
    def handle_expose(self, event):
        if event.count == 0:
            self.draw()

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        self.button_press_handlers.get(event.detail, lambda event: None)(event)

    def register_button_press_handler(self, button, handler):
        self.button_press_handlers[button] = handler

class SimpleTitlebar(Titlebar):
    """A titlebar that displays the window title."""

    event_mask = (EventMask.StructureNotify |
                  EventMask.Exposure |
                  EventMask.ButtonPress)

    def __init__(self, title="", **kwargs):
        self.title = title
        super(SimpleTitlebar, self).__init__(**kwargs)

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

class InputFieldTitlebar(Titlebar):
    """A one-line, editable input field."""

    event_mask = (EventMask.StructureNotify |
                  EventMask.Exposure |
                  EventMask.ButtonPress |
                  EventMask.KeyPress |
                  EventMask.FocusChange)

    def __init__(self, prompt="", initial_value="",
                 commit=lambda value: None, rollback=lambda: None,
                 **kwargs):
        self.prompt = unicode(prompt)
        self.value = unicode(initial_value)
        self.commit = commit
        self.rollback = rollback
        super(InputFieldTitlebar, self).__init__(**kwargs)

    def draw(self, x=5):
        super(InputFieldTitlebar, self).draw()

        def draw_string(x, string):
            text_items = list(textitem16(string))
            self.conn.core.PolyText16(self.window, self.config.fg_gc,
                                      x, self.config.baseline,
                                      len(text_items), "".join(text_items))
        if self.prompt:
            draw_string(x, self.prompt)
            x += self.config.text_width(self.prompt)
        if self.value:
            draw_string(x, self.value)

    @handler(MapNotifyEvent)
    def handle_map_notify(self, event):
        self.client.focus_override = self.window
        if self.manager.current_focus == self.client:
            # Override client focus.
            self.client.focus()

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        self.client.focus_override = None
        if self.manager.current_focus == self.client:
            # Revert focus to the client window.
            self.client.focus()

    @handler(KeyPressEvent)
    def handle_keypress(self, event):
        keysym = self.manager.keymap.lookup_key(event.detail, event.state)
        if keysym == XK_Escape:
            self.rollback()
        elif keysym == XK_Return:
            self.commit(self.value)
        elif keysym == XK_BackSpace:
            self.value = self.value[:-1]
            self.draw()
        else:
            self.value += keysym_to_string(keysym)
            self.draw()

class TitlebarDecorator(FrameDecorator):
    """Decorate a client with a multi-purpose titlebar."""

    def __init__(self, conn, client,
                 focused_config=None, unfocused_config=None,
                 button_press_handlers={},
                 **kwargs):
        assert (isinstance(focused_config, TitlebarConfig) and
                isinstance(unfocused_config, TitlebarConfig))
        self.titlebar = None
        self.titlebar_configs = (unfocused_config, focused_config)
        self.button_press_handlers = button_press_handlers
        super(TitlebarDecorator, self).__init__(conn, client, **kwargs)

    def decorate(self):
        super(TitlebarDecorator, self).decorate()
        if not self.titlebar:
            config = self.titlebar_configs[0]
            geometry = Geometry(0, 0,
                                self.client.geometry.width, config.height, 0)
            self.titlebar = SimpleTitlebar(conn=self.conn,
                                           client=self.client,
                                           manager=self.client.manager,
                                           parent=self.client.frame,
                                           geometry=geometry,
                                           config=config)
            for button, handler in self.button_press_handlers.items():
                self.titlebar.register_button_press_handler(button, handler)

    def undecorate(self):
        if self.titlebar:
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
                       config=None):
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
        self.titlebar = InputFieldTitlebar(conn=self.conn,
                                           client=self.client,
                                           manager=self.client.manager,
                                           parent=self.client.frame,
                                           geometry=titlebar.geometry,
                                           config=config,
                                           prompt=prompt,
                                           initial_value=initial_value,
                                           commit=commit,
                                           rollback=restore_titlebar)
