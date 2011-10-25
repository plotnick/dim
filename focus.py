# -*- mode: Python; coding: utf-8 -*-

from logging import basicConfig as logconfig, debug, info, warning, error

from xcb.xproto import *

from event import UnhandledEvent, handler
from manager import NoSuchClient, WindowManager, ReparentingWindowManager

__all__ = ["FocusFollowsMouse", "SloppyFocus", "ClickToFocus"]

class FocusPolicy(WindowManager):
    """A focus policy determines how and when to assign the input focus to the
    client windows."""

    def __init__(self, *args, **kwargs):
        self.current_focus = None
        self.pending_focus = ()
        super(FocusPolicy, self).__init__(*args, **kwargs)

    def adopt(self, windows):
        self.reparenting_initial_clients = set()
        for window in windows:
            client = self.manage(window)
            if client and client.frame and client.reparenting:
                self.reparenting_initial_clients.add(client)
        self.initial_focus()

    def normalize(self, client):
        if super(FocusPolicy, self).normalize(client):
            if self.reparenting_initial_clients is not None:
                self.reparenting_initial_clients.discard(client)
                self.initial_focus()
            return client

    def initial_focus(self):
        """Query for and set the initial focus."""
        # We need to wait to set the initial focus until all of the initial
        # clients are done reparenting (if they need reparenting). Otherwise,
        # the pointer might be over a window that is temporarily unmapped but
        # that ought to get the initial focus.
        if self.reparenting_initial_clients:
            return
        else:
            self.reparenting_initial_clients = None

        def focus(window):
            try:
                client = self.get_client(window)
            except NoSuchClient:
                return
            debug("Setting initial focus to window 0x%x." % window)
            self.focus(client, Time.CurrentTime, False)

        window = self.conn.core.GetInputFocus().reply().focus
        if window == InputFocus.PointerRoot:
            # We're in PointerRoot mode (i.e., focus-follows-mouse), so we
            # need to query the server for the window currently containing
            # the pointer.
            reply = self.conn.core.QueryPointer(self.screen.root).reply()
            if reply and reply.child:
                focus(reply.child)
            else:
                info("No window currently has the focus.")
        else:
            focus(window)

    def focus(self, client, time, have_focus):
        """Give the given client the input focus."""
        if client is self.current_focus:
            return True
        if not have_focus and self.pending_focus != (client, time):
            debug("Attempting to focus client window 0x%x." % client.window)
            self.pending_focus = (client, time)
            if not client.focus(time):
                return False
        if have_focus:
            debug("Client window 0x%x now has the focus." % client.window)
            client.decorator.focus()
            self.current_focus = client
            return True

    def unfocus(self, client):
        """Unfocus the currently focused client."""
        debug("Unfocusing client window 0x%x." % client.window)
        client.unfocus()
        if client is self.current_focus:
            self.current_focus = None
        elif self.current_focus:
            warning("Unfocused client was not the current focus; 0x%x was." %
                    self.current_focus.window)

    @handler(FocusInEvent)
    def handle_focus_in(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            raise UnhandledEvent(event)
        debug("Window 0x%x got the focus." % event.event)
        self.focus(self.get_client(event.event), Time.CurrentTime, True)

    @handler(FocusOutEvent)
    def handle_focus_out(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            raise UnhandledEvent(event)
        debug("Window 0x%x lost the focus." % event.event)
        self.unfocus(self.get_client(event.event))

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
        self.focus(self.get_client(event.event), event.time,
                   event.same_screen_focus & 1)

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
            self.grab_focus_click(client)
        return client

    def grab_focus_click(self, client):
        self.conn.core.GrabButton(False, client.frame,
                                  EventMask.ButtonPress,
                                  GrabMode.Sync, GrabMode.Async,
                                  Window._None, Cursor._None,
                                  1, ModMask.Any)

    def focus(self, client, time, have_focus):
        super(ClickToFocus, self).focus(client, time, have_focus)

        # Once a client is focused, we can release our grab. This is purely
        # an optimization: we don't want to be responsible for proxying all
        # button press events to the client. We'll re-establish our grab
        # when the client loses focus.
        self.conn.core.UngrabButton(1, client.frame, ModMask.Any)

    def unfocus(self, client):
        if client is self.current_focus:
            self.grab_focus_click(client)
        super(ClickToFocus, self).unfocus(client)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        try:
            client = self.frames[event.event]
        except KeyError:
            raise UnhandledEvent(event)
        debug("Button %d press in window 0x%x." % (event.detail, event.event))
        if self.ignore_focus_click:
            self.conn.core.UngrabPointer(event.time)
        else:
            self.conn.core.AllowEvents(Allow.ReplayPointer, event.time)
        self.focus(client, event.time, False)
