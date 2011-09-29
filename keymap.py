# -*- mode: Python; coding: utf-8 -*-

from xcb.xproto import *

class Keymap(object):
    """A map from keycodes to keysyms (and vice-versa)."""

    def __init__(self, conn):
        setup = conn.get_setup()
        self.conn = conn
        self.min_keycode = setup.min_keycode
        self.max_keycode = setup.max_keycode

        n = (self.max_keycode - self.min_keycode) + 1
        reply = self.conn.core.GetKeyboardMapping(self.min_keycode, n).reply()
        self.keysyms = reply.keysyms
        self.keysyms_per_keycode = reply.keysyms_per_keycode

    def refresh(self, first_keycode=None, count=None):
        if first_keycode is None:
            first_keycode = self.min_keycode
        if count is None:
            count = (self.max_keycode - first_keycode) + 1

        reply = self.conn.core.GetKeyboardMapping(first_keycode, count).reply()
        if reply.keysyms_per_keycode == self.keysyms_per_keycode:
            # Only replace the keysym range that was changed.
            i = first_keycode - self.min_keycode
            j = i + (count * self.keysyms_per_keycode)
            assert (j - i) == len(reply.keysyms)
            self.keysyms[i:j] = reply.keysyms
        else:
            raise ValueError("number of keysyms per keycode changed")

    def keycode_to_keysym(self, keycode, index):
        """Return the index'th symbol bound to a keycode."""
        i = (keycode - self.min_keycode) * self.keysyms_per_keycode
        return self.keysyms[i + index]

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
