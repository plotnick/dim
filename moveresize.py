# -*- mode: Python; coding: utf-8 -*-

import logging

from xcb.xproto import *

from cursor import *
from event import UnhandledEvent, handler
from geometry import *
from keysym import *
from manager import WindowManager, compress
from properties import WMSizeHints
from xutil import *

__all__ = ["MoveResize"]

log = logging.getLogger("moveresize")

class ClientUpdate(object):
    """A transactional client configuration change."""

    def __init__(self, client, pointer, cleanup, change_cursor):
        self.client = client
        self.pointer = pointer
        self.cleanup = cleanup
        self.change_cursor = change_cursor
        self.geometry = client.absolute_geometry
        self.frame_geometry = client.frame_geometry

    def delta(self, pointer):
        return pointer - self.pointer

    def update(self, pointer):
        pass
            
    def commit(self, time):
        self.cleanup(time)
        self.client.decorator.message(None)

    def rollback(self, time):
        self.cleanup(time)
        self.client.decorator.message(None)

    def display_geometry(self, geometry):
        self.client.decorator.message(geometry)

    def cycle_gravity(self, pointer, time):
        pass

class ClientMove(ClientUpdate):
    cursor = XC_fleur

    def __init__(self, *args):
        super(ClientMove, self).__init__(*args)
        self.position = self.frame_geometry.position()
        self.change_cursor(self.cursor)
        self.display_geometry(self.position)

    def update(self, pointer):
        position = self.position + self.delta(pointer)
        self.client.move(position)
        self.display_geometry(position)

    def rollback(self, time=Time.CurrentTime):
        self.client.move(self.position)
        super(ClientMove, self).rollback(time)

class ClientResize(ClientUpdate):
    # Indexed by gravity offset.
    cursors = {(-1, -1): XC_top_left_corner,
               (+0, -1): XC_top_side,
               (+1, -1): XC_top_right_corner,
               (-1, +0): XC_left_side,
               (+0, +0): XC_fleur,
               (+1, +0): XC_right_side,
               (-1, +1): XC_bottom_left_corner,
               (+0, +1): XC_bottom_side,
               (+1, +1): XC_bottom_right_corner}

    def __init__(self, *args):
        super(ClientResize, self).__init__(*args)
        self.initial_geometry = self.geometry
        self.size_hints = self.client.wm_normal_hints

        # We'll use the offset gravity representation; see comment in the
        # geometry module for details. Technically, this is anti-gravity,
        # since we'll be moving the specified reference point instead of
        # keeping it fixed, but the concept is the same.
        def third(pointer, start, length):
            thirds = (start + length // 3, start + 2 * length // 3)
            return (-1 if pointer < thirds[0] else
                     0 if pointer < thirds[1] else
                     1)
        offset = (third(self.pointer.x, self.geometry.x, self.geometry.width),
                  third(self.pointer.y, self.geometry.y, self.geometry.height))
        self.gravity = Position(*offset)
        self.change_cursor(self.cursors[self.gravity])
        self.display_geometry(self.initial_geometry)

    def update(self, pointer):
        delta = self.delta(pointer)

        # Treat center gravity as just a move.
        if self.gravity == (0, 0):
            position = self.frame_geometry.position() + delta
            self.client.move(position)
            self.display_geometry(position)
            return

        ds = Rectangle(delta.x * self.gravity.x, delta.y * self.gravity.y)
        size = self.client.resize(self.geometry.size() + ds,
                                  gravity=offset_gravity[-self.gravity]).size()
        self.display_geometry(size)

    def rollback(self, time=Time.CurrentTime):
        self.client.configure(self.initial_geometry)
        super(ClientResize, self).rollback(time)

    def display_geometry(self, geometry):
        display = super(ClientResize, self).display_geometry
        def display_size(size):
            display(self.size_hints.size_increments(size)
                    if self.size_hints.flags & WMSizeHints.PResizeInc
                    else size)
        if isinstance(geometry, Geometry):
            if self.gravity == (0, 0):
                display(geometry.position())
            else:
                display_size(geometry.size())
        elif isinstance(geometry, Position):
            display(geometry)
        elif isinstance(geometry, Rectangle):
            display_size(geometry)

    def cycle_gravity(self, pointer, time,
                      gravities=sorted(offset_gravity,
                                       key=lambda x: x.phase())):
        i = gravities.index(self.gravity)
        self.gravity = gravities[(i + 1) % len(gravities)]
        self.change_cursor(self.cursors[self.gravity], time)
        self.geometry = self.client.geometry
        self.display_geometry(self.geometry)
        self.pointer = pointer

class MoveResize(WindowManager):
    __grab_event_mask = (EventMask.ButtonPress |
                         EventMask.ButtonRelease |
                         EventMask.ButtonMotion |
                         EventMask.PointerMotionHint)

    def __init__(self, display=None, screen=None,
                 move_resize_mods=ModMask._1, move_button=1, resize_button=3,
                 grab_buttons=GrabButtons(),
                 **kwargs):
        assert move_resize_mods != 0, \
            "Invalid modifiers for move/resize"
        assert move_button != resize_button, \
            "Can't have move and resize on the same button"
        self.__modifiers = move_resize_mods
        self.__buttons = {move_button: ClientMove, resize_button: ClientResize}
        self.moveresize = None
        
        kwargs.update(grab_buttons=grab_buttons.merge({
            (move_button, move_resize_mods): self.__grab_event_mask,
            (resize_button, move_resize_mods): self.__grab_event_mask
        }))
        super(MoveResize, self).__init__(display, screen, **kwargs)

    def query_pointer(self):
        """Return the current pointer position."""
        reply = self.conn.core.QueryPointer(self.screen.root).reply()
        return Position(reply.root_x, reply.root_y)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        button = event.detail
        modifiers = event.state & 0xff
        window = event.child

        if not window or \
                modifiers != self.__modifiers or \
                button not in self.__buttons:
            raise UnhandledEvent(event)

        self.conn.core.GrabKeyboard(False, self.screen.root, event.time,
                                    GrabMode.Async, GrabMode.Async)

        def ungrab(time=Time.CurrentTime):
            self.conn.core.UngrabPointer(time)
            self.conn.core.UngrabKeyboard(time)
        def change_cursor(cursor, time=Time.CurrentTime):
            self.conn.core.ChangeActivePointerGrab(self.cursors[cursor], time,
                                                   self.__grab_event_mask)
        action = self.__buttons[button]
        self.moveresize = action(self.get_client(window),
                                 Position(event.root_x, event.root_y),
                                 ungrab, change_cursor)

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        if not self.moveresize:
            raise UnhandledEvent(event)
        self.moveresize.commit(event.time)
        self.moveresize = None

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if not self.moveresize:
            raise UnhandledEvent(event)
        self.moveresize.update(self.query_pointer() \
                                   if event.detail == Motion.Hint \
                                   else Position(event.root_x, event.root_y))

    @handler(KeyPressEvent)
    def handle_key_press(self, event):
        if not self.moveresize:
            raise UnhandledEvent(event)
        keysym = self.keymap.lookup_key(event.detail, event.state)
        if keysym == XK_Escape:
            self.moveresize.rollback(event.time)
            self.moveresize = None
        elif keysym == XK_Return:
            self.moveresize.commit(event.time)
            self.moveresize = None
        elif keysym == XK_space:
            self.moveresize.cycle_gravity(self.query_pointer(), event.time)
