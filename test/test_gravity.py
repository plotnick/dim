# -*- mode: Python; coding: utf-8 -*-

import unittest

from decorator import FrameDecorator
from event import handler
from geometry import *
from manager import ReparentingWindowManager
from properties import WMSizeHints
from wm import BaseWM

from xcb.xproto import *

from test_manager import EventType, TestClient, WMTestCase

class GravityTestClient(TestClient):
    def __init__(self, geometry, screen=None, win_gravity=Gravity.NorthWest):
        super(GravityTestClient, self).__init__(geometry, screen)
        self.frame = None
        self.set_size_hints(WMSizeHints(win_gravity=win_gravity))

    @handler(ReparentNotifyEvent)
    def handle_reparent_notify(self, event):
        assert event.window == self.window
        self.parent = event.parent

class Padding(object):
    def __init__(self, left=0, right=0, top=0, bottom=0):
        self.left = left
        self.right = right
        self.top = top
        self.bottom = bottom

class PaddingDecorator(FrameDecorator):
    """A frame decorator which inserts a bit of padding between its inside
    edge and the client window it's framing."""

    def __init__(self, conn, client, border_width=1,
                 padding=Padding(0, 0, 0, 0), **kwargs):
        super(PaddingDecorator, self).__init__(conn, client, border_width,
                                               **kwargs)
        assert isinstance(padding, Padding)
        self.padding = padding

    def compute_client_offset(self):
        return Geometry(self.padding.left,
                        self.padding.top,
                        self.padding.left + self.padding.right,
                        self.padding.top + self.padding.bottom,
                        None)

class GravityTestWM(ReparentingWindowManager):
    def decorator(self, client):
        return PaddingDecorator(self.conn, client, border_width=5,
                                padding=Padding(top=10, bottom=2,
                                                left=7, right=3))

def reference_point(geometry, gravity):
    """Return the reference point of the given geometry with respect to the
    given gravity. See ICCCM §4.1.2.3."""
    p = geometry.position()
    w, h = geometry.size()
    bw = geometry.border_width

    if gravity == Gravity.Static:
        return p + Position(bw, bw)

    if gravity in (Gravity.North, Gravity.Center, Gravity.South):
        dx = (w + 2 * bw) // 2
    elif gravity in (Gravity.NorthEast, Gravity.East, Gravity.SouthEast):
        dx = w + 2 * bw
    else:
        dx = 0

    if gravity in (Gravity.West, Gravity.Center, Gravity.East):
        dy = (h + 2 * bw) // 2
    elif gravity in (Gravity.SouthWest, Gravity.South, Gravity.SouthEast):
        dy = h + 2 * bw
    else:
        dy = 0

    return p + Position(dx, dy)

class TestInitialMapGeometry(WMTestCase):
    wm_class = GravityTestWM

    def runTest(self):
        geometry = Geometry(10, 10, 100, 100, 1)
        for gravity in (Gravity.NorthWest, Gravity.North, Gravity.NorthEast,
                        Gravity.West, Gravity.Center, Gravity.East,
                        Gravity.SouthWest, Gravity.South, Gravity.SouthEast,
                        Gravity.Static):
            client = self.add_client(GravityTestClient(geometry,
                                                       win_gravity=gravity))
            client.map()
            self.loop(lambda: (client.managed and
                               client.mapped and
                               client.parent and
                               client.parent != self.screen.root))

            reply = self.conn.core.GetGeometry(client.parent).reply()
            frame_geometry = Geometry(reply.x, reply.y,
                                      reply.width, reply.height,
                                      reply.border_width)

            self.assertEqual(reference_point(geometry, gravity),
                             reference_point(frame_geometry, gravity))

            client.unmap()
            self.loop(lambda: client.parent == self.screen.root)

            reply = self.conn.core.GetGeometry(client.window).reply()
            client_geometry = Geometry(reply.x, reply.y,
                                       reply.width, reply.height,
                                       reply.border_width)
            self.assertEqual(client_geometry, geometry)

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING)

    unittest.main()
