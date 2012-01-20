# -*- mode: Python; coding: utf-8 -*-

import exceptions

from xcb.xproto import *

from keysym import *

__all__ = ["keypad_aliases",
           "KeyBindingMap", "ButtonBindingMap", "event_mask",
           "KeyBindings", "ButtonBindings"]

keypad_aliases = {XK_KP_Space: XK_space,
                  XK_KP_Tab: XK_Tab,
                  XK_KP_Enter: XK_Return,
                  XK_KP_Home: XK_Home,
                  XK_KP_Left: XK_Left,
                  XK_KP_Up: XK_Up,
                  XK_KP_Right: XK_Right,
                  XK_KP_Down: XK_Down,
                  XK_KP_Prior: XK_Prior,
                  XK_KP_Page_Up: XK_Page_Up,
                  XK_KP_Next: XK_Next,
                  XK_KP_Page_Down: XK_Page_Down,
                  XK_KP_End: XK_End,
                  XK_KP_Begin: XK_Begin,
                  XK_KP_Insert: XK_Insert,
                  XK_KP_Delete: XK_Delete,
                  XK_KP_Equal: XK_equal,
                  XK_KP_Multiply: XK_asterisk,
                  XK_KP_Add: XK_plus,
                  XK_KP_Separator: XK_comma,
                  XK_KP_Subtract: XK_minus,
                  XK_KP_Decimal: XK_period,
                  XK_KP_Divide: XK_slash,
                  XK_KP_0: XK_0,
                  XK_KP_1: XK_1,
                  XK_KP_2: XK_2,
                  XK_KP_3: XK_3,
                  XK_KP_4: XK_4,
                  XK_KP_5: XK_5,
                  XK_KP_6: XK_6,
                  XK_KP_7: XK_7,
                  XK_KP_8: XK_8,
                  XK_KP_9: XK_9}

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

    A binding maps keys of the form (modset, symbol, press) to opaque
    values. Such keys are designated by sequences whose last element is a
    designator for a symbol and whose other elements are modifier names.
    Symbols are either keysyms or logical button numbers. If the symbol
    is positive, the binding is for a press event; if negative, for the
    release of the symbol's absolute value.

    A simple (single-inheritance) hierarchy of bindings is supported. If a
    binding is not found in a binding map, it will be recursively looked up
    in the parent map if there is one.

    Finally, symbols may be aliased to other symbols. This is convenient
    for, e.g., symbols on the numeric keypad (see keypad_aliases, above).
    Aliases are also inherited from the parent map, if there is one, with
    the child's aliases overriding those of the parent."""

    def __init__(self, mapping, parent=None, aliases={}):
        super(BindingMap, self).__init__(self.parse_bindings(mapping))
        self.parent = parent
        self.aliases = dict(parent.aliases if parent else [])
        self.aliases.update(aliases)

    def parse_bindings(self, bindings):
        """Given either a mapping object or a sequence of (key, value)
        pairs, parse the keys as binding specifications and yield new
        (key, value) tuples, where each key is a tuple consisting of a
        (possibly empty) frozen set of modifiers, a symbol, and a boolean
        indicating whether the binding is for a press (true) or a release
        (false)."""
        try:
            iterable = bindings.iteritems()
        except AttributeError:
            iterable = iter(bindings)
        for key, value in iterable:
            key = ensure_sequence(key)
            modifiers = frozenset(mod.lower() for mod in key[:-1])
            symbol = self.ensure_symbol(key[-1])
            yield ((modifiers, abs(symbol), symbol > 0),
                   self.normalize_value(value))

    def ensure_symbol(self, x):
        """Given a symbol designator, return the designated symbol."""
        return x

    def normalize_value(self, value):
        """Perform any necessary value canonicalization."""
        return value

class KeyBindingMap(BindingMap):
    def ensure_symbol(self, x):
        return ensure_keysym(x)

class ButtonBindingMap(BindingMap):
    def ensure_symbol(self, x):
        return int(x)

    def normalize_value(self, value):
        """Values for button bindings are designators for tuples of the form
        (event-mask, action). If a non-tuple is provided, then we'll look for
        an "event_mask" attribute on the value; if that fails, the event-mask
        is assumed to be just ButtonPress."""
        if isinstance(value, tuple):
            return value
        elif hasattr(value, "event_mask"):
            return (value.event_mask, value)
        else:
            return (EventMask.ButtonPress, value)

def event_mask(mask):
    """A factory for a decorator that sets the "event_mask" attribute on a
    function for use as a bound button action."""
    def set_event_mask(function):
        function.event_mask = mask
        return function
    return set_event_mask

class Bindings(object):
    """We'd like key and button bindings to be specified using keysyms
    and symbolic modifier names. However, the detail and state fields of
    X KeyPress/Release and ButtonPress/Release events represent only the
    physical state of the corresponding device: keycodes and modifier bits.

    This class provides a mapping from the physical to the logical
    representation. Keysyms are resolved using the current keyboard and
    modifier maps. Modifiers are handled by generating all of the possible
    sets of symbolic modifiers that correspond to a given physical state.
    Those two objects (the symbol and the modifier set), together with a
    boolean representing whether a given event is a press or release
    (press=True, release=False) provide a key for lookup in the actual
    bindings map."""

    def __init__(self, bindings, keymap, modmap):
        self.bindings = bindings
        self.keymap = keymap
        self.modmap = modmap
        self.keymap.scry_modifiers(self.modmap)

    def modifiers(self, bit):
        """Yield the names of each of the modifiers currently bound to the
        given bucky bit."""
        if bit == KeyButMask.Shift:
            # Shift is special, inasmuch as we allow bindings that explicitly
            # include it as a modifier and ones that implicitly assume it by
            # specifying a symbol which is only selected when it is active
            # (e.g., an uppercase letter or shifted punctuation symbol).
            yield "shift"
            yield None
        if bit == KeyButMask.Control:
            yield "control"
        if bit == self.keymap.alt:
            yield "alt"
        if bit == self.keymap.meta:
            yield "meta"
        if bit == self.keymap.super:
            yield "super"
        if bit == self.keymap.hyper:
            yield "hyper"

    def bucky_bits(self, modset):
        """Return a bitmask that corresponds to the given modset."""
        return ((KeyButMask.Shift if "shift" in modset else 0) |
                (KeyButMask.Control if "control" in modset else 0) |
                (self.keymap.alt if "alt" in modset else 0) |
                (self.keymap.meta if "meta" in modset else 0) |
                (self.keymap.super if "super" in modset else 0) |
                (self.keymap.hyper if "hyper" in modset else 0))

    def modsets(self, state):
        """Yield sets of modifier names that are logically down in the given
        state."""
        modlists = filter(None,
                          (tuple(self.modifiers(bit))
                           for bit in (1 << i for i in range(8))
                           if state & bit))
        for modlist in all_combinations(modlists):
            yield frozenset(filter(None, modlist))

    def __getitem__(self, key):
        """Return the binding associated with the key (symbol, state, press)."""
        symbol, state, press = key
        symbol = self.bindings.aliases.get(symbol, symbol)
        bindings = self.bindings
        while bindings:
            for modset in self.modsets(state):
                try:
                    return bindings[(modset, symbol, press)]
                except KeyError:
                    continue
            bindings = bindings.parent
        raise KeyError(symbol, state, press)

    def grabs(self):
        """Yield tuples of values suitable for establishing passive grabs."""
        pass

class KeyBindings(Bindings):
    def __init__(self, bindings, keymap, modmap):
        bindings = (bindings
                    if isinstance(bindings, KeyBindingMap)
                    else KeyBindingMap(bindings))
        super(KeyBindings, self).__init__(bindings, keymap, modmap)

    def __getitem__(self, key):
        if isinstance(key, KeyPressEvent):
            key = (key.detail, key.state, True)
        elif isinstance(key, KeyReleaseEvent):
            key = (key.detail, key.state, False)
        keycode, state, press = key
        keysym = self.keymap.lookup_key(keycode, state)
        return super(KeyBindings, self).__getitem__((keysym, state, press))

    def grabs(self):
        """Yield tuples of the form (modifiers, keycode) suitable for
        establishing passive key grabs for all of the current key bindings."""
        for modset, symbol, press in self.bindings.keys():
            modifiers = self.bucky_bits(modset)
            for keycode in self.keymap.keysym_to_keycodes(symbol):
                yield (modifiers, keycode)

class ButtonBindings(Bindings):
    def __init__(self, bindings, keymap, modmap):
        bindings = (bindings
                    if isinstance(bindings, ButtonBindingMap)
                    else ButtonBindingMap(bindings))
        super(ButtonBindings, self).__init__(bindings, keymap, modmap)

    def __getitem__(self, key):
        if isinstance(key, ButtonPressEvent):
            key = (key.detail, key.state, True)
        elif isinstance(key, ButtonReleaseEvent):
            key = (key.detail, key.state, False)
        button, state, press = key
        value = super(ButtonBindings, self).__getitem__((button, state, press))
        # Return only the action, not the event mask.
        return value[1]

    def grabs(self):
        """Yield tuples of the form (modifiers, button, event-mask) suitable
        for establishing passive button grabs for all of the current button
        bindings."""
        for key, value in self.bindings.items():
            modset, button, press = key
            mask, action = value
            modifiers = self.bucky_bits(modset)
            yield (modifiers, button, mask)
