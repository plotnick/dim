# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error

from xcb.xproto import *

from event import UnhandledEvent, handler
from manager import WindowManager, ReparentingWindowManager

__all__ = ["FocusFollowsMouse", "SloppyFocus", "ClickToFocus"]

class InitialFocusEvent(object):
    """A pseudo-event class used for establishing the initial focus at WM
    start-up time."""
    def __init__(self, window):
        self.event = window
        self.time = Time.CurrentTime

def is_focus_event(event):
    """Return true if the event window has the input focus."""
    if isinstance(event, (FocusInEvent, InitialFocusEvent)):
        return True
    elif isinstance(event, FocusOutEvent):
        return False
    elif isinstance(event, (EnterNotifyEvent, LeaveNotifyEvent)):
        return event.same_screen_focus & 1
    else:
        return False

def event_time(event):
    """Not all events have a timestamp (e.g., FocusIn/FocusOut); this function
    simply returns CurrentTime if the event lacks a time."""
    return event.time if hasattr(event, "time") else Time.CurrentTime

class FocusPolicy(WindowManager):
    """A focus policy determines how and when to assign the input focus to the
    client windows."""

    set_focus = True

    def __init__(self, *args, **kwargs):
        self.current_focus = None
        super(FocusPolicy, self).__init__(*args, **kwargs)

        # Try to determine which client currently has the focus.
        focus = self.conn.core.GetInputFocus().reply().focus
        if focus == InputFocus.PointerRoot:
            # We're in PointerRoot mode (i.e., focus-follows-mouse), so we
            # need to query the server for the window currently containing
            # the pointer.
            reply = self.conn.core.QueryPointer(self.screen.root).reply()
            if reply and reply.child:
                self.initial_focus(reply.child)
            else:
                info("No window currently has the focus.")
        else:
            self.initial_focus(focus)

    def initial_focus(self, window):
        """Set the initial focus to the given window."""
        debug("Setting initial focus to window 0x%x." % window)
        try:
            self.focus(self.get_client(window), InitialFocusEvent(window))
        except UnhandledEvent:
            pass

    def focus(self, client, event):
        """Set the input focus to the event window."""
        if client == self.current_focus:
            debug("Ignoring re-focus of window 0x%x." % client.window)
            return True
        debug("Attempting to focus window 0x%x." % client.window)
        if client.focus(self.set_focus, event_time(event)):
            self.unfocus(event)
            if is_focus_event(event):
                # If the event claims we have the focus now, don't bother
                # waiting for a FocusIn event to record the current focus.
                self.current_focus = client
            return client

    def unfocus(self, event):
        """Unfocus the currently focused client."""
        if self.current_focus:
            debug("Unfocusing window 0x%x." % self.current_focus.window)
            self.current_focus.unfocus()
            self.current_focus = None
            return True

    @handler(FocusInEvent)
    def handle_focus_in(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            raise UnhandledEvent(event)
        client = self.get_client(event.event)
        if self.current_focus and self.current_focus != client:
            debug("Window 0x%x stole the focus." % client.window)
            self.focus(client, event)
        else:
            debug("Window 0x%x got focus." % client.window)
            self.current_focus = client

class FocusFollowsMouse(FocusPolicy):
    """Let the input focus follow the pointer. We track which top-level
    window currently has focus only so that we can correctly update the
    client decoration."""

    set_focus = False

    def __init__(self, *args):
        super(FocusFollowsMouse, self).__init__(*args)

        # Set focus mode to PointerRoot (i.e., focus-follows-mouse). This is
        # the one and only time this policy will make a SetInputFocus request.
        self.conn.core.SetInputFocus(InputFocus.PointerRoot,
                                     InputFocus.PointerRoot,
                                     Time.CurrentTime)

    @handler(EnterNotifyEvent)
    def handle_enter_notify(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            return
        debug("Window 0x%x entered (%d)." % (event.event, event.detail))
        self.focus(self.get_client(event.event), event)

    @handler(LeaveNotifyEvent)
    def handle_leave_notify(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            return
        debug("Window 0x%x left (%d)." % (event.event, event.detail))
        self.unfocus(event)

class SloppyFocus(FocusPolicy):
    """Let the input focus follow the pointer, except that if the pointer
    moves into the root window or a window that refuses to take focus, the
    most-recently focused window retains its focus."""

    @handler(EnterNotifyEvent)
    def handle_enter_notify(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            return
        debug("Window 0x%x entered (%d)." % (event.event, event.detail))
        self.focus(self.get_client(event.event), event)

class ClickToFocus(FocusPolicy, ReparentingWindowManager):
    """Focus ignores the movement of the pointer, and changes only when
    button 1 is pressed in a client window.

    In order to intercept focus clicks, we need to establish a passive grab
    on the pointer button for each client window. However, ICCCM §6.3 states
    that "[c]lients should establish button and key grabs only on windows that
    they own." This policy therefore requires a reparenting window manager,
    and establishes grabs only on the frames that we create, and not on the
    client windows themselves."""

    def __init__(self, conn, screen=None, ignore_focus_click=False, **kwargs):
        self.ignore_focus_click = ignore_focus_click
        super(ClickToFocus, self).__init__(conn, screen, **kwargs)

    def manage(self, window):
        client = super(ClickToFocus, self).manage(window)
        if client:
            self.grab_focus_click(client.frame)
        return client

    def grab_focus_click(self, window):
        self.conn.core.GrabButton(False, window,
                                  EventMask.ButtonPress,
                                  GrabMode.Sync, GrabMode.Async,
                                  Window._None, Cursor._None,
                                  1, ModMask.Any)

    def focus(self, client, event):
        super(ClickToFocus, self).focus(client, event)

        # Once a client is focused, we can release our grab. This is purely
        # an optimization: we don't want to be responsible for proxying all
        # button press events to the client. We'll re-establish our grab
        # when the client loses focus.
        self.conn.core.UngrabButton(1, client.frame, ModMask.Any)

    def unfocus(self, event):
        if self.current_focus:
            self.grab_focus_click(self.current_focus.frame)
        super(ClickToFocus, self).unfocus(event)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        try:
            client = self.frames[event.event]
        except KeyError:
            raise UnhandledEvent(event)
        debug("Button %d press in window 0x%x." % (event.detail, event.event))
        if not self.ignore_focus_click:
            self.conn.core.AllowEvents(Allow.ReplayPointer, Time.CurrentTime)
        self.conn.core.UngrabPointer(Time.CurrentTime)
        self.focus(client, event)
