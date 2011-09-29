# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error
from select import select

import xcb
from xcb.xproto import *

from client import ClientWindow
from event import handler, EventHandler, UnhandledEvent
from geometry import *
from keysym import *
from manager import WindowManager, compress
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
    def __init__(self, client, *args):
        super(ResizeClient, self).__init__(client, *args)
        self.size = Rectangle(client.geometry.width, client.geometry.height)
        self.size_hints = client.wm_normal_hints

    def update(self, delta):
        self.client.resize(constrain_size(self.size + delta, self.size_hints))

    def rollback(self):
        self.client.resize(self.size)
        super(ResizeClient, self).rollback()

class MoveResize(WindowManager):
    GRAB_EVENT_MASK = (EventMask.ButtonPress |
                       EventMask.ButtonRelease |
                       EventMask.ButtonMotion |
                       EventMask.PointerMotionHint)

    def __init__(self, conn,
                 screen=None,
                 modifier=ModMask._1,
                 move_button=ButtonIndex._1,
                 resize_button=ButtonIndex._3):
        assert modifier != 0, "Invalid modifier key for move/resize"
        assert move_button != resize_button, \
            "Can't have move and resize on the same button"

        super(MoveResize, self).__init__(conn, screen)

        self.moving = None
        self.move_button = move_button
        self.resize_button = resize_button

        for button in (move_button, resize_button):
            self.conn.core.GrabButtonChecked(False, self.screen.root,
                                             self.GRAB_EVENT_MASK,
                                             GrabMode.Async, GrabMode.Async,
                                             self.screen.root, Cursor._None,
                                             button, modifier).check()

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        if not event.child:
            debug("Ignoring button %d press in root window" % button)
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
                                           self.grab_keyboard,
                                           self.ungrab_keyboard)
        else:
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
        if self.keymap[event.detail] == XK_Escape:
            try:
                self.moveresize.rollback()
            finally:
                self.moveresize = None
