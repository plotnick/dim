# -*- mode: Python; coding: utf-8 -*-

"""Focus cycling."""

import logging

from xcb.xproto import *

from bindings import *
from event import *
from geometry import *
from keysym import *
from properties import WMState
from minibuffer import Minibuffer
from xutil import *

__all__ = ["CycleFocus"]

class CycleFocus(Minibuffer):
    """Cycle through the visible windows and give the user the opportunity
    to choose one as the current keyboard focus.

    The cycling consists of activating the focus decoration on successive
    clients without actually offering the focus. The currently indicated
    client is called the target. During cycling, we decorate the target as
    focused (even though it is not) and display its title in the minibuffer.

    During cycling, the various event handlers may be used to cycle to
    the next/previous target, accept (focus) the current target, or abort
    the whole cycle. The clients which are eligible to appear in the cycle
    and their order are entirely determined the manager's focus list, but
    we skip any clients not in the Normal state. If the cycle is aborted,
    we return focus to whichever client which had the focus before the cycle
    started.

    A few other miscellaneous actions are available as conveniences during
    cycling: the user may raise/lower the target window, or warp the pointer
    into it."""

    override_redirect = True
    event_mask = (EventMask.ButtonPress |
                  EventMask.ButtonRelease |
                  EventMask.KeyPress |
                  EventMask.KeyRelease |
                  EventMask.EnterWindow)

    __log = logging.getLogger("cycle")

    def __new__(cls, focus_list=[], **kwargs):
        # A focus cycle can only exist if there are clients through which to
        # cycle. This assumption, besides seeming logical enough, dramatically
        # simplifies both the code and the interface, since we can then assume
        # that there's always a target client.
        focus_list = [client for client in focus_list
                             if client.wm_state == WMState.NormalState]
        if not focus_list:
            cls.__log.debug("Not starting empty focus cycle.")
            return None
        return super(CycleFocus, cls).__new__(cls, focus_list=focus_list,
                                              **kwargs)

    def __init__(self, event=None, focus_list=[], direction=+1,
                 button_bindings={}, key_bindings={}, aliases={},
                 select=lambda client: None, abort=lambda: None,
                 **kwargs):
        super(CycleFocus, self).__init__(**kwargs)

        if isinstance(event, (KeyPressEvent, ButtonPressEvent)):
            modifiers = next(self.manager.key_bindings.modsets(event.state))
            key_bindings = ModalKeyBindingMap(modifiers, key_bindings,
                                              aliases=aliases)
            button_bindings = ModalButtonBindingMap(modifiers, button_bindings)
            self.key_bindings = KeyBindings(key_bindings,
                                            self.manager.keymap,
                                            self.manager.modmap)
            self.button_bindings = ButtonBindings(button_bindings,
                                                  self.manager.keymap,
                                                  self.manager.modmap)
        else:
            self.__log.error("Must start with a key or button press.")
            return

        # Cycle-end callbacks.
        self.select = select
        self.abort = abort

        # Initialize & start the cycle.
        self.focus_list = tuple(focus_list)
        self.initial_focus = self.focus_list[0]
        self.target_index = 0 # into focus list
        self.map(event.time)
        self.cycle_focus(direction)

    @property
    def target(self):
        """Return the currently indicated client in this focus cycle.
        This is not necessarily the currently focused client."""
        return self.focus_list[self.target_index]

    def cycle_focus(self, incr):
        self.target.decorator.unfocus()
        n = len(self.focus_list)
        for i in range(n):
            self.target_index = ((self.target_index + incr) % n)
            if self.target.wm_state == WMState.NormalState:
                try:
                    self.target.decorator.focus()
                except BadWindow:
                    continue
                self.icon = self.target
                self.buffer[:] = unicode(self.target.title)
                self.draw()
                return True

    def end_focus_cycle(self, client, time):
        # We must send the ensure-focus message first so that we can
        # correctly ignore the FocusIn and FocusOut events generated
        # due to the ungrabbing.
        self.manager.ensure_focus(client)
        self.unmap(time)
        self.destroy()

    def cycle_focus_next(self, event=None):
        self.cycle_focus(+1)

    def cycle_focus_prev(self, event=None):
        self.cycle_focus(-1)

    def accept_focus(self, event):
        self.__log.debug("Client 0x%x accepted.", self.target.window)
        self.end_focus_cycle(self.target, event.time)
        self.select(self.target)

    def abort_focus_cycle(self, event):
        self.__log.debug("Focus cycle aborted.")
        if self.target != self.initial_focus:
            self.target.decorator.unfocus()
        self.end_focus_cycle(self.initial_focus, event.time)
        self.abort()

    def raise_target_window(self, event=None):
        self.target.configure(sibling=self.window, stack_mode=StackMode.Below)

    def lower_target_window(self, event=None):
        self.target.configure(stack_mode=StackMode.BottomIf)

    def warp_to_target(self, event=None):
        x, y = self.target.geometry.size() // 2
        self.conn.core.WarpPointer(Window._None, self.target.window,
                                   0, 0, 0, 0, int16(x), int16(y))

    def map(self, time=Time.CurrentTime):
        super(CycleFocus, self).map(time)
        self.conn.core.GrabPointer(True, self.window,
                                   (EventMask.ButtonPress |
                                    EventMask.ButtonRelease),
                                   GrabMode.Async,
                                   GrabMode.Async,
                                   Window._None, 0, time)

    def unmap(self, time=Time.CurrentTime):
        self.conn.core.UngrabPointer(time)
        super(CycleFocus, self).unmap()

    @handler((KeyPressEvent, KeyReleaseEvent))
    def handle_key_event(self, event):
        try:
            action = self.key_bindings[event]
        except KeyError:
            raise UnhandledEvent(event)
        action(self, event)
        raise StopPropagation(event)

    @handler((ButtonPressEvent, ButtonReleaseEvent))
    def handle_button_event(self, event):
        try:
            action = self.button_bindings[event]
        except KeyError:
            raise UnhandledEvent(event)
        action(self, event)
        raise StopPropagation(event)
