# -*- mode: Python; coding: utf-8 -*-

from abc import abstractmethod, ABCMeta
from array import array
from collections import Mapping as AbstractMapping # avoid conflict with xcb
from operator import or_

from xcb.xproto import *

from keysym import *

__all__ = ["KeyboardMap", "ModifierMap", "PointerMap", "KeymapError"]

class KeymapError(Exception):
    pass

class InputDeviceMapping(AbstractMapping):
    """Abstract base class for keyboard, modifier, and pointer mappings."""

    def __init__(self, conn, cookie=None, *args):
        self.conn = conn
        if cookie:
            self.update(cookie, *args)
        else:
            self.refresh(*args)

    @abstractmethod
    def refresh(self):
        """Request an updated mapping from the server."""
        # Subclasses should generate an appropriate request and pass the
        # cookie to update.
        pass

    @abstractmethod
    def update(self, cookie):
        """Update the cached mapping using the given request cookie."""
        pass

class KeyboardMap(InputDeviceMapping):
    """A map from keycodes to keysyms (and vice-versa)."""

    def __init__(self, conn, cookie=None, modmap=None):
        setup = conn.get_setup()
        self.min_keycode = setup.min_keycode
        self.max_keycode = setup.max_keycode
        self.keycodes = {} # frozen sets, indexed by keysym
        super(KeyboardMap, self).__init__(conn, cookie,
                                          self.min_keycode, len(self))

        if modmap:
            self.scry_modifiers(modmap)
        else:
            self.clear_modifiers()

    def refresh(self, first_keycode=None, count=None):
        """Request an updated keyboard mapping for the specified keycodes."""
        self.keycodes = {} # flush the cache
        if first_keycode is None:
            first_keycode = self.min_keycode
        if count is None:
            count = len(self)
        cookie = self.conn.core.GetKeyboardMapping(first_keycode, count)
        self.update(cookie, first_keycode, count)

    def update(self, cookie, first_keycode, count):
        """Update the stored keyboard mapping for the count keycodes starting
        at first_keycode."""
        def check_reply(reply, count, n=None):
            if n is None:
                n = reply.keysyms_per_keycode
            elif reply.keysyms_per_keycode != n:
                raise KeymapError("number of keysyms per keycode changed "
                                  "(was %d, reply has %d)" %
                                  (n, reply.keysyms_per_keycode))
            if len(reply.keysyms) != count * n:
                raise KeymapError("unexpected number of keysyms in reply "
                                  "(expected %d, got %d)" %
                                  (count * n, len(reply.keysyms)))

        reply = cookie.reply()
        if first_keycode == self.min_keycode and count == len(self):
            # Replace the entire mapping.
            check_reply(reply, count)
            self.keysyms_per_keycode = reply.keysyms_per_keycode
            self.keysyms = array("I", reply.keysyms)
        else:
            # Only replace the keysym range that was requested.
            check_reply(reply, count, self.keysyms_per_keycode)
            n = self.keysyms_per_keycode
            i = (first_keycode - self.min_keycode) * n
            j = i + (count * n)
            self.keysyms[i:j] = array("I", reply.keysyms)

    @staticmethod
    def effective_index(keysyms, index):
        """From the X11 protocol specification (Chapter 5, ¶3):

        A list of KEYSYMs is associated with each KEYCODE. The list is intended
        to convey the set of symbols on the corresponding key. If the list
        (ignoring trailing NoSymbol entries) is a single KEYSYM "K", then the
        list is treated as if it were the list "K NoSymbol K NoSymbol". If the
        list (ignoring trailing NoSymbol entries) is a pair of KEYSYMs "K1 K2",
        then the list is treated as if it were the list "K1 K2 K1 K2". If the
        list (ignoring trailing NoSymbol entries) is a triple of KEYSYMs
        "K1 K2 K3", then the list is treated as if it were the list
        "K1 K2 K3 NoSymbol". When an explicit "void" element is desired in
        the list, the value VoidSymbol can be used."""
        if 1 < index < 4:
            # This subtle but efficient logic was blatantly stolen from Xlib's
            # KeyCodetoKeySym function.
            n = len(keysyms)
            while n > 2 and keysyms[n - 1] == NoSymbol:
                n -= 1
            if n < 3:
                index -= 2
        return index

    @staticmethod
    def effective_keysym(keysyms, index):
        """From the X11 protocol specification (Chapter 5, ¶4):

        The first four elements of the list are split into two groups of
        KEYSYMs. Group 1 contains the first and second KEYSYMs; Group 2
        contains the third and fourth KEYSYMs. Within each group, if the
        second element of the group is NoSymbol, then the group should be
        treated as if the second element were the same as the first element,
        except when the first element is an alphabetic KEYSYM "K" for which
        both lowercase and uppercase forms are defined. In that case, the
        group should be treated as if the first element were the lowercase
        form of "K" and the second element were the uppercase form of "K"."""
        if index < 4:
            index = KeyboardMap.effective_index(keysyms, index)
            if len(keysyms) == 1 or keysyms[index | 1] == NoSymbol:
                keysym = keysyms[index & ~1]
                return upper(keysym) if index & 1 else lower(keysym)
        return keysyms[index]

    @staticmethod
    def lookup_effective_keysym(keysyms, modifiers, group, num_lock, lock):
        """From the X11 protocol specification (Chapter 5, ¶8):

        Within a group, the choice of KEYSYM is determined by applying the
        first rule that is satisfied from the following list:

      • The numlock modifier is on and the second KEYSYM is a keypad KEYSYM.
        In this case, if the Shift modifier is on, or if the Lock modifier
        is on and is interpreted as ShiftLock, then the first KEYSYM is used;
        otherwise, the second KEYSYM is used.

      • The Shift and Lock modifiers are both off. In this case, the first
        KEYSYM is used.

      • The Shift modifier is off, and the Lock modifier is on and is
        interpreted as CapsLock. In this case, the first KEYSYM is used,
        but if that KEYSYM is lowercase alphabetic, then the corresponding
        uppercase KEYSYM is used instead.

      • The Shift modifier is on, and the Lock modifier is on and is
        interpreted as CapsLock. In this case, the second KEYSYM is used,
        but if that KEYSYM is lowercase alphabetic, then the corresponding
        uppercase KEYSYM is used instead.

      • The Shift modifier is on, or the Lock modifier is on and is interpreted
        as ShiftLock, or both. In this case, the second KEYSYM is used."""
        index = 2 if modifiers & group else 0 # select group
        num_lock_on = modifiers & num_lock
        caps_lock_on = modifiers & ModMask.Lock and lock == XK_Caps_Lock
        shift_lock_on = modifiers & ModMask.Lock and lock == XK_Shift_Lock
        shift = modifiers & ModMask.Shift or shift_lock_on

        if (num_lock_on and
            is_keypad_key(KeyboardMap.effective_keysym(keysyms, index | 1))):
            return KeyboardMap.effective_keysym(keysyms, index | (not shift))
        elif caps_lock_on:
            return upper(KeyboardMap.effective_keysym(keysyms, index | shift))
        else:
            return KeyboardMap.effective_keysym(keysyms, index | shift)

    def lookup_key(self, keycode, modifiers):
        """Given a keycode and modifier mask (e.g., from the detail and state
        fields of a KeyPress/KeyRelease event), return the effective keysym."""
        return self.lookup_effective_keysym(self[keycode],
                                            modifiers,
                                            self.group,
                                            self.num_lock,
                                            self.lock)

    def __getitem__(self, key):
        """Retrieve the symbol associated with a key.

        If the key is a raw keycode, the entire list of keysyms currently
        bound to that keycode is returned. If the key is given as a tuple
        of the form (keycode, index), then the effective keysym at the
        index'th position is returned."""
        if isinstance(key, tuple):
            keycode, index = key
        else:
            keycode, index = key, None

        n = self.keysyms_per_keycode
        i = (keycode - self.min_keycode) * n
        j = i + n
        return (self.keysyms[i:j] if index is None else
                self.effective_keysym(self.keysyms[i:j], index))

    def __iter__(self):
        for keycode in range(self.min_keycode, self.max_keycode):
            yield keycode

    def __len__(self):
        return (self.max_keycode - self.min_keycode) + 1

    def keysym_to_keycodes(self, keysym):
        """Return the set of keycodes that generate the given symbol.
        These sets are fairly expensive to compute, so we cache them."""
        try:
            return self.keycodes[keysym]
        except KeyError:
            keycodes = frozenset(i
                                 for j in range(self.keysyms_per_keycode)
                                 for i in range(self.min_keycode,
                                                self.max_keycode + 1)
                                 if self[(i, j)] == keysym)
            self.keycodes[keysym] = keycodes
            return keycodes

    def keysym_to_keycode(self, keysym):
        """Return an arbitrary keycode that generates the given symbol,
        or None if there is no such keycode."""
        keycodes = self.keysym_to_keycodes(keysym)
        if keycodes:
            return tuple(keycodes)[0]
        else:
            return None

    def clear_modifiers(self):
        self.lock = NoSymbol # keysym, not bucky bit
        self.group = 0
        self.num_lock = 0
        self.scroll_lock = 0
        self.alt = 0
        self.meta = 0
        self.super = 0
        self.hyper = 0
        self.locking_modifiers = []

    def scry_modifiers(self, modmap):
        """Grovel through the modifier map and assign meanings to modifiers.

        Assigns to the "lock" attribute one of the keysyms Caps_Lock or
        Shift_Lock, depending on which keysym is currently attached to a
        keycode that is in turn attached to the Lock modifier. If no such
        keys are attached, lock will be NoSymbol.

        Also assigns modifier bits to each of the attributes "group",
        "num_lock", "scroll_lock", "alt", "meta", "super", and "hyper"
        if there is an appropriate keysym attached to a keycode that is
        attached to any of the modifiers Mod1 through Mod5."""
        self.clear_modifiers()

        # Find any appropriate keysym currently acting as the Lock modifier.
        for keycode in modmap[MapIndex.Lock]:
            keysyms = self[keycode]
            if XK_Caps_Lock in keysyms or XK_ISO_Lock in keysyms:
                self.lock = XK_Caps_Lock
                break
            elif XK_Shift_Lock in keysyms:
                self.lock = XK_Shift_Lock
                break

        # Now find any bucky bits acting as Group, Num Lock, Scroll Lock,
        # Alt, Meta, Super, and Hyper modifiers. Only the first two are
        # required for proper keycode → keysym translation; the others
        # are provided purely as a convenience.
        for mod in range(MapIndex._1, MapIndex._5 + 1):
            for keycode in modmap[mod]:
                keysyms = self[keycode]
                self.group |= (XK_Mode_switch in keysyms) << mod
                self.num_lock |= (XK_Num_Lock in keysyms) << mod
                self.scroll_lock |= (XK_Scroll_Lock in keysyms) << mod
                self.alt |= (XK_Alt_L in keysyms or
                             XK_Alt_R in keysyms) << mod
                self.meta |= (XK_Meta_L in keysyms or
                              XK_Meta_R in keysyms) << mod
                self.super |= (XK_Super_L in keysyms or
                               XK_Super_R in keysyms) << mod
                self.hyper |= (XK_Hyper_L in keysyms or
                               XK_Hyper_R in keysyms) << mod

        # Various parties (especially those establishing passive grabs)
        # may be interested in which bucky bits correspond to locks, and
        # which do not.
        self.locking_mods = filter(bool,
                                   [ModMask.Lock,
                                    self.num_lock,
                                    self.scroll_lock])
        self.non_locking_mods = 0xff & ~reduce(or_, self.locking_mods)

class ModifierMap(InputDeviceMapping):
    def refresh(self):
        """Request an updated modifier mapping from the server."""
        self.update(self.conn.core.GetModifierMapping())

    def update(self, cookie):
        """Update the stored modifier mapping."""
        reply = cookie.reply()
        n = self.keycodes_per_modifier = reply.keycodes_per_modifier
        self.modmap = [[reply.keycodes[(i * n) + j] for j in range(n)]
                       for i in range(8)]

    def __getitem__(self, modifier):
        """Return the list of keycodes associated with the given modifier."""
        return self.modmap[modifier]

    def __iter__(self):
        for i in range(8):
            yield i

    def __len__(self):
        return 8

class PointerMap(InputDeviceMapping):
    def refresh(self):
        """Request an updated pointer mapping from the server."""
        self.update(self.conn.core.GetPointerMapping())

    def update(self, cookie):
        """Update the stored pointer mapping."""
        reply = cookie.reply()
        self.map = (None,) + tuple(reply.map)

    def __getitem__(self, button):
        if button == 0:
            raise KeyError("pointer buttons are 1-indexed")
        return self.map[button]

    def __iter__(self):
        return iter(self.map[1:])

    def __len__(self):
        return len(self.map) - 1
