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

def identity(x):
    return x

# Thanks to Tim Bray for the binary search implementation:
# <http://www.tbray.org/ongoing/When/200x/2003/03/22/Binary>
def bsearch_floor(sequence, item, key=identity):
    """Return the largest element of sequence ≤ item."""
    high = len(sequence); low = -1
    while high - low > 1:
        probe = (low + high) // 2
        if key(sequence[probe]) > item:
            high = probe
        else:
            low = probe
    return sequence[low] if low != -1 else None

def bsearch_ceil(sequence, item, key=identity):
    """Return the smallest element of sequence ≥ item."""
    high = len(sequence); low = -1
    while high - low > 1:
        probe = (low + high) // 2
        if key(sequence[probe]) < item:
            low = probe
        else:
            high = probe
    return sequence[high] if high != len(sequence) else None

class Resistance(object):
    cardinal_directions = map(gravity_offset,
                              [Gravity.North, Gravity.South,
                               Gravity.East, Gravity.West])
    axial_directions = [map(gravity_offset, [Gravity.East, Gravity.West]),
                        map(gravity_offset, [Gravity.North, Gravity.South])]

    def __init__(self, client, **kwargs):
        self.client = client

    def resist(self, geometry, gravity=Gravity.Center):
        """Given a requested geometry, apply all applicable resistance and
        return the nearest acceptable geometry."""
        for axis in (0, 1):
            for direction in self.axial_directions[axis]:
                geometry = self.maybe_resist(geometry, gravity_offset(gravity),
                                             axis, direction)
        return geometry

    def maybe_resist(self, geometry, gravity, axis, direction):
        """Apply any applicable resistance in the given cardinal direction
        and return the nearest acceptable geometry."""
        return geometry

    @staticmethod
    def apply_resistance(geometry, gravity, axis, direction, resistance):
        assert isinstance(geometry, Geometry)
        assert isinstance(gravity, Position)
        assert 0 <= axis <= 1
        assert isinstance(direction, Position)
        assert isinstance(resistance, int)

        if direction[axis] > 0:
            if gravity[axis] < 0:
                return geometry - Rectangle(*direction) * resistance
            else:
                return geometry - direction * resistance
        elif direction[axis] < 0:
            if gravity[axis] > 0:
                return (geometry +
                        direction * resistance -
                        Rectangle(*direction) * resistance)
            else:
                return geometry + direction * resistance
        else:
            assert False, "invalid direction for resistance application"

class ScreenEdgeResistance(Resistance):
    """Resist moving a client's external edges past the screen edges."""

    def __init__(self, client, screen_edge_resistance=40, **kwargs):
        super(ScreenEdgeResistance, self).__init__(client, **kwargs)

        self.__threshold = screen_edge_resistance
        screen_geometry = client.manager.screen_geometry
        self.screen_edges = {}
        for direction in self.cardinal_directions:
            self.screen_edges[direction] = screen_geometry.edge(direction)

    def maybe_resist(self, geometry, gravity, axis, direction):
        requested_edge = geometry.edge(direction)
        current_edge = self.client.frame_geometry.edge(direction)
        screen_edge = self.screen_edges[direction]
        if ((direction[axis] > 0 and
             current_edge <= screen_edge and
             screen_edge < requested_edge < screen_edge + self.__threshold) or
            (direction[axis] < 0 and
             current_edge >= screen_edge and
             screen_edge - self.__threshold < requested_edge < screen_edge)):
            return self.apply_resistance(geometry, gravity, axis, direction,
                                         requested_edge - screen_edge)
        return super(ScreenEdgeResistance, self).maybe_resist(geometry, gravity,
                                                              axis, direction)

class WindowEdgeResistance(Resistance):
    """Classical edge resistance: windows' opposite external edges resist
    moving past one another."""

    def __init__(self, client, window_edge_resistance=20, **kwargs):
        super(WindowEdgeResistance, self).__init__(client, **kwargs)

        self.__threshold = window_edge_resistance
        clients = [client
                   for client in client.manager.clients.values()
                   if client is not self.client]
        self.client_list = {}
        for direction in self.cardinal_directions:
            def edge(client):
                return client.frame_geometry.edge(direction)
            self.client_list[direction] = sorted(clients, key=edge)

    def maybe_resist(self, geometry, gravity, axis, direction):
        opposite = -direction
        def opposite_edge(client):
            return client.frame_geometry.edge(opposite)
        def adjacent_edges(client):
            return (client.frame_geometry.edge(Position(*reversed(direction))),
                    client.frame_geometry.edge(Position(*reversed(opposite))))
        def adjacent_edges_intersect(client, other):
            a = adjacent_edges(client)
            b = adjacent_edges(other)
            return (min(a) <= min(b) <= max(a) or
                    min(a) <= max(b) <= max(a) or
                    min(b) <= min(a) <= max(b) or
                    min(b) <= max(a) <= max(b))
        requested_edge = geometry.edge(direction)
        current_edge = self.client.frame_geometry.edge(direction)
        threshold = self.__threshold
        while True: # for lack of goto
            if direction[axis] > 0:
                other = bsearch_floor(self.client_list[opposite],
                                      requested_edge,
                                      key=opposite_edge)
                if not other:
                    break
                other_edge = opposite_edge(other)
                if (current_edge <= other_edge and
                    other_edge < requested_edge < other_edge + threshold and
                    adjacent_edges_intersect(self.client, other)):
                    return self.apply_resistance(geometry, gravity,
                                                 axis, direction,
                                                 requested_edge - other_edge)
            elif direction[axis] < 0:
                other = bsearch_ceil(self.client_list[opposite],
                                     requested_edge,
                                     key=opposite_edge)
                if not other:
                    break
                other_edge = opposite_edge(other)
                if (current_edge >= other_edge and
                    other_edge - threshold < requested_edge < other_edge and
                    adjacent_edges_intersect(self.client, other)):
                    return self.apply_resistance(geometry, gravity,
                                                 axis, direction,
                                                 requested_edge - other_edge)
            break
        return super(WindowEdgeResistance, self).maybe_resist(geometry, gravity,
                                                              axis, direction)

class EdgeResistance(WindowEdgeResistance, ScreenEdgeResistance):
    pass

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
        delta = self.delta(pointer)
        self.display_geometry(self.client.move(self.position + delta))

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
                                  gravity=offset_gravity(-self.gravity)).size()
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
                      gravities=sorted(offset_gravity(None),
                                       key=lambda x: x.phase())):
        i = gravities.index(self.gravity)
        self.gravity = gravities[(i + 1) % len(gravities)]
        self.change_cursor(self.cursors[self.gravity], time)
        self.geometry = self.client.absolute_geometry
        self.frame_geometry = self.client.frame_geometry
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
        self.client_update = None
        
        kwargs.update(grab_buttons=grab_buttons.merge({
            (move_button, move_resize_mods): self.__grab_event_mask,
            (resize_button, move_resize_mods): self.__grab_event_mask
        }))
        super(MoveResize, self).__init__(display, screen, **kwargs)

    def constrain_position(self, client, position):
        position = super(MoveResize, self).constrain_position(client, position)
        if self.client_update:
            geometry = client.frame_geometry.move(position)
            position = self.client_update.resistance.resist(geometry).position()
        return position

    def constrain_size(self, client, geometry, size=None, border_width=None,
                       gravity=None):
        requested = super(MoveResize, self).constrain_size(client, geometry,
                                                           size, border_width,
                                                           gravity)
        if self.client_update:
            frame = client.absolute_to_frame_geometry(requested)
            frame = self.client_update.resistance.resist(frame, gravity)
            resisted = client.frame_to_absolute_geometry(frame)
            if requested != resisted:
                # Re-constrain the resisted size to ensure compliance with
                # size hints.
                return super(MoveResize, self).constrain_size(client,
                                                              resisted,
                                                              gravity=gravity)
        return requested

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
        client = self.get_client(window)
        self.client_update = action(client,
                                    Position(event.root_x, event.root_y),
                                    ungrab, change_cursor)
        self.client_update.resistance = EdgeResistance(client)

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        if not self.client_update:
            raise UnhandledEvent(event)
        self.client_update.commit(event.time)
        self.client_update = None

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if not self.client_update:
            raise UnhandledEvent(event)
        self.client_update.update(self.query_pointer()
                                  if event.detail == Motion.Hint
                                  else Position(event.root_x, event.root_y))

    @handler(KeyPressEvent)
    def handle_key_press(self, event):
        if not self.client_update:
            raise UnhandledEvent(event)
        keysym = self.keymap.lookup_key(event.detail, event.state)
        if keysym == XK_Escape:
            self.client_update.rollback(event.time)
            self.client_update = None
        elif keysym == XK_Return:
            self.client_update.commit(event.time)
            self.client_update = None
        elif keysym == XK_space:
            self.client_update.cycle_gravity(self.query_pointer(), event.time)
