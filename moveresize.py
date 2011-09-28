# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error
from select import select

import xcb
from xcb.xproto import *

from client import ClientWindow
from event import handler, EventHandler, UnhandledEvent
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

    def begin_move(self, client, x, y):
        self.moving, self.resizing = (client, None)
        self.begin_move_resize(client, x, y)

    def begin_resize(self, client, x, y):
        self.moving, self.resizing = (None, client)
        self.size_hints = client.wm_normal_hints
        self.begin_move_resize(client, x, y)

    def begin_move_resize(self, client, x, y, move=True):
        """Shared initialization for move and resize."""
        self.starting_position = (x, y)
        self.starting_geometry = client.geometry

    def move_resize(self, x, y):
        delta_x = x - self.starting_position[0]
        delta_y = y - self.starting_position[1]
        g = self.starting_geometry
        if self.moving:
            x = int16(delta_x + g.x)
            y = int16(delta_y + g.y)
            self.conn.core.ConfigureWindow(self.moving.window,
                                           (ConfigWindow.X | ConfigWindow.Y),
                                           (x, y))
        else:
            min_size = self.size_hints.min_width
            width = int16(max(min_size.width, delta_x + g.width))
            height = int16(max(min_size.height, delta_y + g.height))
            self.conn.core.ConfigureWindow(self.resizing.window,
                                           (ConfigWindow.Width |
                                            ConfigWindow.Height),
                                           (width, height))
        self.conn.flush()

    def end_move_resize(self):
        debug("Ending move/resize")
        self.moving = self.resizing = None

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
        if button == self.move_button:
            self.begin_move(client, event.root_x, event.root_y)
        elif button == self.resize_button:
            self.begin_resize(client, event.root_x, event.root_y)
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
                pointer = self.conn.core.QueryPointer(self.screen.root).reply()
                x, y = (pointer.root_x, pointer.root_y)
            else:
                x, y = (event.root_x, event.root_y)
            self.move_resize(x, y)
        else:
            raise UnhandledEvent(event)
