# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple
from operator import or_
import exceptions

from xcb.xproto import *

from keysym import *
from xutil import event_window

__all__ = ["keypad_aliases", "event_mask",
           "BindingMap", "KeyBindingMap", "ButtonBindingMap",
           "ModalKeyBindingMap", "ModalButtonBindingMap",
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

class InvalidSymbol(Exception):
    "Invalid key symbol, alias, or desigantor."
    pass

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
        raise InvalidSymbol("invalid keysym designator %r" % (x,))

def event_mask(mask):
    """A factory for a decorator that sets the "event_mask" attribute on a
    function for use as a bound button action."""
    def set_event_mask(function):
        function.event_mask = mask
        return function
    return set_event_mask

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
        self.aliases = (dict(parent.aliases)
                        if isinstance(parent, BindingMap)
                        else {})
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
            value = self.normalize_value(value)
            modifiers = frozenset(mod.lower() for mod in key[:-1])
            try:
                symbol = self.ensure_symbol(key[-1])
            except InvalidSymbol:
                continue
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


class ModalBindingMap(BindingMap):
    """A modal binding map is a specialized mapping that automatically
    adds a given set of modifiers to each symbol, and which provides
    a symbol designator (None) for the release of the last of them.
    This is (by design, of course) exactly what is needed for "Alt+Tab"-style
    focus cycling."""

    def __init__(self, modifiers, *args, **kwargs):
        self.modifiers = modifiers
        super(ModalBindingMap, self).__init__(*args, **kwargs)

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
            elif isinstance(key, tuple):
                # Add the given modifiers to the specified set.
                mods = self.modifiers | frozenset(key[:-1])
                symbol = self.ensure_symbol(key[-1])
                yield ((mods, abs(symbol), symbol > 0), value)
            else:
                # Keys here are just symbol designators.
                symbol = self.ensure_symbol(key)
                yield ((self.modifiers, abs(symbol), symbol > 0), value)

class ModalKeyBindingMap(ModalBindingMap, KeyBindingMap):
    pass

class ModalButtonBindingMap(ModalBindingMap, ButtonBindingMap):
    pass

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
        self.conn = self.keymap.conn

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

    def locking_modifier_combinations(self):
        """Yield combinations of bound locking modifiers."""
        for mods in all_combinations([[0, lock]
                                      for lock in self.keymap.locking_mods]):
            yield reduce(or_, mods)

    def establish_grabs(self, window):
        """Establish passive grabs for each binding."""
        pass

class KeyBindings(Bindings):
    """Support lookup of key bindings via KeyPress & KeyRelease events.

    We also support the binding of key sequences via submaps, wherein
    prefix keys are bound to (designators for) keymaps. We actively
    grab the keyboard on recognizing a prefix key, so the bindings in
    the submap need not be passively grabbed. This makes it convenient
    to use unmodified symbols in a submap without worrying about
    interfering with client applications."""

    # When we recognize a prefix key, we'll push the old binding map onto
    # a stack. But we'll also push the symbol that corresponds to that prefix
    # key so that we can correctly ignore the corresponding release event.
    BindingFrame = namedtuple("BindingFrame", "bindings, symbol")

    def __init__(self, bindings, keymap, modmap):
        bindings = (bindings if isinstance(bindings, KeyBindingMap)
                             else KeyBindingMap(bindings))
        super(KeyBindings, self).__init__(bindings, keymap, modmap)
        self.binding_stack = []
        self.grabs = {}

    def push(self, bindings, symbol, window, time):
        """Push the current bindings onto the stack and grab the keyboard."""
        self.binding_stack.append(self.BindingFrame(self.bindings, symbol))
        self.bindings = bindings
        self.conn.core.GrabKeyboard(False, window, time,
                                    GrabMode.Sync, # queue pointer events
                                    GrabMode.Async)

    def unwind(self, time):
        """Unwind the binding stack and release the grab."""
        self.bindings = self.binding_stack[0].bindings
        self.binding_stack = []
        self.conn.core.UngrabKeyboard(time)

    def __getitem__(self, event):
        """Look up and return the binding designated by the given event."""
        if isinstance(event, (KeyPressEvent, KeyReleaseEvent)):
            press = True if isinstance(event, KeyPressEvent) else False
            state = event.state
            symbol = self.keymap.lookup_key(event.detail, state)
            time = event.time
            key = (symbol, state, press)
        else:
            key = event

        # In a submap, ignore modifiers and prefix key release.
        if (self.binding_stack and
            (is_modifier_key(symbol) or
             (not press and symbol == self.binding_stack[-1].symbol))):
            raise KeyError(key)

        try:
            binding = super(KeyBindings, self).__getitem__(key)
        except KeyError:
            # No binding found: maybe unwind the stack and re-raise.
            if self.binding_stack:
                self.unwind(time)
            raise
        if isinstance(binding, dict):
            # Submap designator: instantiate a submap.
            binding = self.__class__(binding, self.keymap, self.modmap)
        if isinstance(binding, KeyBindings):
            # Prefix binding: push the submap & ignore the prefix key.
            self.push(binding.bindings, symbol, event_window(event), time)
            raise KeyError(key)
        if binding and self.binding_stack:
            # Found a complete binding: unwind the stack.
            self.unwind(time)
        return binding

    def compute_grabs(self):
        """Yield (modifiers, keycode) grab pairs for the current bindings."""
        # We establish grabs only for top-level bindings. If an action in
        # a submap launches a new client, we don't want the new client to
        # establish grabs for the bindings in the submap.
        bindings = (self.bindings if not self.binding_stack
                                  else self.binding_stack[0].bindings)
        inverse_aliases = dict(zip(bindings.aliases.values(),
                                   bindings.aliases.keys()))
        for modset, symbol, press in bindings.keys():
            modifiers = self.bucky_bits(modset)
            for keycode in self.keymap.keysym_to_keycodes(symbol):
                yield (modifiers, keycode)
            alias = inverse_aliases.get(symbol, None)
            if alias:
                for keycode in self.keymap.keysym_to_keycodes(alias):
                    yield (modifiers, keycode)

    def update_grabs(self, window, grabs):
        """Update grabs that have changed since the previous update."""
        prev_grabs = self.grabs.get(window) or frozenset()
        self.grabs[window] = grabs # save for next update
        for mods, key in prev_grabs - grabs:
            for locks in self.locking_modifier_combinations():
                self.conn.core.UngrabKey(key, window, locks | mods)
        for mods, key in grabs - prev_grabs:
            for locks in self.locking_modifier_combinations():
                self.conn.core.GrabKey(True, window, locks | mods, key,
                                       GrabMode.Async, GrabMode.Async)

    def establish_grabs(self, window):
        self.update_grabs(window, frozenset(self.compute_grabs()))

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

    def establish_grabs(self, window):
        def grabs():
            for key, value in self.bindings.items():
                modset, button, press = key
                mask, action = value
                modifiers = self.bucky_bits(modset)
                yield (modifiers, button, mask)
        self.conn.core.UngrabButton(ButtonIndex.Any, window, ModMask.Any)
        for modifiers, button, mask in grabs():
            for locks in self.locking_modifier_combinations():
                self.conn.core.GrabButton(True, window, mask,
                                          GrabMode.Async, GrabMode.Async,
                                          Window._None, Cursor._None,
                                          button, locks | modifiers)
