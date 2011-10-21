# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error

from xcb.xproto import *

from client import ClientWindow
from cursor import *
from event import UnhandledEvent, handler
from geometry import *
from keysym import *
from manager import WindowManager, compress
from xutil import *

class ClientUpdate(object):
    """A transactional client configuration change."""

    def __init__(self, client, start=lambda: None, end=lambda: None):
        self.client = client
        self.end = end
        start()

    def update(self, delta):
        pass
            
    def commit(self):
        self.end()

    def rollback(self):
        self.end()

class ClientMove(ClientUpdate):
    cursor = XC_fleur

    def __init__(self, client, *args):
        super(ClientMove, self).__init__(client, *args)
        self.position = Position(client.geometry.x, client.geometry.y)

    def update(self, delta):
        self.client.move(self.position + delta)

    def rollback(self):
        self.client.move(self.position)
        super(ClientMove, self).rollback()

class ClientResize(ClientUpdate):
    def __init__(self, client, point, *args):
        super(ClientResize, self).__init__(client, *args)
        self.geometry = client.geometry
        self.size_hints = client.wm_normal_hints

        # We'll use the offset gravity representation; see comment in the
        # geometry module for details. Technically, this is anti-gravity,
        # since we'll be moving the specified reference point instead of
        # keeping it fixed, but the concept is the same.
        def third(point, start, length):
            thirds = (start + length // 3, start + 2 * length // 3)
            return (-1 if point < thirds[0] else
                     0 if point < thirds[1] else
                     1)
        offset = (third(point.x, self.geometry.x, self.geometry.width),
                  third(point.y, self.geometry.y, self.geometry.height))
        self.gravity = Position(*offset)

    def update(self, delta):
        if self.gravity == (0, 0):
            # Center gravity is just a move.
            self.client.move(self.geometry.position() + delta)
            return

        # Depending on the gravity, resizing may involve a move, too.
        size = self.geometry.size()
        dsize = Rectangle(delta.x * self.gravity.x, delta.y * self.gravity.y)
        new_size = self.size_hints.constrain_window_size(size + dsize)
        offset = (new_size.width - size.width if self.gravity.x < 0 else 0,
                  new_size.height - size.height if self.gravity.y < 0 else 0)
        self.client.update_geometry(self.geometry.resize(new_size) - offset)

    @property
    def cursor(self, cursors={(-1, -1): XC_top_left_corner,
                              (+0, -1): XC_top_side,
                              (+1, -1): XC_top_right_corner,
                              (-1, +0): XC_left_side,
                              (+0, +0): XC_fleur,
                              (+1, +0): XC_right_side,
                              (-1, +1): XC_bottom_left_corner,
                              (+0, +1): XC_bottom_side,
                              (+1, +1): XC_bottom_right_corner}):
        return cursors[self.gravity]

    def rollback(self):
        self.client.update_geometry(self.geometry)
        super(ClientResize, self).rollback()

class MoveResize(WindowManager):
    __grab_event_mask = (EventMask.ButtonPress |
                         EventMask.ButtonRelease |
                         EventMask.ButtonMotion |
                         EventMask.PointerMotionHint)

    def __init__(self, conn, screen=None,
                 move_resize_mods=ModMask._1, move_button=1, resize_button=3,
                 grab_buttons=GrabButtons(),
                 **kwargs):
        assert move_resize_mods != 0, \
            "Invalid modifiers for move/resize"
        assert move_button != resize_button, \
            "Can't have move and resize on the same button"
        self.move_resize_mods = move_resize_mods
        self.move_button = move_button
        self.resize_button = resize_button
        self.client_update = None
        
        kwargs.update(grab_buttons=grab_buttons.merge({
            (self.move_button, self.move_resize_mods): self.__grab_event_mask,
            (self.resize_button, self.move_resize_mods): self.__grab_event_mask
        }))
        super(MoveResize, self).__init__(conn, screen, **kwargs)

    def change_cursor(self, cursor):
        self.conn.core.ChangeActivePointerGrab(self.cursors[cursor],
                                               Time.CurrentTime,
                                               self.__grab_event_mask)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        modifiers = event.state & 0xff
        window = event.child

        if not window or \
                modifiers != self.move_resize_mods or \
                button not in (self.move_button, self.resize_button):
            raise UnhandledEvent(event)

        client = self.get_client(window)
        self.button_press = Position(event.root_x, event.root_y)
        if button == self.move_button:
            self.client_update = ClientMove(client,
                                            self.grab_keyboard,
                                            self.ungrab_keyboard)
        elif button == self.resize_button:
            self.client_update = ClientResize(client,
                                              self.button_press,
                                              self.grab_keyboard,
                                              self.ungrab_keyboard)
        self.change_cursor(self.client_update.cursor)
        raise UnhandledEvent(event)

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        if not self.client_update:
            raise UnhandledEvent(event)
        try:
            self.client_update.commit()
        except:
            self.client_update.rollback()
        finally:
            self.client_update = None

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if not self.client_update:
            raise UnhandledEvent(event)
        if event.detail == Motion.Hint:
            q = self.conn.core.QueryPointer(self.screen.root).reply()
            p = Position(q.root_x, q.root_y)
        else:
            p = Position(event.root_x, event.root_y)
        self.client_update.update(p - self.button_press)

    @handler(KeyPressEvent)
    def handle_key_press(self, event):
        if not self.client_update:
            raise UnhandledEvent(event)
        if XK_Escape in self.keymap[event.detail]:
            try:
                self.client_update.rollback()
            finally:
                self.client_update = None
