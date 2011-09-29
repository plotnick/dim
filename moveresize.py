# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error
from select import select

import xcb
from xcb.xproto import *

from client import ClientWindow
from event import handler, EventHandler, UnhandledEvent
from geometry import *
from manager import WindowManager, compress
from xutil import *

class ConfigureClient(object):
    def __init__(self, client):
        self.client = client

    def update(self, delta):
        pass
            
    def commit(self):
        pass

    def rollback(self):
        pass

class MoveClient(ConfigureClient):
    def __init__(self, client):
        super(MoveClient, self).__init__(client)
        self.position = Position(client.geometry.x, client.geometry.y)

    def update(self, delta):
        self.client.move(self.position + delta)

    def rollback(self):
        self.client.move(self.position)

class ResizeClient(ConfigureClient):
    def __init__(self, client):
        super(ResizeClient, self).__init__(client)
        self.size = Rectangle(client.geometry.width, client.geometry.height)
        self.size_hints = client.wm_normal_hints

    def update(self, delta):
        self.client.resize(constrain_size(self.size + delta, self.size_hints))

    def rollback(self):
        self.client.resize(self.size)

class MoveResize(WindowManager):
    GRAB_EVENT_MASK = (EventMask.ButtonPress |
                       EventMask.ButtonRelease |
                       EventMask.ButtonMotion |
                       EventMask.PointerMotionHint)

    def __init__(self, conn, screen=None,
                 mod_key=8, move_button=1, resize_button=3):
        assert mod_key != 0, "Invalid modifier key for move/resize"
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
                                             button, mod_key).check()

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
            self.configuring = MoveClient(client)
        elif button == self.resize_button:
            self.configuring = ResizeClient(client)
        else:
            raise UnhandledEvent(event)

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        if self.configuring:
            try:
                self.configuring.commit()
            except:
                self.configuring.rollback()
            finally:
                self.configuring = None
        else:
            raise UnhandledEvent(event)

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if self.configuring:
            if event.detail == Motion.Hint:
                q = self.conn.core.QueryPointer(self.screen.root).reply()
                p = Position(q.root_x, q.root_y)
            else:
                p = Position(event.root_x, event.root_y)
            self.configuring.update(p - self.button_press)
        else:
            raise UnhandledEvent(event)
