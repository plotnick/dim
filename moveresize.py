# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error
from select import select
from struct import pack, unpack

import xcb
from xcb.xproto import *

from client import ClientWindow
from event import handler, EventHandler
from manager import WindowManager
from xutil import *

class MoveResize(WindowManager):
    GRAB_EVENT_MASK = (EventMask.ButtonPress |
                       EventMask.ButtonRelease |
                       EventMask.ButtonMotion |
                       EventMask.PointerMotionHint)

    def __init__(self, conn, screen=None, mod_key=8):
        super(MoveResize, self).__init__(conn, screen)

        self.moving = None

        for button in (1, 2, 3):
            self.conn.core.GrabButtonChecked(False, self.screen.root,
                                             self.GRAB_EVENT_MASK,
                                             GrabMode.Async, GrabMode.Async,
                                             self.screen.root, Cursor._None,
                                             button, mod_key).check()

    def begin_move(self, client, x, y):
        debug("Beginning move of client 0x%x" % client.window)
        geometry = self.conn.core.GetGeometry(client.window).reply()
        if geometry:
            self.offset = (x - geometry.x, y - geometry.y)
            self.moving = client

    def move(self, x, y):
        self.conn.core.ConfigureWindow(self.moving.window,
            ConfigWindow.X | ConfigWindow.Y,
            (int16(x - self.offset[0]), int16(y - self.offset[1])))

    def end_move(self):
        debug("Ending move of client 0x%x" % self.moving.window)
        self.moving = None

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        if not event.child:
            debug("Ignoring button %d press in root window" % button)
            return
        try:
            client = self.clients[event.child]
        except KeyError:
            debug("Ignoring button %d press in non-managed window" % button)
            return
        debug("Button %d pressed in window 0x%x at (%d, %d)" %
              (button, event.child, event.root_x, event.root_y))
        if button == 1:
            self.begin_move(client, event.root_x, event.root_y)

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        debug("Button %d released" % event.detail)
        if self.moving:
            self.end_move()

    @handler(MotionNotifyEvent)
    def handle_motion_notify(self, event):
        if self.moving:
            if event.detail == Motion.Hint:
                pointer = self.conn.core.QueryPointer(self.screen.root).reply()
                if pointer:
                    self.move(pointer.root_x, pointer.root_y)
            else:
                self.move(event.root_x, event.root_y)
