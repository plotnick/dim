# -*- mode: Python; coding: utf-8 -*-

from abc import abstractmethod, ABCMeta
from array import array
from collections import Mapping as AbstractMapping # avoid conflict with xcb

from xcb.xproto import *

from keysym import NoSymbol, upper, lower

__all__ = ["KeyboardMap", "ModifierMap", "PointerMap", "KeymapError"]

def effective_index(keysyms, index):
    """From the X11 protocol specification (Chapter 5, ¶3):

    A list of KEYSYMs is associated with each KEYCODE. The list is intended
    to convey the set of symbols on the corresponding key. If the list
    (ignoring trailing NoSymbol entries) is a single KEYSYM "K", then the
    list is treated as if it were the list "K NoSymbol K NoSymbol". If the
    list (ignoring trailing NoSymbol entries) is a pair of KEYSYMs "K1 K2",
    then the list is treated as if it were the list "K1 K2 K1 K2". If the list
    (ignoring trailing NoSymbol entries) is a triple of KEYSYMs "K1 K2 K3",
    then the list is treated as if it were the list "K1 K2 K3 NoSymbol".
    When an explicit "void" element is desired in the list, the value
    VoidSymbol can be used."""
    if 1 < index < 4:
        # This subtle but efficient logic was blatantly stolen from Xlib's
        # KeyCodetoKeySym function.
        n = len(keysyms)
        while n > 2 and keysyms[n - 1] == NoSymbol:
            n -= 1
        if n < 3:
            index -= 2
    return index

def effective_keysym(keysyms, index):
    """From the X11 protocol specification (Chapter 5, ¶4):

    The first four elements of the list are split into two groups of KEYSYMs.
    Group 1 contains the first and second KEYSYMs; Group 2 contains the third
    and fourth KEYSYMs. Within each group, if the second element of the group
    is NoSymbol, then the group should be treated as if the second element
    were the same as the first element, except when the first element is an
    alphabetic KEYSYM "K" for which both lowercase and uppercase forms are
    defined. In that case, the group should be treated as if the first element
    were the lowercase form of "K" and the second element were the uppercase
    form of "K"."""
    if index < 4:
        index = effective_index(keysyms, index)
        if keysyms[index | 1] == NoSymbol:
            keysym = keysyms[index & ~1]
            return upper(keysym) if index & 1 else lower(keysym)
    return keysyms[index]

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

    def __init__(self, conn, cookie=None):
        setup = conn.get_setup()
        self.min_keycode = setup.min_keycode
        self.max_keycode = setup.max_keycode
        super(KeyboardMap, self).__init__(conn, cookie,
                                          self.min_keycode, len(self))

    def refresh(self, first_keycode=None, count=None):
        """Request an updated keyboard mapping for the specified keycodes."""
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
        keysyms = self.keysyms[i:j]
        return (tuple(keysyms) if index is None else
                effective_keysym(self.keysyms[i:j], index))

    def __iter__(self):
        for keycode in range(self.min_keycode, self.max_keycode):
            yield keycode

    def __len__(self):
        return (self.max_keycode - self.min_keycode) + 1

    def keysym_to_keycode(self, keysym):
        """Return the first keycode that generates the given symbol."""
        for j in range(self.keysyms_per_keycode):
            for i in range(self.min_keycode, self.max_keycode + 1):
                if self[(i, j)] == keysym:
                    return i

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
