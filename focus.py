# -*- mode: Python; coding: utf-8 -*-

from collections import deque
import logging
import exceptions

from xcb.xproto import *

from event import UnhandledEvent, handler
from manager import *
from properties import WMState
from xutil import *

__all__ = ["FocusPolicy", "SloppyFocus", "ClickToFocus"]

@client_message("_DIM_ENSURE_FOCUS")
class EnsureFocus(ClientMessage):
    """Try to ensure that some client has the input focus."""
    pass

class FocusPolicy(WindowManager):
    """A focus policy determines how and when to assign the input focus to the
    client windows."""

    __log = logging.getLogger("focus")

    def __init__(self, *args, **kwargs):
        super(FocusPolicy, self).__init__(*args, **kwargs)
        self.focus_list = deque() # most-recently focused first

    def adopt(self, windows):
        focus = get_input_focus(self.conn)

        super(FocusPolicy, self).adopt(windows)

        try:
            client = self.get_client(focus, True)
        except NoSuchClient:
            client = None
        self.ensure_focus(client)

    def manage(self, window):
        client = super(FocusPolicy, self).manage(window)
        if client:
            self.focus_list.append(client)
        return client

    def unmanage(self, client):
        try:
            self.focus_list.remove(client)
        except exceptions.ValueError:
            pass
        return super(FocusPolicy, self).unmanage(client)

    def focus(self, client, time):
        """Offer the input focus to a client. If the offer is accepted,
        returns true and moves the client to the head of the focus list;
        otherwise, returns false."""
        if client.focus(time):
            try:
                self.focus_list.remove(client)
            except exceptions.ValueError:
                pass
            self.focus_list.appendleft(client)
            return True
        else:
            return False

    def unfocus(self, client):
        """Note that a client no longer has the input focus."""
        client.unfocus()

    def update_tagset(self, window, name, deleted, time):
        super(FocusPolicy, self).update_tagset(window, name, deleted, time)
        self.ensure_focus(time=time)

    @handler(FocusInEvent)
    def handle_focus_in(self, event):
        if (event.mode != NotifyMode.Normal or
            event.detail == NotifyDetail.Inferior or
            event.detail == NotifyDetail.Pointer):
            raise UnhandledEvent(event)
        self.__log.debug("Window 0x%x got the focus (%s).",
                         event.event, notify_detail_name(event))
        self.focus(self.get_client(event.event), None)

    @handler(FocusOutEvent)
    def handle_focus_out(self, event):
        if (event.mode != NotifyMode.Normal or
            event.detail == NotifyDetail.Inferior or
            event.detail == NotifyDetail.Pointer):
            raise UnhandledEvent(event)
        self.__log.debug("Window 0x%x lost the focus (%s).",
                         event.event, notify_detail_name(event))
        self.unfocus(self.get_client(event.event))

    def ensure_focus(self, client=None, time=Time.CurrentTime):
        # We use a client message for ensuring focus so that we can be sure
        # that any outstanding requests or events generated as a result
        # thereof have been completely processed before we go groveling
        # through the focus list.
        send_client_message(self.conn, self.screen.root, self.screen.root,
                            (EventMask.SubstructureRedirect |
                             EventMask.StructureNotify),
                            32, self.atoms["_DIM_ENSURE_FOCUS"],
                            [time, client.window if client else 0, 0, 0, 0])

    @handler(EnsureFocus)
    def handle_ensure_focus(self, client_message):
        """Attempt to focus a client."""
        # There should be a timestamp in the first data slot and a window ID
        # (which may be None) in the second.
        time, window = client_message.data.data32[:2]
        self.__log.debug("Received ensure-focus message (0x%x, %d).",
                         window, time)

        def choose_focus_client():
            # Start with the window specified in the message, if any.
            if window:
                try:
                    yield self.get_client(window, True)
                except NoSuchClient:
                    pass

            # Next we'll try the focus list, starting with the most recently
            # focused client. We run over a copy because failed focus attempts
            # will cause clients to be removed from the focus list.
            for client in list(self.focus_list):
                yield client

            # Now try the window that has the input focus, if there is one.
            focus = get_input_focus(self.conn, self.screen)
            if focus:
                try:
                    yield self.get_client(focus, True)
                except NoSuchClient:
                    pass

            # Finally, we'll just pick clients at random.
            for client in set(self.clients.values()) - set(self.focus_list):
                yield client

        for client in choose_focus_client():
            if self.focus(client, time):
                break
        else:
            self.__log.debug("Couldn't find a client to focus.")

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
        self.focus(self.get_client(event.event), event.time)

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

    def framed(self, client):
        super(ClickToFocus, self).framed(client)
        self.grab_focus_click(client)

    def grab_focus_click(self, client):
        self.conn.core.GrabButton(False, client.frame,
                                  EventMask.ButtonPress,
                                  GrabMode.Sync, GrabMode.Async,
                                  Window._None, Cursor._None,
                                  1, ModMask.Any)

    def focus(self, client, time):
        if super(ClickToFocus, self).focus(client, time):
            # Once a client is focused, we can release our grab. This is
            # purely an optimization: we don't want to be responsible
            # for proxying all button press events to the client. We'll
            # re-establish our grab when the client loses focus.
            self.conn.core.UngrabButton(1, client.frame, ModMask.Any)
            return True
        else:
            return False

    def unfocus(self, client):
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
