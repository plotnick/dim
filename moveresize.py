# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error

import xcb
from xcb.xproto import *

from client import ClientWindow
from cursor import *
from event import handler, EventHandler, UnhandledEvent
from geometry import *
from keysym import *
from manager import WindowManager, compress, GrabButtons
from xutil import *

class ConfigureClient(object):
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

class MoveClient(ConfigureClient):
    cursor = XC_fleur

    def __init__(self, client, *args):
        super(MoveClient, self).__init__(client, *args)
        self.position = Position(client.geometry.x, client.geometry.y)

    def update(self, delta):
        self.client.move(self.position + delta)

    def rollback(self):
        self.client.move(self.position)
        super(MoveClient, self).rollback()

class ResizeClient(ConfigureClient):
    def __init__(self, client, point, *args):
        super(ResizeClient, self).__init__(client, *args)
        self.geometry = client.geometry
        self.size_hints = client.wm_normal_hints

        # Determine which octant of the client window the initial button
        # press occurred in. An octant is a represented by a position whose
        # coordinates are ±1 or 0:
        #     ┌──────┬──────┬──────┐
        #     │ -1-1 │ +0-1 │ +1-1 │
        #     ├──────┼──────┼──────┤
        #     │ -1+0 │ +1+1 │ +1+0 │
        #     ├──────┼──────┼──────┤
        #     │ -1+1 │ +0+1 │ +1+1 │
        #     └──────┴──────┴──────┘
        # (Yes, Virginia, there are nine octants. But two of them are the
        # same, and so there are effectively only eight.)
        def third(point, start, length):
            thirds = (start + length // 3, start + 2 * length // 3)
            return (-1 if point < thirds[0] else
                     0 if point < thirds[1] else
                     1)
        octant = (third(point.x, self.geometry.x, self.geometry.width),
                  third(point.y, self.geometry.y, self.geometry.height))
        self.octant = Position(*(octant if octant != (0, 0) else (+1, +1)))

    def update(self, delta):
        delta = Position(delta.x * self.octant.x, delta.y * self.octant.y)
        old_size = Rectangle(self.geometry.width, self.geometry.height)
        new_size = constrain_size(old_size + delta, self.size_hints)
        if new_size != old_size:
            offset = Position(new_size.width - old_size.width \
                                  if self.octant.x < 0 \
                                  else 0,
                              new_size.height - old_size.height \
                                  if self.octant.y < 0 \
                                  else 0)
            self.client.update_geometry(self.geometry.resize(new_size) - offset)

    @property
    def cursor(self, cursors={(+0, +0): XC_cross,
                              (-1, -1): XC_top_left_corner,
                              (+0, -1): XC_top_side,
                              (+1, -1): XC_top_right_corner,
                              (+1, +0): XC_right_side,
                              (+1, +1): XC_bottom_right_corner,
                              (+0, +1): XC_bottom_side,
                              (-1, +1): XC_bottom_left_corner,
                              (-1, +0): XC_left_side}):
        return cursors[self.octant]

    def rollback(self):
        self.client.update_geometry(self.geometry)
        super(ResizeClient, self).rollback()

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
        self.moveresize = None
        
        kwargs.update(grab_buttons=grab_buttons.merge({
            (self.move_button, self.move_resize_mods): self.__grab_event_mask,
            (self.resize_button, self.move_resize_mods): self.__grab_event_mask
        }))
        super(MoveResize, self).__init__(conn, screen, **kwargs)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        modifiers = event.state & 0xff
        window = event.child

        if not window or \
                modifiers != self.move_resize_mods or \
                button not in (self.move_button, self.resize_button):
            raise UnhandledEvent(event)

        try:
            client = self.clients[event.child]
        except KeyError:
            raise UnhandledEvent(event)

        self.button_press = Position(event.root_x, event.root_y)
        if button == self.move_button:
            self.moveresize = MoveClient(client,
                                         self.grab_keyboard,
                                         self.ungrab_keyboard)
        elif button == self.resize_button:
            self.moveresize = ResizeClient(client,
                                           self.button_press,
                                           self.grab_keyboard,
                                           self.ungrab_keyboard)
        self.change_cursor(self.moveresize.cursor)
        raise UnhandledEvent(event)

    def change_cursor(self, cursor):
        self.conn.core.ChangeActivePointerGrabChecked(self.cursors[cursor],
            Time.CurrentTime, self.__grab_event_mask).check()

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        if not self.moveresize:
            raise UnhandledEvent(event)
        try:
            self.moveresize.commit()
        except:
            self.moveresize.rollback()
        finally:
            self.moveresize = None

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if not self.moveresize:
            raise UnhandledEvent(event)
        if event.detail == Motion.Hint:
            q = self.conn.core.QueryPointer(self.screen.root).reply()
            p = Position(q.root_x, q.root_y)
        else:
            p = Position(event.root_x, event.root_y)
        self.moveresize.update(p - self.button_press)

    @handler(KeyPressEvent)
    def handle_key_press(self, event):
        if not self.moveresize:
            raise UnhandledEvent(event)
        if XK_Escape in self.keymap[event.detail]:
            try:
                self.moveresize.rollback()
            finally:
                self.moveresize = None
