# -*- mode: Python; coding: utf-8 -*-

import exceptions

from xcb.xproto import *

from keysym import *

__all__ = ["KeyBindingMap", "ButtonBindingMap", "Bindings"]

def all_combinations(sequences):
    """Given a sequence of sequences, recursively yield all combinations of
    each element of the first sequence with all combinations of the rest of
    the sequences."""
    if sequences:
        for x in sequences[0]:
            for combination in all_combinations(sequences[1:]):
                yield [x] + combination
    else:
        yield []

def ensure_sequence(x):
    return x if isinstance(x, (list, tuple)) else (x,)

def ensure_keysym(x):
    if isinstance(x, int):
        return x
    elif isinstance(x, basestring):
        return string_to_keysym(x)
    else:
        raise exceptions.ValueError("invalid keysym designator '%s'" % x)

class BindingMap(dict):
    """A dictionary of bindings which is parsed at initialization time.

    A binding maps a symbol together with a set of modifiers to some value.
    The former is represented by a designator for a sequence whose last
    element is a designator for a symbol and whose other elements are
    modifier names. The symbol is either a designator for a keysym or a
    logical button number; the ensure_symbol method should accept such a
    designator and return a corresponding symbol."""

    def __init__(self, mapping):
        return super(BindingMap, self).__init__(self.parse_bindings(mapping))

    def parse_bindings(self, bindings={}):
        """Given either a mapping object or a sequence of (key, value)
        pairs, parse the keys as binding specifications and yield new
        (key, value) tuples, where each key is a tuple consisting of a
        (possibly empty) frozen set of modifiers and a symbol."""
        try:
            iterable = bindings.iteritems()
        except AttributeError:
            iterable = iter(bindings)
        for key, value in iterable:
            key = ensure_sequence(key)
            modifiers = frozenset(mod.lower() for mod in key[:-1])
            symbol = self.ensure_symbol(key[-1])
            yield ((modifiers, symbol), value)

class KeyBindingMap(BindingMap):
    def ensure_symbol(self, x):
        return ensure_keysym(x)

class ButtonBindingMap(BindingMap):
    def ensure_symbol(self, x):
        return int(x)

class Bindings(object):
    """Key and button bindings are specified using keysyms, logical button
    numbers, and symbolic modifier names. However, the detail and state
    fields of X KeyPress/Release and ButtonPress/Release events represent
    only the physical state of the corresponding device: keycodes, physical
    buttons, and raw modifier bits.

    This class provides a mapping from the physical to the logical
    representation. Keysyms and logical button numbers are resolved using
    the current keyboard, modifier, and pointer button maps. Modifiers are
    handled by generating all of the possible sets of symbolic modifiers
    that correspond to a given physical state. Together, those two objects
    (the symbol and the modifier set) provide a key for lookup in the
    appropriate bindings table."""

    def __init__(self, key_bindings, button_bindings, keymap, modmap, butmap):
        self.key_bindings = (key_bindings
                             if isinstance(key_bindings, KeyBindingMap)
                             else KeyBindingMap(key_bindings))
        self.button_bindings = (button_bindings
                                if isinstance(button_bindings, ButtonBindingMap)
                                else ButtonBindingMap(button_bindings))
        self.keymap = keymap
        self.modmap = modmap
        self.butmap = butmap
        self.keymap.scry_modifiers(self.modmap)

    def modifiers(self, bit):
        """Yield each of the modifiers bound to the given bucky bit."""
        if bit == KeyButMask.Shift:
            # Shift is special, inasmuch as we allow bindings that explicitly
            # include it as a modifier and ones that implicitly assume it by
            # specifying a symbol which is only selected when it is active
            # (e.g., an uppercase letter or shifted punctuation symbol).
            yield "shift"
            yield None
        if bit == KeyButMask.Control:
            yield "control"
        if bit == self.keymap.meta:
            yield "meta"
        if bit == self.keymap.alt:
            yield "alt"
        if bit == self.keymap.super:
            yield "super"
        if bit == self.keymap.hyper:
            yield "hyper"

    def modsets(self, state):
        """Yield sets of modifier names that are active in the given state."""
        modlists = filter(None,
                          (tuple(self.modifiers(bit))
                           for bit in (1 << i for i in range(8))
                           if state & bit))
        for modlist in all_combinations(modlists):
            yield frozenset(filter(None, modlist))

    def get_binding(self, bindings, symbol, state):
        for modset in self.modsets(state):
            try:
                return bindings[(modset, symbol)]
            except KeyError:
                continue
        raise KeyError(symbol, state)

    def key_binding(self, keycode, state):
        return self.get_binding(self.key_bindings,
                                self.keymap.lookup_key(keycode, state),
                                state)

    def button_binding(self, button, state):
        return self.get_binding(self.button_bindings,
                                self.butmap[button],
                                state)

    def __getitem__(self, event):
        if isinstance(event, (KeyPressEvent, KeyReleaseEvent)):
            return self.key_binding(event.detail, event.state)
        elif isinstance(event, (ButtonPressEvent, ButtonReleaseEvent)):
            return self.button_binding(event.detail, event.state)
        else:
            raise TypeError("unhandled event type")
