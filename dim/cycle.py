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

__all__ = ["CycleFocus"]

class ModalKeyBindingMap(KeyBindingMap):
    """A modal key binding map is a specialized mapping that automatically
    adds a specific set of modifiers to each specified key, and which
    provides a symbol designator (None in this class) for the release of
    the last of those modifers."""

    def __init__(self, modifiers, *args, **kwargs):
        self.modifiers = modifiers
        super(ModalKeyBindingMap, self).__init__(*args, **kwargs)

    def parse_bindings(self, bindings,
                       mod_keys={"control": (XK_Control_L, XK_Control_R),
                                 "alt": (XK_Alt_L, XK_Alt_R),
                                 "meta": (XK_Meta_L, XK_Meta_R),
                                 "super": (XK_Super_L, XK_Super_R),
                                 "hyper": (XK_Hyper_L, XK_Hyper_R)}):
        for key, value in bindings.iteritems():
            value = self.normalize_value(value)
            if key is None:
                # None designates the release of the last held modifier.
                for mod in self.modifiers:
                    mods = frozenset([mod])
                    for keysym in mod_keys.get(mod, ()):
                        yield ((mods, keysym, False), value)
            else:
                # Keys here are just symbol designators.
                symbol = self.ensure_symbol(key)
                yield ((self.modifiers, abs(symbol), symbol > 0), value)

class CycleFocus(Minibuffer):
    """Cycle through the visible windows and give the user the opportunity
    to choose one as the current keyboard focus.

    The cycling consists of activating the focus decoration on successive
    clients without actually offering the focus. The currently indicated
    client is called the target. If a target is selected, we offer the
    focus to that client. If the cycle is aborted, we return focus to
    whichever client which had the focus before the cycle started."""

    override_redirect = True
    event_mask = (EventMask.ButtonPress |
                  EventMask.ButtonRelease |
                  EventMask.KeyPress |
                  EventMask.KeyRelease)

    __log = logging.getLogger("cycle")

    def __init__(self, event=None, focus_list=[], forward=True, key_bindings={},
                 **kwargs):
        super(CycleFocus, self).__init__(**kwargs)

        if isinstance(event, KeyPressEvent):
            modifiers = next(self.manager.key_bindings.modsets(event.state))
            binding_map = ModalKeyBindingMap(modifiers, key_bindings)
            self.key_bindings = KeyBindings(binding_map,
                                            self.manager.keymap,
                                            self.manager.modmap)
            self.key_bindings.establish_grabs(self.window)
        else:
            self.__log.error("Focus cycle must be initiated by a key-press.")
            return

        self.focus_list = tuple(focus_list)
        self.initial_focus = self.focus_list[0]
        self.target_index = 0
        self.map(event.time)
        self.cycle_focus(event, 1 if forward else -1)

    @property
    def target(self):
        """Return the currently indicated client in this focus cycle.
        This is not necessarily the currently focused client."""
        return self.focus_list[self.target_index]

    def cycle_focus_next(self, event):
        self.cycle_focus(event, 1)

    def cycle_focus_prev(self, event):
        self.cycle_focus(event, -1)

    def cycle_focus(self, event, incr):
        self.target.decorator.unfocus()
        while True:
            self.target_index = ((self.target_index + incr) %
                                 len(self.focus_list))
            if self.target.wm_state == WMState.NormalState:
                try:
                    self.target.decorator.focus()
                except BadWindow:
                    continue
                self.buffer[:] = unicode(self.target.net_wm_name or
                                         self.target.wm_name)
                self.draw()
                return True

    def end_focus_cycle(self, event, client):
        self.unmap(event.time)
        self.destroy()
        self.manager.ensure_focus(client)

    def accept_focus(self, event):
        self.__log.debug("Client 0x%x selected.", self.target.window)
        self.end_focus_cycle(event, self.target)

    def abort_focus_cycle(self, event):
        self.__log.debug("Focus cycle aborted.")
        if self.target != self.initial_focus:
            self.target.decorator.unfocus()
        self.end_focus_cycle(event, self.initial_focus)

    def raise_target_window(self, event):
        self.target.configure(sibling=self.window, stack_mode=StackMode.Below)

    def lower_target_window(self, event):
        self.target.configure(stack_mode=StackMode.BottomIf)

    @handler((KeyPressEvent, KeyReleaseEvent))
    def handle_key_event(self, event):
        try:
            action = self.key_bindings[event]
        except KeyError:
            raise UnhandledEvent(event)
        action(self, event)
        raise StopPropagation(event)
