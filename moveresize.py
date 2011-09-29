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

    def begin_move(self, client):
        self.moving = client
        self.initial_position = Position(client.geometry.x,
                                         client.geometry.y)

    def begin_resize(self, client):
        self.resizing = client
        self.size_hints = client.wm_normal_hints
        self.initial_size = Rectangle(client.geometry.width,
                                      client.geometry.height)

    def move_resize(self, delta):
        if self.moving:
            new_position = self.initial_position + delta
            self.conn.core.ConfigureWindow(self.moving.window,
                                           (ConfigWindow.X | ConfigWindow.Y),
                                           map(int16, new_position))
        elif self.resizing:
            new_size = constrain_size(self.initial_size + delta,
                                      self.size_hints)
            self.conn.core.ConfigureWindow(self.resizing.window,
                                           (ConfigWindow.Width |
                                            ConfigWindow.Height),
                                           map(int16, new_size))
        else:
            warning("Neither moving nor resizing, but in move_resize.")
        self.conn.flush()

    def end_move_resize(self):
        debug("Ending move/resize")
        self.moving = self.resizing = None
        self.initial_position = None
        self.initial_size = None
        self.size_hints = None

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
            self.begin_move(client)
        elif button == self.resize_button:
            self.begin_resize(client)
        else:
            raise UnhandledEvent(event)

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        if self.moving or self.resizing:
            self.end_move_resize()
        else:
            raise UnhandledEvent(event)

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if self.moving or self.resizing:
            if event.detail == Motion.Hint:
                q = self.conn.core.QueryPointer(self.screen.root).reply()
                p = Position(q.root_x, q.root_y)
            else:
                p = Position(event.root_x, event.root_y)
            self.move_resize(p - self.button_press)
        else:
            raise UnhandledEvent(event)
