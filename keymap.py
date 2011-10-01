# -*- mode: Python; coding: utf-8 -*-

from array import array

from xcb.xproto import *

from keysym import NoSymbol, upper, lower

__all__ = ["Keymap"]

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

class Keymap(object):
    """A map from keycodes to keysyms (and vice-versa)."""

    def __init__(self, conn):
        setup = conn.get_setup()
        self.conn = conn
        self.min_keycode = setup.min_keycode
        self.max_keycode = setup.max_keycode

        # Always fetch the entire map on initialization.
        first_keycode = self.min_keycode
        count = (self.max_keycode - first_keycode) + 1
        reply = self.conn.core.GetKeyboardMapping(first_keycode, count).reply()
        self.keysyms_per_keycode = reply.keysyms_per_keycode
        self.check_reply(reply, count * self.keysyms_per_keycode)
        self.keysyms = array("I", reply.keysyms)

    def refresh(self, first_keycode=None, count=None):
        """Request an updated keyboard mapping for the specified keycodes."""
        if first_keycode is None:
            first_keycode = self.min_keycode
        if count is None:
            count = (self.max_keycode - first_keycode) + 1

        # Only replace the keysym range that was requested.
        reply = self.conn.core.GetKeyboardMapping(first_keycode, count).reply()
        n = self.keysyms_per_keycode
        i = (first_keycode - self.min_keycode) * n
        j = i + (count * n)
        self.check_reply(reply, j - i)
        self.keysyms[i:j] = array("I", reply.keysyms)

    def check_reply(self, reply, nkeysyms):
        if reply.keysyms_per_keycode != self.keysyms_per_keycode:
            raise KeymapError("number of keysyms per keycode changed")
        if len(reply.keysyms) != nkeysyms:
            raise KeymapError("did not receive the expected number of keysyms")

    def keycode_to_keysym(self, keycode, index):
        """Return the index'th symbol bound to the given keycode."""
        n = self.keysyms_per_keycode
        i = (keycode - self.min_keycode) * n
        j = i + n
        return effective_keysym(self.keysyms[i:j], index)

    def __getitem__(self, key):
        """Retrieve the symbol associated with a keycode.

        As a convenience, the key may be either a (keycode, index) tuple,
        or a raw keycode, in which case the index defaults to 0."""
        if isinstance(key, tuple):
            return self.keycode_to_keysym(*key)
        else:
            return self.keycode_to_keysym(key, 0)

    def keysym_to_keycode(self, keysym):
        """Return the first keycode that generates the given symbol."""
        for j in range(self.keysyms_per_keycode):
            for i in range(self.min_keycode, self.max_keycode + 1):
                if self.keycode_to_keysym(i, j) == keysym:
                    return i
