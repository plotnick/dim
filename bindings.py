# -*- mode: Python; coding: utf-8 -*-

import exceptions

from xcb.xproto import *

from keysym import *

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

class Bindings(object):
    def __init__(self, key_bindings, button_bindings, keymap, modmap, butmap):
        self.key_bindings = self.parse_bindings(key_bindings, ensure_keysym)
        self.button_bindings = self.parse_bindings(button_bindings, int)
        self.keymap = keymap
        self.modmap = modmap
        self.butmap = butmap

    def parse_bindings(self, raw_bindings, ensure_symbol):
        """A binding maps a symbol together with a set of modifiers to some
        value. The former is represented by a designator for a sequence
        whose last element is a designator for a symbol and whose other
        elements are modifier names. The symbol is either a designator for
        a keysym or a pointer button number, depending on whether the
        binding is a key or pointer binding; the ensure_symbol function
        should accept such a designator and return an appropriate symbol."""
        bindings = {}
        for key, value in raw_bindings.items():
            key = ensure_sequence(key)
            modifiers = frozenset(mod.lower() for mod in key[:-1])
            symbol = ensure_symbol(key[-1])
            bindings[(modifiers, symbol)] = value
        return bindings

    def modifiers(self, bit):
        """Yield each of the modifiers bound to the given bucky bit."""
        if bit == KeyButMask.Shift:
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
        raise KeyError((symbol, state))

    def key_binding(self, keycode, state):
        return self.get_binding(self.key_bindings,
                                self.keymap.lookup_key(keycode, state),
                                state)

    def button_binding(self, button, state):
        return self.get_binding(self.button_bindings,
                                self.butmap[button],
                                state)

    def __getitem__(self, event):
        if isinstance(event, KeyPressEvent):
            return self.key_binding(event.detail, event.state)
        elif isinstance(event, ButtonPressEvent):
            return self.button_binding(event.detail, event.state)
        else:
            raise KeyError("unhandled event type")
