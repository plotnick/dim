# -*- mode: Python; coding: utf-8 -*-

import logging

from xcb.xproto import *

from event import UnhandledEvent, handler
from manager import NoSuchClient, WindowManager, ReparentingWindowManager
from properties import WMState
from xutil import notify_detail_name

__all__ = ["FocusPolicy", "SloppyFocus", "ClickToFocus"]

class FocusPolicy(WindowManager):
    """A focus policy determines how and when to assign the input focus to the
    client windows."""

    __log = logging.getLogger("focus")

    def __init__(self, *args, **kwargs):
        self.current_focus = None
        self.pending_focus = None
        super(FocusPolicy, self).__init__(*args, **kwargs)

    def adopt(self, windows):
        self.reparenting_initial_clients = set()
        for window in windows:
            client = self.manage(window)
            if client and client.reparenting:
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

        focus = self.conn.core.GetInputFocus().reply().focus
        if focus == InputFocus.PointerRoot:
            # If we're in PointerRoot mode, we need to query the server
            # again for the window currently containing the pointer.
            focus = self.conn.core.QueryPointer(self.screen.root).reply().child
        if focus:
            try:
                client = self.get_client(focus)
            except NoSuchClient:
                return
            self.__log.debug("Setting initial focus to window 0x%x.", focus)
            self.focus(client, Time.CurrentTime)
        else:
            self.__log.debug("No window currently has the focus.")

    def focus(self, client, time):
        """Offer the given client the input focus."""
        if client.properties.wm_state != WMState.NormalState:
            return False
        if client == self.current_focus or client == self.pending_focus:
            return True
        self.__log.debug("Attempting to focus client window 0x%x.",
                       client.window)
        if client.focus(time):
            self.pending_focus = client
            return True
        else:
            self.__log.debug("Client window 0x%x declined the focus offer.",
                           client.window)
            self.pending_focus = None
            return False

    def client_focused(self, client):
        self.__log.debug("Client window 0x%x now has the focus.", client.window)
        self.current_focus = client
        if self.pending_focus:
            if client != self.pending_focus:
                self.__log.warning("Unexpected client got the focus.")
            self.pending_focus = None
        client.decorator.focus()

    def unfocus(self, client):
        """Unfocus the currently focused client."""
        if client.properties.wm_state != WMState.NormalState:
            return False
        self.__log.debug("Unfocusing client window 0x%x.", client.window)
        client.unfocus()
        if client == self.current_focus:
            self.current_focus = None
        elif self.current_focus:
            self.__log.warning("Unfocused client was not the current focus; "
                               "0x%x was.", self.current_focus.window)

    @handler(FocusInEvent)
    def handle_focus_in(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            raise UnhandledEvent(event)
        self.__log.debug("Window 0x%x got the focus (%s).",
                         event.event, notify_detail_name(event))
        self.client_focused(self.get_client(event.event))

    @handler(FocusOutEvent)
    def handle_focus_out(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            raise UnhandledEvent(event)
        self.__log.debug("Window 0x%x lost the focus (%s).",
                         event.event, notify_detail_name(event))
        self.unfocus(self.get_client(event.event))

class SloppyFocus(FocusPolicy):
    """Let the input focus follow the pointer, except that if the pointer
    moves into the root window or a window that refuses to take focus, the
    most-recently focused window retains its focus."""

    __log = logging.getLogger("focus.sloppy")

    @handler(EnterNotifyEvent)
    def handle_enter_notify(self, event):
        if event.mode != NotifyMode.Normal or \
                event.detail == NotifyDetail.Inferior:
            return
        self.__log.debug("Window 0x%x entered (%s).",
                         event.event, notify_detail_name(event))
        client = self.get_client(event.event)
        self.focus(client, event.time)
        if event.same_screen_focus & 1:
            self.client_focused(client)

class ClickToFocus(FocusPolicy, ReparentingWindowManager):
    """Focus ignores the movement of the pointer, and changes only when
    button 1 is pressed in a client window.

    In order to intercept focus clicks, we need to establish a passive grab
    on the pointer button for each client window. However, ICCCM §6.3 states
    that "[c]lients should establish button and key grabs only on windows that
    they own." This policy therefore requires a reparenting window manager,
    and establishes grabs only on the frames that we create, and not on the
    client windows themselves."""

    __log = logging.getLogger("focus.click")

    def __init__(self, display=None, screen=None,
                 ignore_focus_click=False, **kwargs):
        self.ignore_focus_click = ignore_focus_click
        super(ClickToFocus, self).__init__(display, screen, **kwargs)

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

    def focus(self, client, time):
        super(ClickToFocus, self).focus(client, time)

        # Once a client is focused, we can release our grab. This is purely
        # an optimization: we don't want to be responsible for proxying all
        # button press events to the client. We'll re-establish our grab
        # when the client loses focus.
        self.conn.core.UngrabButton(1, client.frame, ModMask.Any)

    def unfocus(self, client):
        if client == self.current_focus:
            self.grab_focus_click(client)
        super(ClickToFocus, self).unfocus(client)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        try:
            client = self.frames[event.event]
        except KeyError:
            raise UnhandledEvent(event)
        self.__log.debug("Button %d press in window 0x%x.",
                         event.detail, event.event)
        if self.ignore_focus_click:
            self.conn.core.UngrabPointer(event.time)
        else:
            self.conn.core.AllowEvents(Allow.ReplayPointer, event.time)
        self.focus(client, event.time)
