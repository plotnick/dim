# -*- mode: Python; coding: utf-8 -*-

import logging

from xcb.xproto import *

from bindings import event_mask
from cursor import *
from event import handler
from geometry import *
from keysym import *
from manager import WindowManager, compress
from properties import WMSizeHints, WMState
from xutil import *

__all__ = ["MoveResize"]

log = logging.getLogger("moveresize")

def identity(x):
    return x

def bsearch_floor(item, sequence, key=identity):
    """Return a set containing the largest elements of sequence ≤ item."""
    high = len(sequence); low = -1
    while high - low > 1:
        probe = (low + high) // 2
        if key(sequence[probe]) > item:
            high = probe
        else:
            low = probe
    matches = set()
    if low >= 0:
        floor = key(sequence[low])
        matches.add(sequence[low])
        low -= 1
        while low >= 0 and key(sequence[low]) == floor:
            matches.add(sequence[low])
            low -= 1
    return matches

def bsearch_ceil(item, sequence, key=identity):
    """Return a set containing the smallest elements of sequence ≥ item."""
    n = len(sequence)
    high = n; low = -1
    while high - low > 1:
        probe = (low + high) // 2
        if key(sequence[probe]) < item:
            low = probe
        else:
            high = probe
    matches = set()
    if high < n:
        ceil = key(sequence[high])
        matches.add(sequence[high])
        high += 1
        while high < n and key(sequence[high]) == ceil:
            matches.add(sequence[high])
            high += 1
    return matches

# Many resistance calculations are made in terms of the four cardinal
# directions, which we represent as unit vectors with a single non-zero
# component. The following routines are specialized to such directions,
# and are not intended for general use.

cardinal_directions = map(gravity_offset,
                          [Gravity.North,
                           Gravity.South,
                           Gravity.East,
                           Gravity.West])

def is_positive_direction(direction):
    return any(x > 0 for x in direction)

def is_negative_direction(direction):
    return any(x < 0 for x in direction)

def cardinal_axis(direction):
    for i, x in enumerate(direction):
        if x:
            return i

class Resistance(object):
    def __init__(self, client, **kwargs):
        self.client = client

    def resist(self, geometry, gravity=Gravity.Center):
        """Given a requested geometry, apply all applicable resistance and
        return the nearest acceptable geometry."""
        def apply_resistance(geometry, gravity, direction, resistance):
            if is_positive_direction(direction):
                if gravity[cardinal_axis(direction)] < 0:
                    return geometry - Rectangle(*direction) * resistance
                else:
                    return geometry - direction * resistance
            else:
                if gravity[cardinal_axis(direction)] > 0:
                    return (geometry +
                            direction * resistance -
                            Rectangle(*direction) * resistance)
                else:
                    return geometry + direction * resistance

        gravity = gravity_offset(gravity)
        for direction in cardinal_directions:
            geometry = apply_resistance(geometry, gravity, direction,
                                        self.compute_resistance(geometry,
                                                                gravity,
                                                                direction))
        return geometry

    def compute_resistance(self, geometry, gravity, direction):
        """Compute and return any applicable resistance in the given cardinal
        direction."""
        return 0

    def cleanup(self, time):
        pass

class ScreenEdgeResistance(Resistance):
    """Resist moving a client's external edges past the screen edges."""

    def __init__(self, client, screen_edge_resistance=40, **kwargs):
        super(ScreenEdgeResistance, self).__init__(client, **kwargs)

        self.screen_edge_resistance = screen_edge_resistance
        screen_geometry = client.manager.screen_geometry
        self.screen_edges = dict((direction, screen_geometry.edge(direction))
                                 for direction in cardinal_directions)

    def edge_resistance(self, edge, geometry, gravity, direction):
        requested_edge = geometry.edge(direction)
        current_edge = self.client.frame_geometry.edge(direction)
        threshold = self.screen_edge_resistance
        if ((is_positive_direction(direction) and
             current_edge <= edge and
             edge < requested_edge < edge + threshold) or
            (is_negative_direction(direction) and
             current_edge >= edge and
             edge - threshold < requested_edge < edge)):
            return requested_edge - edge

    def compute_resistance(self, geometry, gravity, direction):
        resistance = self.edge_resistance(self.screen_edges[direction],
                                          geometry, gravity, direction)
        if resistance:
            return resistance
        return super(ScreenEdgeResistance, self).compute_resistance(geometry,
                                                                    gravity,
                                                                    direction)

class CRTCEdgeResistance(ScreenEdgeResistance):
    """Treat CRTC edges like screen edges."""

    def __init__(self, client, **kwargs):
        super(CRTCEdgeResistance, self).__init__(client, **kwargs)

        self.crtc_edges = [dict((direction, geometry.edge(direction))
                                for direction in cardinal_directions)
                           for geometry in client.manager.crtcs.values()]

    def compute_resistance(self, geometry, gravity, direction):
        for crtc_edges in self.crtc_edges:
            resistance = self.edge_resistance(crtc_edges[direction],
                                              geometry, gravity, direction)
            if resistance:
                return resistance
        return super(CRTCEdgeResistance, self).compute_resistance(geometry,
                                                                  gravity,
                                                                  direction)

class WindowEdgeResistance(Resistance):
    """Classical edge resistance: visible windows' opposite external edges
    resist moving past one another."""

    def __init__(self, client, window_edge_resistance=20, **kwargs):
        super(WindowEdgeResistance, self).__init__(client, **kwargs)

        self.window_edge_resistance = window_edge_resistance
        clients = [client
                   for client in client.manager.clients.values()
                   if (client is not self.client and
                       client.properties.wm_state == WMState.NormalState and
                       client.visibility != Visibility.FullyObscured)]
        self.client_list = {}
        for direction in cardinal_directions:
            def edge(client):
                return client.frame_geometry.edge(direction)
            self.client_list[direction] = sorted(clients, key=edge)

    def compute_resistance(self, geometry, gravity, direction):
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
        threshold = self.window_edge_resistance
        if is_positive_direction(direction):
            for other in bsearch_floor(requested_edge,
                                       self.client_list[opposite],
                                       key=opposite_edge):
                other_edge = opposite_edge(other)
                if (current_edge <= other_edge and
                    other_edge < requested_edge < other_edge + threshold and
                    adjacent_edges_intersect(self.client, other)):
                    return requested_edge - other_edge
        else:
            for other in bsearch_ceil(requested_edge,
                                      self.client_list[opposite],
                                      key=opposite_edge):
                other_edge = opposite_edge(other)
                if (current_edge >= other_edge and
                    other_edge - threshold < requested_edge < other_edge and
                    adjacent_edges_intersect(self.client, other)):
                    return requested_edge - other_edge
        return super(WindowEdgeResistance, self).compute_resistance(geometry,
                                                                    gravity,
                                                                    direction)

class AlignWindowEdges(WindowEdgeResistance):
    def __init__(self, *args, **kwargs):
        super(AlignWindowEdges, self).__init__(*args, **kwargs)
        self.guides = [None, None]

    def resist(self, *args):
        self.draw_guide(None, None)
        return super(AlignWindowEdges, self).resist(*args)

    def compute_resistance(self, geometry, gravity, direction):
        def edge(client):
            return client.frame_geometry.edge(direction)
        requested_edge = geometry.edge(direction)
        current_edge = edge(self.client)
        threshold = self.window_edge_resistance
        if is_positive_direction(direction):
            for other in bsearch_floor(requested_edge,
                                       self.client_list[direction],
                                       key=edge):
                other_edge = edge(other)
                if (current_edge <= other_edge and
                    other_edge < requested_edge < other_edge + threshold):
                    self.draw_guide(cardinal_axis(direction), other_edge)
                    return requested_edge - other_edge
        else:
            for other in bsearch_ceil(requested_edge,
                                      self.client_list[direction],
                                      key=edge):
                other_edge = edge(other)
                if (current_edge >= other_edge and
                    other_edge - threshold < requested_edge < other_edge):
                    self.draw_guide(cardinal_axis(direction), other_edge - 1)
                    return requested_edge - other_edge
        return super(AlignWindowEdges, self).compute_resistance(geometry,
                                                                gravity,
                                                                direction)

    def draw_guide(self, axis, coord):
        def draw(axis, coord):
            if coord is not None:
                w, h = self.client.manager.screen_geometry.size()
                line = [[coord, 0, coord, h], [0, coord, w, coord]][axis]
                self.client.conn.core.PolyLine(CoordMode.Origin,
                                               self.client.screen.root,
                                               self.client.manager.xor_gc,
                                               1, line)
        if axis is None and coord is None:
            for axis in (0, 1):
                draw(axis, self.guides[axis])
                self.guides[axis] = None
        elif self.guides[axis] != coord:
            draw(axis, self.guides[axis])
            draw(axis, coord)
            self.guides[axis] = coord

    def cleanup(self, time):
        self.draw_guide(None, None)

class EdgeResistance(AlignWindowEdges, CRTCEdgeResistance):
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
        self.client.conn.flush()

    def rollback(self, time):
        self.cleanup(time)
        self.client.decorator.message(None)

    def display_geometry(self, geometry):
        self.client.decorator.message(unicode(geometry))

    def cycle_gravity(self, pointer, time):
        pass

    def move(self, position):
        client = self.client
        return client.move(client.manager.constrain_position(client, position))

    def resize(self, size, gravity):
        client = self.client
        return client.configure(client.manager.constrain_size(client,
                                                              self.geometry,
                                                              size,
                                                              gravity=gravity))

class ClientMove(ClientUpdate):
    cursor = XC_fleur

    def __init__(self, *args):
        super(ClientMove, self).__init__(*args)
        self.position = self.frame_geometry.position()
        self.change_cursor(self.cursor)
        self.display_geometry(self.position)

    def update(self, pointer):
        delta = self.delta(pointer)
        self.display_geometry(self.move(self.position + delta))

    def rollback(self, time=Time.CurrentTime):
        self.move(self.position)
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
        self.size_hints = self.client.properties.wm_normal_hints

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
        self.update(self.pointer)

    def update(self, pointer):
        delta = self.delta(pointer)

        # Treat center gravity as just a move.
        if self.gravity == (0, 0):
            position = self.frame_geometry.position() + delta
            self.display_geometry(self.move(position))
            return

        ds = Rectangle(delta.x * self.gravity.x, delta.y * self.gravity.y)
        size = self.resize(self.geometry.size() + ds,
                           offset_gravity(-self.gravity)).size()
        if self.size_hints.flags & WMSizeHints.PResizeInc:
            size = self.size_hints.size_increments(size)
        self.display_geometry(size)

    def rollback(self, time=Time.CurrentTime):
        self.client.configure(self.initial_geometry)
        super(ClientResize, self).rollback(time)

    def cycle_gravity(self, pointer, time,
                      gravities=sorted(offset_gravity(None),
                                       key=lambda x: x.phase())):
        i = gravities.index(self.gravity)
        self.gravity = gravities[(i + 1) % len(gravities)]
        self.change_cursor(self.cursors[self.gravity], time)
        self.geometry = self.client.absolute_geometry
        self.frame_geometry = self.client.frame_geometry
        self.pointer = pointer
        self.update(pointer)

class MoveResize(WindowManager):
    __grab_event_mask = (EventMask.ButtonPress |
                         EventMask.ButtonRelease |
                         EventMask.ButtonMotion |
                         EventMask.PointerMotionHint)

    def __init__(self, display=None, screen=None, **kwargs):
        super(MoveResize, self).__init__(display, screen, **kwargs)
        self.client_update = None

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

    def cleanup_client_update(self, time=Time.CurrentTime):
        self.client_update.resistance.cleanup(time)
        self.conn.core.UngrabPointer(time)
        self.conn.core.UngrabKeyboard(time)

    def change_client_update_cursor(self, cursor, time=Time.CurrentTime):
        self.conn.core.ChangeActivePointerGrab(self.cursors[cursor], time,
                                               self.__grab_event_mask)

    @event_mask(__grab_event_mask)
    def move_window(self, event):
        self.move_resize_window(event, ClientMove)

    @event_mask(__grab_event_mask)
    def resize_window(self, event):
        self.move_resize_window(event, ClientResize)

    def move_resize_window(self, event, update):
        assert isinstance(event, ButtonPressEvent)
        client = self.get_client(event.child)
        if not client or self.client_update:
            return
        self.client_update = update(client,
                                    Position(event.root_x, event.root_y),
                                    self.cleanup_client_update,
                                    self.change_client_update_cursor)
        self.client_update.resistance = EdgeResistance(client)
        self.client_update.button = event.detail
        self.conn.core.GrabKeyboard(False, self.screen.root, event.time,
                                    GrabMode.Async, GrabMode.Async)

    @handler(ButtonReleaseEvent)
    def handle_button_release(self, event):
        if not self.client_update or event.detail != self.client_update.button:
            return
        self.client_update.commit(event.time)
        self.client_update = None

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if not self.client_update:
            return
        self.client_update.update(query_pointer(self.conn, self.screen)
                                  if event.detail == Motion.Hint
                                  else Position(event.root_x, event.root_y))

    @handler(KeyPressEvent)
    def handle_key_press(self, event):
        if not self.client_update:
            return
        keysym = self.keymap.lookup_key(event.detail, event.state)
        if keysym == XK_Escape:
            self.client_update.rollback(event.time)
            self.client_update = None
        elif keysym == XK_Return:
            self.client_update.commit(event.time)
            self.client_update = None
        elif keysym == XK_space:
            self.client_update.cycle_gravity(query_pointer(self.conn,
                                                           self.screen),
                                             event.time)
