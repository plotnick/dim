# -*- mode: Python; coding: utf-8 -*-

from collections import deque
import logging
import exceptions

from xcb.xproto import *

from event import handler
from manager import *
from properties import WMState
from xutil import *

__all__ = ["FocusPolicy", "SloppyFocus", "ClickToFocus"]

@client_message("_DIM_ENSURE_FOCUS")
class EnsureFocus(ClientMessage):
    """Try to ensure that some client has the input focus."""
    pass

class FocusPolicy(WindowManager):
    """A focus policy determines how and when to assign the input focus."""

    __log = logging.getLogger("focus")

    def __init__(self, **kwargs):
        super(FocusPolicy, self).__init__(**kwargs)

        self.focus_list = deque() # most-recently focused first
        self.pending_focus = None # from an EnsureFocus message

        # Create a default focus window. We'll give the input focus to this
        # window when no client window has it so that global key bindings
        # continue to work.
        self.default_focus_window = self.conn.generate_id()
        self.conn.core.CreateWindowChecked(0,
                                           self.default_focus_window,
                                           self.screen.root,
                                           0, 0, 1, 1, 0,
                                           WindowClass.InputOnly,
                                           self.screen.root_visual,
                                           CW.OverrideRedirect,
                                           [True]).check()
        self.key_bindings.establish_grabs(self.default_focus_window)
        self.conn.core.MapWindow(self.default_focus_window)

    def shutdown(self, *args):
        if self.conn:
            self.conn.core.SetInputFocus(InputFocus.PointerRoot,
                                         InputFocus.PointerRoot,
                                         Time.CurrentTime)
        super(FocusPolicy, self).shutdown(*args)

    def adopt(self, windows):
        focus = get_input_focus(self.conn)
        super(FocusPolicy, self).adopt(windows)
        self.ensure_focus(focus)

    def unmanage(self, client, **kwargs):
        try:
            self.focus_list.remove(client)
        except exceptions.ValueError:
            pass
        return super(FocusPolicy, self).unmanage(client, **kwargs)

    def focus(self, client, time):
        """Offer the input focus to a client. If the offer is accepted,
        return true and move the client to the head of the focus list;
        otherwise, return false."""
        if client and client.focus(time):
            try:
                self.focus_list.remove(client)
            except exceptions.ValueError:
                pass
            self.focus_list.appendleft(client)
            return True
        return False

    def focus_default_window(self, time):
        """Set the input focus to our default focus window."""
        if time is None:
            time = Time.CurrentTime
        self.__log.debug("Focusing default focus window at time %d.", time)
        self.conn.core.SetInputFocus(InputFocus.PointerRoot,
                                     self.default_focus_window,
                                     time)

    def unfocus(self, client):
        """Note that a client no longer has the input focus."""
        client.unfocus()

    @property
    def current_focus(self):
        try:
            return self.focus_list[0]
        except IndexError:
            return super(FocusPolicy, self).current_focus

    def ensure_focus(self, client=None, time=Time.CurrentTime):
        """Send a message to ourselves requesting that some client receive
        the input focus. If the client argument is provided, it must be
        either a client instance or a window; that window will be tried
        first in the search for a client to focus."""
        # We use a client message for ensuring focus so that we can be sure
        # that any outstanding requests or events generated as a result
        # thereof have been completely processed before we go groveling
        # through the focus list. See the EnsureFocus handler, below,
        # for the the actual algorithm.
        window = (Window._None
                  if client is None
                  else getattr(client, "window", client))
        send_client_message(self.conn, self.screen.root, False,
                            (EventMask.SubstructureRedirect |
                             EventMask.SubstructureNotify),
                            self.screen.root, self.atoms["_DIM_ENSURE_FOCUS"],
                            32, [time, window, 0, 0, 0])

    def update_for_changed_mapping(self):
        super(FocusPolicy, self).update_for_changed_mapping()
        self.key_bindings.establish_grabs(self.default_focus_window)

    @handler((FocusInEvent, FocusOutEvent))
    def handle_focus_event(self, event):
        if (event.detail == NotifyDetail.Inferior or
            event.detail == NotifyDetail.Pointer):
            return
        client = self.get_client(event.event)
        if not client:
            return
        self.__log.debug("Client window 0x%x got %s (%s, %s).",
                         client.window, event.__class__.__name__,
                         notify_detail_name(event), notify_mode_name(event))
        if isinstance(event, FocusInEvent):
            if self.pending_focus:
                if client.window == self.pending_focus:
                    self.pending_focus = None
                else:
                    self.__log.debug("Ignoring FocusIn pending focus of 0x%x.",
                                     self.pending_focus)
                    return
            self.focus(client, None)
        else:
            self.unfocus(client)

    @handler(UnmapNotifyEvent)
    def handle_unmap_notify(self, event):
        if event.from_configure or event.window != event.event:
            return
        client = self.get_client(event.window, True)
        if client and client == self.current_focus:
            # Losing the current focus; try to focus another window.
            self.__log.debug("Ensuring focus due to UnmapNotify event.")
            self.ensure_focus()

    @handler(EnsureFocus)
    def handle_ensure_focus(self, client_message):
        # There should be a timestamp in the first data slot and a window ID
        # (which may be None) in the second.
        time, window = client_message.data.data32[:2]
        self.__log.debug("Received ensure-focus message (0x%x, %d).",
                         window, time)

        def choose_focus_client():
            # Start with the window specified in the message, if any.
            if window:
                client = self.get_client(window, True)
                if client:
                    yield client

            # Next we'll try the focus list, starting with the most recently
            # focused client. We run over a copy because failed focus attempts
            # will cause clients to be removed from the focus list.
            for client in list(self.focus_list):
                yield client

            # Now try the window that has the input focus, if there is one.
            focus = get_input_focus(self.conn, self.screen)
            if focus:
                client = self.get_client(focus, True)
                if client:
                    yield client

            # Finally, we'll just pick clients at random.
            for client in set(self.clients.values()) - set(self.focus_list):
                yield client

        for client in choose_focus_client():
            if self.focus(client, time):
                self.pending_focus = client
                break
        else:
            self.pending_focus = None
            self.focus_default_window(time)

class FocusNewWindows(FocusPolicy):
    """Give newly-normalized windows the focus immediately."""

    __log = logging.getLogger("focus.new")

    def change_state(self, client, initial, final):
        super(FocusPolicy, self).change_state(client, initial, final)

        if (initial, final) == (WMState.WithdrawnState, WMState.NormalState):
            self.__log.debug("Focusing new window 0x%x.", client.window)
            self.ensure_focus(client)

class SloppyFocus(FocusPolicy):
    """Let the input focus follow the pointer, except that if the pointer
    moves into the root window or a window that refuses to take focus, the
    most-recently focused window retains its focus."""

    __log = logging.getLogger("focus.sloppy")

    def __init__(self, **kwargs):
        super(SloppyFocus, self).__init__(**kwargs)

        # In a comment in the source of AHWM (event.c,v 1.72 2002/02/16),
        # Alex Hioreanu writes:
        #
        #   We want to discriminate between EnterNotify events caused by
        #   the user moving the mouse and EnterNotify events caused by a
        #   change in the window configuration brought about by either
        #   this window manager or clients unmapping themselves, etc.
        #
        # He proceeds to suggest a strategy for performing this
        # discrimination: by keeping the sequence numbers of all events
        # which may cause the pointer to enter a window without motion,
        # and assuming that the consequent EnterNotify event is generated
        # without servicing any other requests, we can simply ignore the
        # EnterNotify with the same sequence number as the preceeding
        # modification event. As he points out, only the ordering is
        # guaranteed by the X protocol; a server is in theory free to
        # service other requests before generating any EnterNotify events.
        # Nevertheless, this simple heuristic seems to work flawlessly on
        # all current X servers.
        self.last_modify_serial = None

    @handler(EnterNotifyEvent)
    def handle_enter_notify(self, event):
        self.__log.debug("Window 0x%x entered (%s).",
                         event.event, notify_detail_name(event))
        if (event.mode != NotifyMode.Normal or
            event.detail == NotifyDetail.Inferior or
            sequence_number(event) == self.last_modify_serial or
            self.check_typed_window_event(event.event, LeaveNotifyEvent) or
            self.client_update):
            return
        self.focus(self.get_client(event.event), event.time)

    @handler((UnmapNotifyEvent,
              MapNotifyEvent,
              MapRequestEvent,
              ConfigureNotifyEvent,
              ConfigureRequestEvent,
              GravityNotifyEvent,
              CirculateNotifyEvent,
              CirculateRequestEvent))
    def note_serial(self, event):
        self.last_modify_serial = sequence_number(event)

        # Issue a request so that subsequent events will not have the same
        # sequence number, even if no other requests intervene.
        self.conn.core.NoOperation()

class ClickToFocus(FocusPolicy):
    """Focus ignores the movement of the pointer, and changes only when
    button 1 is pressed in a client window.

    In order to intercept focus clicks, we need to establish a passive grab
    on the pointer button for each client window. However, ICCCM §6.3 states
    that "[c]lients should establish button and key grabs only on windows that
    they own." This policy therefore only establishes grabs on client frames,
    and not on the client windows themselves."""

    __log = logging.getLogger("focus.click")

    def __init__(self, ignore_focus_click=False, **kwargs):
        self.ignore_focus_click = ignore_focus_click
        super(ClickToFocus, self).__init__(**kwargs)

    def manage(self, window, adopted=False):
        client = super(ClickToFocus, self).manage(window, adopted)
        if client:
            self.grab_focus_click(client)
        return client

    def focus(self, client, time, **kwargs):
        if super(ClickToFocus, self).focus(client, time, **kwargs):
            # Once a client is focused, we can release our focus grab.
            # This is purely an optimization: we don't want to be
            # responsible for proxying all button press events to
            # the client. We'll re-establish our grab when the client
            # loses focus.
            self.conn.core.UngrabButton(1, client.frame, ModMask.Any)

            # The above may release passive button grabs established by
            # our global button bindings, so we'll re-establish those here.
            client.establish_grabs(button_bindings=self.button_bindings)
            return True
        else:
            return False

    def unfocus(self, client):
        self.grab_focus_click(client)
        super(ClickToFocus, self).unfocus(client)

    def grab_focus_click(self, client):
        if not client.frame:
            self.__log.warning("Unable to establish grab for focus click.")
            return
        self.conn.core.GrabButton(False, client.frame,
                                  EventMask.ButtonPress,
                                  GrabMode.Sync, GrabMode.Async,
                                  Window._None, Cursor._None,
                                  1, ModMask.Any)

    @handler(ButtonPressEvent)
    def handle_button_press(self, event):
        try:
            client = self.frames[event.event]
        except KeyError:
            return
        self.__log.debug("Button %d press in window 0x%x.",
                         event.detail, event.event)
        if event.state & self.keymap.non_locking_mods:
            self.__log.debug("Unfreezing pointer.")
            self.conn.core.AllowEvents(Allow.AsyncPointer, event.time)
            return
        if self.ignore_focus_click:
            self.__log.debug("Ignoring focus click.")
            self.conn.core.UngrabPointer(event.time)
        else:
            self.__log.debug("Replaying click.")
            self.conn.core.AllowEvents(Allow.ReplayPointer, event.time)
        self.focus(client, event.time)
