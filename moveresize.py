# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error

import xcb
from xcb.xproto import *

from client import ClientWindow
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

        # Determine which quadrant of the client window the initial button
        # press occurred in. A quadrant is a represented by a position whose
        # coordinates are ±1:
        #     ┌──────────┬──────────┐
        #     │ (-1, -1) │ (+1, -1) │
        #     ├──────────┼──────────┤
        #     │ (-1, +1) │ (+1, +1) │
        #     └──────────┴──────────┘
        midpoint = Position(self.geometry.x + self.geometry.width // 2,
                            self.geometry.y + self.geometry.height // 2)
        self.quadrant = Position(1 if point.x - midpoint.x >= 0 else -1,
                                 1 if point.y - midpoint.y >= 0 else -1)

    def update(self, delta):
        delta = Position(delta.x * self.quadrant.x, delta.y * self.quadrant.y)
        old_size = Rectangle(self.geometry.width, self.geometry.height)
        new_size = constrain_size(old_size + delta, self.size_hints)
        if new_size != old_size:
            offset = Position(new_size.width - old_size.width \
                                  if self.quadrant.x < 0 \
                                  else 0,
                              new_size.height - old_size.height \
                                  if self.quadrant.y < 0 \
                                  else 0)
            self.client.update_geometry(self.geometry.resize(new_size) - offset)

    def rollback(self):
        self.client.update_geometry(self.geometry)
        super(ResizeClient, self).rollback()

class MoveResize(WindowManager):
    __GRAB_EVENT_MASK = (EventMask.ButtonPress |
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
        self.moving = None
        
        kwargs.update(grab_buttons=grab_buttons.merge({
            (self.move_button, self.move_resize_mods): self.__GRAB_EVENT_MASK,
            (self.resize_button, self.move_resize_mods): self.__GRAB_EVENT_MASK
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
        raise UnhandledEvent(event)

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
