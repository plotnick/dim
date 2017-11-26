# -*- mode: Python; coding: utf-8 -*-

import logging
from threading import Thread, Event as ThreadEvent

from xcb.xproto import *

from bindings import *
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
    def __init__(self, *args, **kwargs):
        self.shared_init(*args, **kwargs)

    def reinitialize(self, *args, **kwargs):
        self.shared_init(*args, **kwargs)

    def shared_init(self, client, **kwargs):
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
        """Compute applicable resistance in the given cardinal direction."""
        return 0

    def cleanup(self):
        pass

class ScreenEdgeResistance(Resistance):
    """Resist moving a client's external edges past the screen edges."""

    def shared_init(self, client, screen_edge_resistance=80, **kwargs):
        super(ScreenEdgeResistance, self).shared_init(client, **kwargs)

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

class HeadEdgeResistance(ScreenEdgeResistance):
    """Treat head (monitor) edges like screen edges."""

    def shared_init(self, client, **kwargs):
        super(HeadEdgeResistance, self).shared_init(client, **kwargs)

        self.head_edges = [dict((direction, head.edge(direction))
                                for direction in cardinal_directions)
                           for head in client.manager.heads]

    def compute_resistance(self, geometry, gravity, direction):
        for edges in self.head_edges:
            resistance = self.edge_resistance(edges[direction],
                                              geometry, gravity, direction)
            if resistance:
                return resistance
        return super(HeadEdgeResistance, self).compute_resistance(geometry,
                                                                  gravity,
                                                                  direction)

class WindowEdgeResistance(Resistance):
    """Classical edge resistance: visible windows' opposite external edges
    resist moving past one another."""

    def shared_init(self, client, window_edge_resistance=40, **kwargs):
        super(WindowEdgeResistance, self).shared_init(client, **kwargs)

        self.window_edge_resistance = window_edge_resistance
        clients = [client
                   for client in client.manager.clients.values()
                   if (client is not self.client and
                       client.wm_state == WMState.NormalState and
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
    """Resist moving past aligned edges of other clients."""

    def __init__(self, *args, **kwargs):
        super(AlignWindowEdges, self).__init__(*args, **kwargs)
        self.guides = dict((direction, None)
                           for direction in cardinal_directions)

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
                    self.draw_guide(direction, other_edge)
                    return requested_edge - other_edge
        else:
            for other in bsearch_ceil(requested_edge,
                                      self.client_list[direction],
                                      key=edge):
                other_edge = edge(other)
                if (other_edge > 0 and
                    current_edge >= other_edge and
                    other_edge - threshold < requested_edge < other_edge):
                    self.draw_guide(direction, other_edge - 1)
                    return requested_edge - other_edge
        self.cleanup(direction)
        return super(AlignWindowEdges, self).compute_resistance(geometry,
                                                                gravity,
                                                                direction)

    def draw_guide(self, direction, coord):
        assert direction in cardinal_directions and coord >= 0
        if self.guides[direction]:
            if self.guides[direction].coord == coord:
                return
            self.cleanup(direction)
        self.guides[direction] = MarchingAnts(self.client, direction, coord)
        self.guides[direction].start()

    def cleanup(self, direction=None):
        assert direction is None or direction in cardinal_directions
        for direction in ([direction] if direction else cardinal_directions):
            if self.guides[direction]:
                self.guides[direction].stop()
                self.guides[direction] = None

class MarchingAnts(Thread):
    """Display a moving dashed line indicating window edge alignment."""

    def __init__(self, client, direction, coord, timeout=0.05, offset=0, dash=8):
        super(MarchingAnts, self).__init__()
        self.client = client
        self.direction = direction
        self.coord = coord
        self.timeout = timeout
        self.offset = offset
        self.dash = dash
        self.daemon = True
        self.timer = ThreadEvent()
        self.gc = self.client.conn.generate_id()
        self.client.conn.core.CreateGC(self.gc, self.client.screen.root,
                                       (GC.Function |
                                        GC.Foreground |
                                        GC.LineStyle |
                                        GC.DashOffset |
                                        GC.DashList),
                                       [GX.xor,
                                        self.client.colors["#808080"],
                                        LineStyle.OnOffDash,
                                        self.offset,
                                        self.dash])
        c = self.coord
        w, h = self.client.manager.screen_geometry.size()
        self.line = ([c, 0, c, h] if self.direction[0] else
                     [0, c, w, c])

    def draw(self):
        self.client.conn.core.PolyLine(CoordMode.Origin,
                                       self.client.screen.root,
                                       self.gc, 1, self.line)
        self.client.conn.flush()

    def run(self):
        while True:
            self.draw()
            self.timer.wait(self.timeout)
            self.draw() # erase
            if self.timer.is_set():
                self.client.conn.core.FreeGC(self.gc)
                return
            self.offset += 1
            self.offset %= self.dash * 2
            self.client.conn.core.ChangeGC(self.gc,
                                           GC.DashOffset,
                                           [self.offset])

    def stop(self):
        self.timer.set()

class EdgeResistance(AlignWindowEdges, HeadEdgeResistance):
    pass

class ClientUpdate(object):
    """A transactional client configuration change."""

    buttons = {}
    keys = {
        XK_space: lambda self, event: self.cycle_gravity(event.time),
        XK_Escape: lambda self, event: self.rollback(event.time),
        None: lambda self, event: self.commit(event.time)
    }

    def __init__(self,
                 event, client, pointer, resistance, cleanup, change_cursor,
                 move_delta=0):
        self.client = client
        self.button = event.detail if isinstance(event, ButtonPressEvent) else 0
        self.pointer = pointer
        self.resistance = resistance
        self.cleanup = cleanup
        self.change_cursor = change_cursor
        self.move_delta = move_delta
        self.geometry = client.absolute_geometry
        self.frame_geometry = client.frame_geometry
        try:
            modifiers = next(client.manager.key_bindings.modsets(event.state))
        except AttributeError:
            modifiers = frozenset()
        self.buttons = ModalButtonBindingMap(modifiers,
                                             {-self.button: self.keys[None]}
                                             if self.button < 3
                                             else self.buttons)
        self.button_bindings = ButtonBindings(self.buttons,
                                              self.client.manager.keymap,
                                              self.client.manager.modmap)
        self.keys = ModalKeyBindingMap(modifiers, self.keys)
        self.key_bindings = KeyBindings(self.keys,
                                        self.client.manager.keymap,
                                        self.client.manager.modmap)

    def delta(self, pointer):
        dp = pointer - self.pointer
        if self.move_delta:
            if abs(dp) < self.move_delta:
                return origin
            else:
                self.move_delta = 0
        return dp

    def update(self, pointer):
        pass
            
    def commit(self, time=Time.CurrentTime):
        self.cleanup(time)
        self.client.decorator.message(None)
        self.client.conn.flush()

    def rollback(self, time=Time.CurrentTime):
        self.cleanup(time)
        self.client.decorator.message(None)
        self.client.conn.flush()

    def display_geometry(self, geometry):
        self.client.decorator.message(unicode(geometry))

    def cycle_gravity(self, time):
        pass

    def move(self, position):
        client = self.client
        position = client.manager.constrain_position(client, position)
        client.configure_request(x=position.x, y=position.y)
        return client.position()

    def resize(self, size, gravity):
        client = self.client
        return client.configure(client.manager.constrain_size(client,
                                                              self.geometry,
                                                              size,
                                                              gravity=gravity))

class ClientMove(ClientUpdate):
    cursor = XC_fleur

    def __init__(self, *args, **kwargs):
        super(ClientMove, self).__init__(*args, **kwargs)
        self.position = self.frame_geometry.position()
        self.change_cursor(self.cursor)
        if not self.move_delta:
            self.display_geometry(self.position)

    def update(self, pointer):
        self.display_geometry(self.move(self.position + self.delta(pointer)))

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

    def __init__(self, *args, **kwargs):
        super(ClientResize, self).__init__(*args, **kwargs)
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

    def cycle_gravity(self, time,
                      gravities=sorted(offset_gravity(None),
                                       key=lambda x: x.phase())):
        i = gravities.index(self.gravity)
        self.gravity = gravities[(i + 1) % len(gravities)]
        self.change_cursor(self.cursors[self.gravity], time)
        self.geometry = self.client.absolute_geometry
        self.frame_geometry = self.client.frame_geometry
        self.pointer = query_pointer(self.client.conn, self.client.screen)
        self.update(self.pointer)

class ClientRoll(ClientResize):
    xincr = Position(20, 0)
    yincr = Position(0, 20)
    buttons = {
        4: lambda self, event: self.roll(+0, -1),
        5: lambda self, event: self.roll(+0, +1),
        6: lambda self, event: self.roll(-1, +0),
        7: lambda self, event: self.roll(+1, +0),
    }

    def __init__(self, *args, **kwargs):
        super(ClientRoll, self).__init__(*args, **kwargs)
        self.xticks = 0
        self.yticks = 0

    def roll(self, x, y):
        self.xticks += x
        self.yticks += y
        self.update(self.pointer +
                    self.xticks * self.xincr +
                    self.yticks * self.yincr)

class MoveResize(WindowManager):
    __grab_event_mask = (EventMask.ButtonPress |
                         EventMask.ButtonRelease |
                         EventMask.ButtonMotion |
                         EventMask.PointerMotionHint)

    def __init__(self, **kwargs):
        super(MoveResize, self).__init__(**kwargs)

        self.heads.register_change_handler(lambda *args: self.update_resistance)

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

    def end_client_update(self, time):
        self.client_update.resistance.cleanup()
        self.conn.core.UngrabPointer(time)
        self.conn.core.UngrabKeyboard(time)
        self.client_update = None

    def update_resistance(self):
        if not self.client_update:
            return
        self.client_update.resistance.reinitialize(self.client_update.client)

    def change_client_update_cursor(self, cursor, time=Time.CurrentTime):
        self.conn.core.ChangeActivePointerGrab(self.cursors[cursor], time,
                                               self.__grab_event_mask)

    def move_resize_window(self, event, update, **kwargs):
        assert isinstance(event, ButtonPressEvent)
        client = self.get_client(event.event)
        if not client or self.client_update:
            return
        self.conn.core.GrabKeyboard(False,
                                    self.screen.root,
                                    event.time,
                                    GrabMode.Async,
                                    GrabMode.Async)
        self.client_update = update(event,
                                    client,
                                    Position(event.root_x, event.root_y),
                                    EdgeResistance(client),
                                    self.end_client_update,
                                    self.change_client_update_cursor,
                                    **kwargs)

    @event_mask(__grab_event_mask)
    def move_window(self, event, **kwargs):
        self.move_resize_window(event, ClientMove, **kwargs)

    @event_mask(__grab_event_mask)
    def resize_window(self, event, **kwargs):
        self.move_resize_window(event, ClientResize, **kwargs)

    @event_mask(__grab_event_mask)
    def roll_window(self, event, **kwargs):
        self.move_resize_window(event, ClientRoll, **kwargs)

    @handler(MotionNotifyEvent)
    @compress
    def handle_motion_notify(self, event):
        if not self.client_update:
            return
        self.client_update.update(query_pointer(self.conn, self.screen)
                                  if event.detail == Motion.Hint
                                  else Position(event.root_x, event.root_y))

    @handler((KeyPressEvent, KeyReleaseEvent,
              ButtonPressEvent, ButtonReleaseEvent))
    def handle_press_release(self, event):
        if not self.client_update:
            return
        bindings = (self.client_update.key_bindings
                    if isinstance(event, (KeyPressEvent, KeyReleaseEvent))
                    else self.client_update.button_bindings)
        try:
            action = bindings[event]
        except KeyError:
            return
        action(self.client_update, event)

    @handler(VisibilityNotifyEvent)
    def handle_visibility_notify(self, event):
        self.update_resistance()
