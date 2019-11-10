# -*- mode: Python; coding: utf-8 -*-

"""Manage multiple heads (physical screens or monitors) on a single X screen."""

from __future__ import division

import logging
from struct import pack, unpack_from

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

    def move_client(self, client=None, incr=1):
        """Move a client window to another head.
        Attempts to maintain the client's head-relative geometry,
        skipping heads for which that geometry would be invisible."""
        client = client or self.manager.current_focus
        if not client:
            return
        cur_head = self.client_head_geometry(client)
        if not cur_head:
            return
        heads = tuple(self)
        n = len(heads)
        if n < 2:
            return # no other head to switch to
        assert (0 < abs(incr) < n), "Bad increment %r" % incr
        while True:
            new_head = heads[(heads.index(cur_head) + incr) % n]
            if new_head == cur_head:
                return
            new_position = (client.position() -
                            cur_head.position() +
                            new_head.position()) & new_head
            if new_position or new_position == origin:
                break
            incr += 1 if incr > 0 else -1
        position = client.manager.constrain_position(client, new_position)
        client.configure_request(x=position.x, y=position.y)

class RandRManager(HeadManager, EventHandler):
    """Support multiple heads and root window geometry changes using the
    X Resize and Rotate extension."""

    log = logging.getLogger("randr")

    def __init__(self, conn, screen, manager):
        super(RandRManager, self).__init__(conn, screen, manager)

        primary_cookie = self.ext.GetOutputPrimary(screen.root)
        resources = self.ext.GetScreenResourcesCurrent(screen.root).reply()
        timestamp = resources.config_timestamp
        def crtcs():
            for crtc, cookie in [(crtc,
                                  self.ext.GetCrtcInfo(crtc, timestamp))
                                 for crtc in resources.crtcs]:
                info = cookie.reply()
                yield (crtc,
                       Geometry(info.x, info.y, info.width, info.height, 0))
        def outputs():
            for output, cookie in [(output,
                                    self.ext.GetOutputInfo(output, timestamp))
                                   for output in resources.outputs]:
                info = cookie.reply()
                yield (output, {"name": unicode(info.name.buf(), "UTF-8"),
                                "crtcs": list(info.crtcs)})

        self.atoms = manager.atoms
        self.crtcs = dict(crtcs())
        self.outputs = dict(outputs())
        self.primary_output = primary_cookie.reply().output

        def join(strings): ",\n ".join(strings)
        if self.crtcs:
            self.log.debug("CRTCs: {\n %s\n}.",
                           join("%d: %s" % (crtc, geometry)
                                for crtc, geometry in self.crtcs.items()))
        if self.outputs:
            self.log.debug("Outputs: {\n %s\n}.",
                           join("%s%d: %s" % \
                                ("\b*" if output == self.primary_output else "",
                                 output,
                                 info)
                                for output, info in self.outputs.items()))
        if self.primary_output:
            self.log.debug("Backlight level on output %d: %s",
                           self.primary_output,
                           self.get_backlight(self.primary_output))

        self.manager.register_window_handler(self.screen.root, self)
        self.ext.SelectInput(self.screen.root, xcb.randr.NotifyMask.CrtcChange)

    def __iter__(self):
        return (self.crtcs.itervalues()
                if self.crtcs
                else super(RandRManager, self).__iter__())

    def query_backlight_range(self, output):
        reply = self.ext.QueryOutputProperty(output,
                                             self.atoms["Backlight"]).reply()
        return reply.validValues if reply.range else (0, 0)

    def get_backlight(self, output):
        reply = self.ext.GetOutputProperty(output,
                                           self.atoms["Backlight"],
                                           self.atoms["INTEGER"],
                                           0, 4, False, False).reply()
        return (unpack_from("=i", reply.data.buf())[0]
                if (reply.type == self.atoms["INTEGER"] and
                    reply.num_items == 1 and
                    reply.format == 32)
                else 0)

    def set_backlight(self, output, value):
        self.log.info("Setting backlight on output %d to %d.", output, value)
        self.ext.ChangeOutputProperty(output,
                                      self.atoms["Backlight"],
                                      self.atoms["INTEGER"],
                                      32, PropMode.Replace, 1,
                                      pack("=i", value))

    def adjust_backlight(self, output, percent, op):
        if not output:
            return

        # adapted from Keith Packard's xbacklight(1)
        cur = self.get_backlight(output)
        min, max = self.query_backlight_range(output)
        try:
            new = {"set": lambda x: min + x,
                   "inc": lambda x: cur + x,
                   "dec": lambda x: cur - x}[op](percent * (max - min) / 100)
        except KeyError:
            self.log.error("Bad backlight operation %s.", op)
            return
        if new > max: new = max
        if new < min: new = min
        self.set_backlight(output, new)

    @handler(xcb.randr.NotifyEvent)
    def handle_notify(self, event):
        if event.subCode == xcb.randr.Notify.CrtcChange:
            cc = event.u.cc
            if cc.window != self.screen.root:
                return
            if cc.mode:
                new_geometry = Geometry(cc.x, cc.y, cc.width, cc.height, 0)
                self.log.debug("CRTC %d changed: %s.", cc.crtc, new_geometry)
                old_geometry = self.crtcs.get(cc.crtc)
                self.crtcs[cc.crtc] = new_geometry
                self.head_geometry_changed(old_geometry, new_geometry)
            else:
                self.log.debug("CRTC %d disabled.", cc.crtc)
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
