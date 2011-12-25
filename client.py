# -*- mode: Python; coding: utf-8 -*-

"""The clients of a window manager are top-level windows. This module provides
classes and routines for dealing with those as such."""

import logging

from xcb.xproto import *

from event import *
from geometry import *
from properties import *
from xutil import *

__all__ = ["Client"]

@client_message("WM_CHANGE_STATE")
class WMChangeState(ClientMessage):
    """Sent by a client that would like its state changed (ICCCM §4.1.4)."""
    pass

class ClientProperties(PropertyManager):
    # ICCCM properties
    wm_name = PropertyDescriptor("WM_NAME", String, "")
    wm_icon_name = PropertyDescriptor("WM_ICON_NAME", String, "")
    wm_normal_hints = PropertyDescriptor("WM_NORMAL_HINTS",
                                         WMSizeHints,
                                         WMSizeHints())
    wm_hints = PropertyDescriptor("WM_HINTS", WMHints, WMHints())
    wm_class = PropertyDescriptor("WM_CLASS", WMClass, (None, None))
    wm_transient_for = PropertyDescriptor("WM_TRANSIENT_FOR", WMTransientFor)
    wm_protocols = PropertyDescriptor("WM_PROTOCOLS", WMProtocols, [])
    wm_state = PropertyDescriptor("WM_STATE", WMState, WMState())

    # EWMH properties
    net_wm_name = PropertyDescriptor("_NET_WM_NAME", UTF8String, "")
    net_wm_icon_name = PropertyDescriptor("_NET_WM_ICON_NAME", UTF8String, "")

    # Dim-specific properties
    dim_tags = PropertyDescriptor("_DIM_TAGS", AtomList, [])

class Client(EventHandler):
    """Represents a managed, top-level client window."""

    client_event_mask = (EventMask.EnterWindow |
                         EventMask.FocusChange |
                         EventMask.PropertyChange)

    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.VisibilityChange)

    def __init__(self, conn, window, manager):
        self.conn = conn
        self.window = window
        self.manager = manager
        self.screen = manager.screen
        self.atoms = manager.atoms
        self.colors = manager.colors
        self.cursors = manager.cursors
        self.fonts = manager.fonts
        self.keymap = manager.keymap
        self.properties = ClientProperties(self.conn, self.window, self.atoms)
        self.decorator = manager.decorator(self)
        self.decorated = False
        self.focus_time = None
        self.focus_override = None
        self.visibility = None
        self.log = logging.getLogger("client.0x%x" % self.window)

        with GrabServer(self.conn):
            geometry = get_window_geometry(self.conn, self.window)
            if not geometry:
                return

            # Set the client's border width to 0, but save the current value
            # so that we can restore it if and when we reparent the client
            # back to the root.
            self.original_border_width = geometry.border_width
            self.conn.core.ConfigureWindow(self.window,
                                           ConfigWindow.BorderWidth,
                                           [0])

            # Compute the frame geometry based on the current geometry
            # and the requirements of our decorator.
            offset = self.decorator.compute_client_offset()
            gravity = self.properties.wm_normal_hints.win_gravity
            frame_geometry = geometry.resize(geometry.size() + offset.size(),
                                             self.decorator.border_width,
                                             gravity)

            # Create the frame and reparent the client window.
            self.reparenting = True
            self.frame = self.conn.generate_id()
            self.log.debug("Creating frame 0x%x.", self.frame)
            self.conn.core.CreateWindow(self.screen.root_depth,
                                        self.frame,
                                        self.screen.root,
                                        frame_geometry.x,
                                        frame_geometry.y,
                                        frame_geometry.width,
                                        frame_geometry.height,
                                        frame_geometry.border_width,
                                        WindowClass.InputOutput,
                                        self.screen.root_visual,
                                        CW.OverrideRedirect | CW.EventMask,
                                        [True, self.frame_event_mask])
            self.conn.core.ChangeSaveSet(SetMode.Insert, self.window)
            self.conn.core.ReparentWindow(self.window, self.frame,
                                          offset.x, offset.y)

            # Record the new window and frame geometries.
            self.geometry = geometry.reborder(0).move(offset.position())
            self.frame_geometry = frame_geometry
            self.offset = offset

        # Register for events on the client window and frame.
        self.conn.core.ChangeWindowAttributes(self.window,
                                              CW.EventMask,
                                              [self.client_event_mask])
        self.manager.register_window_handler(self.window, self)
        self.manager.register_window_handler(self.frame, self)

    @property
    def geometry(self):
        """Return the client window geometry relative to its parent's origin."""
        if self._geometry is None:
            self._geometry = get_window_geometry(self.conn, self.window)
        return self._geometry

    @geometry.setter
    def geometry(self, geometry):
        assert isinstance(geometry, Geometry), "invalid geometry %r" % geometry
        self._geometry = geometry

    @property
    def frame_geometry(self):
        """Return the geometry of the client's frame."""
        if self._frame_geometry is None:
            self._frame_geometry = get_window_geometry(self.conn, self.frame)
        return self._frame_geometry

    @frame_geometry.setter
    def frame_geometry(self, geometry):
        assert isinstance(geometry, Geometry), "invalid geometry %r" % geometry
        self._frame_geometry = geometry

    @property
    def absolute_geometry(self):
        """Return the client window geometry, relative to the root's origin,
        with the frame's border width."""
        bw = self.frame_geometry.border_width
        return self.geometry.move(self.frame_geometry.position() +
                                  self.offset.position()).reborder(bw)

    def absolute_to_frame_geometry(self, geometry):
        """Convert an absolute client window geometry to a frame geometry."""
        return (geometry.reborder(self.frame_geometry.border_width) -
                self.offset.position() +
                self.offset.size())

    def frame_to_absolute_geometry(self, geometry):
        """Convert a frame geometry to an absolute client geometry."""
        return (geometry.reborder(0) +
                self.offset.position() -
                self.offset.size())

    def move(self, position):
        """Move the frame and return its new position."""
        position = self.manager.constrain_position(self, position)
        self.conn.core.ConfigureWindow(self.frame,
                                       ConfigWindow.X | ConfigWindow.Y,
                                       map(int16, position))
        self.frame_geometry = self.frame_geometry.move(position)
        return position

    def resize(self, size, border_width=None, gravity=None):
        """Resize the client window and return the new geometry, which may
        differ in both size and position due to size constraints and gravity."""
        geometry = self.manager.constrain_size(self, self.absolute_geometry,
                                               size, border_width, gravity)
        return self.configure(geometry)

    def moveresize(self, geometry, gravity=None):
        """Change the client window geometry, respecting size hints and using
        the specified gravity. Returns the new geometry."""
        return self.configure(self.manager.constrain_size(self,
                                                          geometry,
                                                          gravity=gravity))

    def configure(self, geometry):
        """Given a requested client geometry in the root coordinate system,
        update the client and frame geometry accordingly. Returns the new
        client geometry."""
        frame_geometry = self.absolute_to_frame_geometry(geometry)
        self.conn.core.ConfigureWindow(self.frame,
                                       (ConfigWindow.X |
                                        ConfigWindow.Y |
                                        ConfigWindow.Width |
                                        ConfigWindow.Height |
                                        ConfigWindow.BorderWidth),
                                       [int16(frame_geometry.x),
                                        int16(frame_geometry.y),
                                        card16(frame_geometry.width),
                                        card16(frame_geometry.height),
                                        card16(frame_geometry.border_width)])
        self.frame_geometry = frame_geometry
        self.decorator.configure(frame_geometry)

        # See ICCCM §4.1.5.
        if self.geometry.size() != geometry.size():
            self.conn.core.ConfigureWindow(self.window,
                                           (ConfigWindow.Width |
                                            ConfigWindow.Height),
                                           [card16(geometry.width),
                                            card16(geometry.height)])
            self.geometry = self.geometry.resize(geometry.size())
        else:
            configure_notify(self.conn, self.window, *self.absolute_geometry)
        return geometry

    def restack(self, stack_mode):
        self.conn.core.ConfigureWindow(self.frame,
                                       ConfigWindow.StackMode,
                                       [stack_mode])

    def focus(self, time=Time.CurrentTime):
        """Offer the input focus to the client. Returns true if the client
        accepts the focus offer or is already focused, and false otherwise."""
        if self.properties.wm_state != WMState.NormalState:
            return False

        if time is None:
            # FocusIn events don't contain a timestamp, so the handler
            # for those events uses None as the time argument. In general,
            # this will indicate confirmation of focus initiated by a prior
            # SetInputFocus request. However, if we don't have a focus
            # time, it means that we were previously unfocused and are now
            # receiving the focus, presumably in PointerRoot mode. In that
            # case, we'll make a new focus offer with CurrentTime.
            self.decorator.focus()
            if self.focus_time is not None:
                return True
            time = Time.CurrentTime
        if self.focus_time is not None:
            # We could be called more than once in response to some request,
            # so we'll only update the focus if the timestamp is newer than
            # the last-focus time for this client.
            if time != Time.CurrentTime and time <= self.focus_time:
                return True

        def set_input_focus(window, time):
            self.log.debug("Setting input focus to window 0x%x at time %d.",
                           window, time)
            try:
                self.conn.core.SetInputFocusChecked(InputFocus.PointerRoot,
                                                    window,
                                                    time).check()
            except (BadMatch, BadWindow):
                self.log.warning("Error trying to focus window 0x%x.", window)
                return None
            else:
                return time
        if self.focus_override:
            # We'll occasionally want to preempt focus of a client window
            # (e.g., for user input in a titlebar).
            self.log.debug("Redirecting focus to window 0x%x.",
                           self.focus_override)
            self.focus_time = set_input_focus(self.focus_override, time)
        else:
            # See ICCCM §4.1.7.
            self.focus_time = None
            if (self.properties.wm_hints.flags & WMHints.InputHint == 0 or
                self.properties.wm_hints.input):
                self.focus_time = set_input_focus(self.window, time)
            if self.atoms["WM_TAKE_FOCUS"] in self.properties.wm_protocols:
                self.log.debug("Taking input focus at time %d.", time)
                send_client_message(self.conn, self.window, self.window, 0,
                                    32, self.atoms["WM_PROTOCOLS"],
                                    [self.atoms["WM_TAKE_FOCUS"], time,
                                     0, 0, 0])
                self.focus_time = time
        return self.focus_time is not None

    def unfocus(self):
        self.focus_time = None
        self.decorator.unfocus()

    def map(self):
        self.conn.core.MapWindow(self.window)
        self.conn.core.MapWindow(self.frame)

    def unmap(self):
        self.conn.core.UnmapWindow(self.frame)
        self.conn.core.UnmapWindow(self.window)

    def undecorate(self, destroyed=False):
        if self.decorated:
            try:
                self.decorator.undecorate()
            except (BadWindow, BadDrawable) as e:
                self.log.info("Received %s (%d) while removing decoration.",
                              e.__class__.__name__,
                              e.args[0].major_opcode)
            else:
                self.decorated = False

        if not destroyed:
            self.log.debug("Reparenting back to root window 0x%x.",
                           self.screen.root)
            with GrabServer(self.conn):
                # Compute the new window geometry based on the current frame
                # geometry, the original border width, and the window gravity.
                bw = self.original_border_width
                size = self.geometry.size()
                gravity = self.properties.wm_normal_hints.win_gravity
                geometry = self.frame_geometry.resize(size, bw, gravity)

                self.conn.core.ConfigureWindow(self.window,
                                               ConfigWindow.BorderWidth,
                                               [bw])
                self.conn.core.ReparentWindow(self.window,
                                              self.screen.root,
                                              geometry.x,
                                              geometry.y)
                self.conn.core.ChangeSaveSet(SetMode.Delete, self.window)

        self.conn.core.DestroyWindow(self.frame)
        self.frame = None

    def normalize(self):
        """Transition to the Normal state."""
        self.log.debug("Entering Normal state.")
        self.properties.wm_state = WMState(WMState.NormalState)
        self.properties.request_properties()
        if not self.decorated:
            try:
                self.decorator.decorate()
            except (BadWindow, BadDrawable) as e:
                self.log.info("Received %s (%d) while applying decoration.",
                              e.__class__.__name__,
                              e.args[0].major_opcode)
            else:
                self.decorated = True
        self.map()

    def iconify(self):
        """Transition to the Iconic state."""
        self.log.debug("Entering Iconic state.")
        self.properties.wm_state = WMState(WMState.IconicState)
        self.unmap()

    def withdraw(self):
        """Transition to the Withdrawn state."""
        self.log.debug("Entering Withdrawn state.")
        self.properties.wm_state = WMState(WMState.WithdrawnState)

    @handler(ReparentNotifyEvent)
    def handle_reparent_notify(self, event):
        self.log.debug("Done reparenting.")
        self.reparenting = False

    @handler(VisibilityNotifyEvent)
    def handle_visibility_notify(self, event):
        if event.window == self.frame:
            self.visibility = event.state

    @handler(WMChangeState)
    def handle_wm_change_state(self, client_message):
        if client_message.window != self.window:
            return
        state = client_message.data.data32[0]
        self.log.debug("Received change-state message (%d).", state)
        if state == WMState.IconicState:
            self.iconify()
