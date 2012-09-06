# -*- mode: Python; coding: utf-8 -*-

"""The clients of a window manager are top-level windows. This module provides
classes and routines for dealing with those as such."""

from contextlib import contextmanager
import exceptions
import logging

from xcb.xproto import *
import xcb.shape

from event import *
from geometry import *
from properties import *
from xutil import *

__all__ = ["Client"]

@client_message("WM_CHANGE_STATE")
class WMChangeState(ClientMessage):
    """Sent by a client that would like its state changed (ICCCM §4.1.4)."""
    pass

class Client(EventHandler, PropertyManager):
    """Represents a managed, top-level client window."""

    client_event_mask = (EventMask.EnterWindow |
                         EventMask.FocusChange |
                         EventMask.PropertyChange |
                         EventMask.StructureNotify)

    frame_event_mask = (EventMask.SubstructureRedirect |
                        EventMask.SubstructureNotify |
                        EventMask.EnterWindow |
                        EventMask.VisibilityChange)

    # ICCCM properties
    wm_name = PropertyDescriptor("WM_NAME", StringProperty, "")
    wm_icon_name = PropertyDescriptor("WM_ICON_NAME", StringProperty, "")
    wm_normal_hints = PropertyDescriptor("WM_NORMAL_HINTS",
                                         WMSizeHints, WMSizeHints())
    wm_hints = PropertyDescriptor("WM_HINTS", WMHints, WMHints())
    wm_class = PropertyDescriptor("WM_CLASS", WMClass, (None, None))
    wm_transient_for = PropertyDescriptor("WM_TRANSIENT_FOR", WindowProperty)
    wm_protocols = PropertyDescriptor("WM_PROTOCOLS", AtomList, [])
    wm_state = PropertyDescriptor("WM_STATE", WMState, WMState())

    # EWMH properties
    net_wm_name = PropertyDescriptor("_NET_WM_NAME",
                                     UTF8StringProperty, "")
    net_wm_icon_name = PropertyDescriptor("_NET_WM_ICON_NAME",
                                          UTF8StringProperty, "")

    # Dim-specific properties
    dim_tags = PropertyDescriptor("_DIM_TAGS", AtomList, [])

    def __init__(self, conn, manager, window, geometry, **kwargs):
        self.conn = conn
        self.manager = manager
        self.window = window
        self.screen = manager.screen
        self.atoms = manager.atoms
        self.colors = manager.colors
        self.cursors = manager.cursors
        self.fonts = manager.fonts
        self.keymap = manager.keymap
        self.transients = []
        self.decorator = manager.decorator(self)
        self.decorated = False
        self.shaped = False
        self.focus_time = None
        self.focus_override = None
        self.visibility = None
        self.log = logging.getLogger("client.0x%x" % self.window)

        super(Client, self).__init__(**kwargs)

        # Set the client's border width to 0, but save the current value
        # so that we can restore it if and when we reparent the client
        # back to the root.
        self.border_width = geometry.border_width
        self.conn.core.ConfigureWindow(self.window,
                                       ConfigWindow.BorderWidth,
                                       [0])

        # Compute the frame geometry based on the current geometry and the
        # requirements of our decorator.
        self.offset = self.decorator.compute_client_offset()
        self.frame_geometry = self.compute_frame_geometry(geometry)
        self.geometry = geometry.reborder(0).move(self.offset.position())

        # Create the frame and reparent the client window.
        self.frame = self.conn.generate_id()
        self.log.debug("Creating frame 0x%x.", self.frame)
        self.conn.core.CreateWindow(self.screen.root_depth,
                                    self.frame,
                                    self.screen.root,
                                    self.frame_geometry.x,
                                    self.frame_geometry.y,
                                    self.frame_geometry.width,
                                    self.frame_geometry.height,
                                    self.frame_geometry.border_width,
                                    WindowClass.InputOutput,
                                    self.screen.root_visual,
                                    CW.OverrideRedirect | CW.EventMask,
                                    [True, self.frame_event_mask])
        self.conn.core.ChangeSaveSet(SetMode.Insert, self.window)
        with self.disable_structure_notify():
            self.conn.core.ReparentWindow(self.window, self.frame,
                                          self.offset.x, self.offset.y)

        # Register for shape change notifications, and, if the client
        # window is shaped, adapt the frame to its shape.
        if self.manager.shape:
            self.manager.shape.SelectInput(self.window, True)
            extents = self.manager.shape.QueryExtents(self.window).reply()
            self.shaped = extents.bounding_shaped
            if self.shaped:
                self.set_frame_shape()

        # Register for events on the client window and frame.
        self.conn.core.ChangeWindowAttributes(self.window,
                                              CW.EventMask,
                                              [self.client_event_mask])
        self.manager.register_window_handler(self.window, self)
        self.manager.register_window_handler(self.frame, self)

        # If this window is a transient for another, establish a link
        # between them.
        transient_for = self.wm_transient_for
        if transient_for:
            other = self.manager.get_client(transient_for, True)
            if other:
                other.transients.append(self.window)

    def update_instance_for_different_class(self, *args, **kwargs):
        """Perform any necessary post-class-change updates. Receives the
        complete set of initialization arguments."""
        pass

    @contextmanager
    def disable_structure_notify(self):
        """A context manager that de-selectes StructureNotify on this client
        for the duration of its body."""
        # We must operate with the server grabbed to avoid race conditions.
        with grab_server(self.conn):
            with mask_events(self.conn, self.window,
                             self.client_event_mask,
                             EventMask.StructureNotify):
                yield

    def send_protocol_message(self, message, time):
        """Send a protocol message to the client (ICCCM §4.2.8)."""
        if message in self.wm_protocols:
            send_client_message(self.conn, self.window, False, 0,
                                self.window, self.atoms["WM_PROTOCOLS"],
                                32, [message, time, 0, 0, 0])
            return True
        return False

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

    def compute_frame_geometry(self, geometry):
        """Compute the frame geometry given a client-requested geometry."""
        return geometry.resize(geometry.size() + self.offset.size(),
                               self.decorator.border_width,
                               self.wm_normal_hints.win_gravity)

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

    def configure_request(self,
                          x=None, y=None,
                          width=None, height=None, border_width=None,
                          sibling=None, stack_mode=None):
        """Update the client configuration in response to a client request.
        If supplied, the x and y coordinates should be frame positions
        expressed in the root coordinate system. Width and height, if
        given, should be the requested width and height of the client
        window."""
        geometry = self.absolute_geometry
        if x is not None:
            geometry = geometry._replace(x=x + self.offset.x)
        if y is not None:
            geometry = geometry._replace(y=y + self.offset.y)
        if width is not None or height is not None:
            # Resize requests must respect the window gravity.
            size = Rectangle(width or geometry.width, height or geometry.height)
            gravity = self.wm_normal_hints.win_gravity
            geometry = geometry.resize(size, None, gravity)
        if border_width is not None:
            # We do not honor border width change requests, but we record them
            # in case the client is reparented, and we pass the requested
            # border width to configure so that it can report it correctly
            # to the client.
            self.border_width = border_width
            geometry = geometry.reborder(border_width)
        self.configure(geometry, sibling, stack_mode)

    def configure(self, geometry=None, sibling=None, stack_mode=None):
        """Update the client and frame configuration according to the given
        absolute geometry and stacking parameters, and return the new client
        geometry."""
        frame_value_mask = 0
        frame_value_list = []
        if geometry is None:
            geometry = self.absolute_geometry
        else:
            self.frame_geometry = self.absolute_to_frame_geometry(geometry)
            self.decorator.configure(self.frame_geometry)
            frame_value_mask |= (ConfigWindow.X |
                                 ConfigWindow.Y |
                                 ConfigWindow.Width |
                                 ConfigWindow.Height)
            frame_value_list += [int16(self.frame_geometry.x),
                                 int16(self.frame_geometry.y),
                                 card16(self.frame_geometry.width),
                                 card16(self.frame_geometry.height)]
        if stack_mode is not None:
            if sibling is not None:
                frame_value_mask |= ConfigWindow.Sibling
                frame_value_list += [sibling]
            frame_value_mask |= ConfigWindow.StackMode
            frame_value_list += [stack_mode]
        self.conn.core.ConfigureWindow(self.frame,
                                       frame_value_mask,
                                       frame_value_list)

        # If we change the window configuration, the client will receive
        # a real ConfigureNotify from the server; otherwise, we'll send a
        # synthetic one. See ICCCM §4.1.5 for details.
        if self.geometry.size() != geometry.size():
            self.conn.core.ConfigureWindow(self.window,
                                           (ConfigWindow.Width |
                                            ConfigWindow.Height),
                                           [card16(geometry.width),
                                            card16(geometry.height)])
            self.geometry = self.geometry.resize(geometry.size())
        else:
            # The synthetic ConfigureNotify event must be adjusted for and
            # include the requested border width, even if we don't actually
            # set it.
            configure_notify(self.conn, self.window,
                             *self.absolute_geometry.resize(geometry.size(),
                                                            geometry.border_width,
                                                            Gravity.Static))
        return geometry

    def set_frame_shape(self):
        self.manager.shape.Combine(xcb.shape.SO.Set,
                                   xcb.shape.SK.Bounding,
                                   xcb.shape.SK.Bounding,
                                   self.frame,
                                   self.offset.x,
                                   self.offset.y,
                                   self.window)
        self.decorator.update_frame_shape()

    def reset_frame_shape(self):
        self.manager.shape.Mask(xcb.shape.SO.Set,
                                xcb.shape.SK.Bounding,
                                self.frame,
                                0, 0,
                                Pixmap._None)
        self.manager.shape.Mask(xcb.shape.SO.Set,
                                xcb.shape.SK.Clip,
                                self.frame,
                                0, 0,
                                Pixmap._None)

    def focus(self, time=Time.CurrentTime):
        """Offer the input focus to the client. Returns true if the client
        accepts the focus offer or is already focused, and false otherwise."""
        if self.wm_state != WMState.NormalState:
            return False

        if time is None:
            # FocusIn events don't contain a timestamp, so the handler for
            # those events use None as the time argument. No other callers
            # should do that, so if we're here, we know that we have the
            # focus, and can tell our decorator to indicate that fact.
            self.decorator.focus()

            # If we have a focus time, then we're receiving the focus due
            # to an earlier call to this method, and we can just return. If
            # not, then we were previously unfocused and are now receiving
            # the focus via some other mechanism (possibly in PointerRoot
            # mode), and so we'll make a new focus offer.
            if self.focus_time is not None:
                return True
            time = Time.CurrentTime

        # We might be called more than once in response to some request,
        # so we'll only update the focus if the timestamp is newer than
        # the last-focus time for this client.
        if self.focus_time and compare_timestamps(self.focus_time, time) >= 0:
            return True

        def set_input_focus(window, time):
            self.log.debug("Setting input focus to window 0x%x at time %d.",
                           window, time)
            try:
                self.conn.core.SetInputFocusChecked(InputFocus.PointerRoot,
                                                    window, time).check()
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
            if (self.wm_hints.flags & WMHints.InputHint == 0 or
                self.wm_hints.input):
                self.focus_time = set_input_focus(self.window, time)
            if self.send_protocol_message(self.atoms["WM_TAKE_FOCUS"], time):
                self.log.debug("Taking input focus at time %d.", time)
                self.focus_time = time
        return self.focus_time is not None

    def unfocus(self):
        self.decorator.unfocus()

    def map(self):
        self.conn.core.MapWindow(self.window)
        self.conn.core.MapWindow(self.frame)

    def unmap(self):
        self.conn.core.UnmapWindow(self.frame)
        with self.disable_structure_notify():
            self.conn.core.UnmapWindow(self.window)

    def undecorate(self, destroyed=False, reparented=False):
        """Remove all decorations from the client window, and (maybe)
        reparent it back to the root window."""
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
            bw = self.border_width
            self.conn.core.ConfigureWindow(self.window,
                                           ConfigWindow.BorderWidth,
                                           [bw])
            if not reparented:
                self.log.debug("Reparenting back to root window 0x%x.",
                               self.screen.root)
                size = self.geometry.size()
                gravity = self.wm_normal_hints.win_gravity
                geometry = self.frame_geometry.resize(size, bw, gravity)
                with self.disable_structure_notify():
                    try:
                        self.conn.core.ReparentWindowChecked(self.window,
                                                             self.screen.root,
                                                             geometry.x,
                                                             geometry.y).check()
                    except BadWindow:
                        pass
                    else:
                        self.conn.core.ChangeSaveSet(SetMode.Delete,
                                                     self.window)

        self.conn.core.DestroyWindow(self.frame)
        self.frame = None

    def normalize(self):
        """Transition to the Normal state."""
        self.log.debug("Entering Normal state.")
        self.wm_state = WMState(WMState.NormalState)
        self.request_properties()
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

        # Map any windows that are transient for this one.
        for transient in list(self.transients):
            client = self.manager.get_client(transient, True)
            if client:
                client.normalize()
            else:
                self.log.warning("Lost transient 0x%x.", transient)
                self.transients.remove(transient)

    def iconify(self):
        """Transition to the Iconic state."""
        self.log.debug("Entering Iconic state.")
        self.wm_state = WMState(WMState.IconicState)
        self.unmap()

        # Iconify any windows that are transient for this one.
        for transient in self.transients:
            client = self.manager.get_client(transient, True)
            if client:
                client.iconify()

    def withdraw(self):
        """Transition to the Withdrawn state."""
        self.log.debug("Entering Withdrawn state.")
        self.wm_state = WMState(WMState.WithdrawnState)

    def delete(self, time=Time.CurrentTime):
        """Ask the client to delete its top-level window."""
        self.send_protocol_message(self.atoms["WM_DELETE_WINDOW"], time)

    @handler(DestroyNotifyEvent)
    def handle_destroy_notify(self, event):
        if event.window == self.window:
            transient_for = self.wm_transient_for
            if transient_for:
                other = self.manager.get_client(transient_for, True)
                if other:
                    try:
                        other.transients.remove(self.window)
                    except exceptions.ValueError:
                        pass
        raise UnhandledEvent(event)

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

    @handler(xcb.shape.NotifyEvent)
    def handle_shape_notify(self, event):
        if (event.affected_window != self.window or
            event.shape_kind != xcb.shape.SK.Bounding):
            return
        if self.shaped and not event.shaped:
            self.reset_frame_shape()
        elif event.shaped:
            self.set_frame_shape()
        self.shaped = event.shaped
