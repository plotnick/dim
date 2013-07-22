# -*- mode: Python; coding: utf-8 -*-

"""Manage multiple heads (physical screens or monitors) on a single X screen."""

import logging

import xcb
from xcb.xproto import *
import xcb.randr
import xcb.xinerama

from event import EventHandler, handler
from geometry import *
from properties import WMState
from xutil import query_extension, query_pointer

class HeadManager(object):
    log = logging.getLogger("multihead")

    def __new__(cls, conn, *args, **kwargs):
        """Auto-probe the supplied connection for RandR or Xinerama support,
        and return an instance of the appropriate subclass."""
        ext = None
        for name, key, kls in [("RANDR", xcb.randr.key, RandRManager),
                               ("XINERAMA", xcb.xinerama.key, XineramaManager)]:
            ext = query_extension(conn, name, key)
            if ext:
                cls = kls
                cls.log.debug("Using %s extension for multi-head support.",
                              name)
                break
        instance = super(HeadManager, cls).__new__(cls)
        instance.ext = ext
        return instance

    def __init__(self, conn, screen, manager):
        self.conn = conn
        self.screen = screen
        self.manager = manager
        self.change_handlers = set()

    def register_change_handler(self, handler):
        self.change_handlers.add(handler)

    def unregister_change_handler(self, handler):
        self.change_handlers.discard(handler)

    def head_geometry_changed(self, old_geometry, new_geometry):
        for handler in self.change_handlers:
            handler(old_geometry, new_geometry)

    def __iter__(self):
        """Return an iterator over the set of current head geometries."""
        return iter([self.manager.screen_geometry])

    def client_head_geometry(self, client):
        """Return the geometry of the head currently containing a client."""
        if not client or client.wm_state != WMState.NormalState:
            return None # not considered to be on any head

        # What counts as `containing a window'? We use a simple heuristic:
        # if there's a head that contains the midpoint of the visible portion
        # of the window, use that; otherwise, look for any non-trivial
        # intersection with the window.
        geometry = client.frame_geometry
        visible = self.manager.screen_geometry & geometry
        if visible:
            point = visible.midpoint()
            for head in self:
                if point in head:
                    return head
        for head in self:
            if geometry & head:
                return head

    @property
    def pointer_head_geometry(self):
        """Return the geometry of the head currently containing the pointer."""
        pointer = query_pointer(self.conn, self.screen)
        for head in self:
            if pointer in head:
                return head
        self.log.warning("Can't find head containing pointer.")
        return self.manager.screen_geometry

    @property
    def focus_head_geometry(self):
        """Return the geometry of the head containing the current focus.
        If there isn't a visible current focus, fall back to the head
        containing the pointer."""
        return (self.client_head_geometry(self.manager.current_focus) or
                self.pointer_head_geometry)

class RandRManager(HeadManager, EventHandler):
    """Support multiple heads and root window geometry changes using the
    X Resize and Rotate extension."""

    log = logging.getLogger("randr")

    def __init__(self, conn, screen, manager):
        super(RandRManager, self).__init__(conn, screen, manager)

        def get_crtc_info(screen):
            """Yield pairs of the form (CRTC, Geometry) for each CRTC
            connected to the given screen."""
            resources = self.ext.GetScreenResources(screen.root).reply()
            timestamp = resources.config_timestamp
            for crtc, cookie in [(crtc, self.ext.GetCrtcInfo(crtc, timestamp))
                                 for crtc in resources.crtcs]:
                info = cookie.reply()
                if info.status or not info.mode:
                    continue
                yield (crtc,
                       Geometry(info.x, info.y, info.width, info.height, 0))
        self.crtcs = dict(get_crtc_info(self.screen))
        self.log.debug("CRTC geometries: {%s}.",
                       ", ".join("0x%x: %s" % (crtc, geometry)
                                 for crtc, geometry in self.crtcs.items()))

        self.manager.register_window_handler(self.screen.root, self)
        self.ext.SelectInput(self.screen.root, xcb.randr.NotifyMask.CrtcChange)

    def __iter__(self):
        return self.crtcs.itervalues()

    @handler(xcb.randr.NotifyEvent)
    def handle_notify(self, event):
        if event.subCode == xcb.randr.Notify.CrtcChange:
            cc = event.u.cc
            if cc.window != self.screen.root:
                return
            if cc.mode:
                new_geometry = Geometry(cc.x, cc.y, cc.width, cc.height, 0)
                self.log.debug("CRTC 0x%x changed: %s.", cc.crtc, new_geometry)
                old_geometry = self.crtcs.get(cc.crtc)
                self.crtcs[cc.crtc] = new_geometry
                self.head_geometry_changed(old_geometry, new_geometry)
            else:
                self.log.debug("CRTC 0x%x disabled.", cc.crtc)
                old_geometry = self.crtcs.pop(cc.crtc, None)
                self.head_geometry_changed(old_geometry, None)

class XineramaManager(HeadManager):
    """Manage multiple heads using the Xinerama extension."""

    log = logging.getLogger("xinerama")

    def __init__(self, conn, screen, manager):
        super(XineramaManager, self).__init__(conn, screen, manager)

        self.heads = [Geometry(info.x_org, info.y_org,
                               info.width, info.height, 0)
                      for info in self.ext.QueryScreens().reply().screen_info]
        self.log.debug("Screen geometries: [%s].",
                       ", ".join(map(str, self.heads)))

    def __iter__(self):
        return iter(self.heads)
