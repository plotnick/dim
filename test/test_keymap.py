# -*- mode: Python; coding: utf-8 -*-

import unittest
from random import shuffle

import xcb
from xcb.xproto import *

from keymap import *
from keymap import effective_index, effective_keysym
from keysym import *
from xutil import GrabServer

class TestEffectiveIndex(unittest.TestCase):
    def assertEffectiveIndices(self, keysyms, indices):
        self.assertEqual(len(keysyms), len(indices))
        for i in range(len(keysyms)):
            self.assertEqual(effective_index(keysyms, i), indices[i])

    def test_singleton(self):
        self.assertEffectiveIndices([XK_a, NoSymbol, NoSymbol, NoSymbol],
                                    [0, 1, 0, 1])

    def test_pair(self):
        self.assertEffectiveIndices([XK_a, XK_A, NoSymbol, NoSymbol],
                                    [0, 1, 0, 1])

    def test_triple(self):
        self.assertEffectiveIndices([XK_a, XK_A, XK_b, NoSymbol],
                                    [0, 1, 2, 3])
    def test_quad(self):
        self.assertEffectiveIndices([XK_a, XK_A, XK_b, XK_B],
                                    [0, 1, 2, 3])

    def test_long_lists(self):
        self.assertEffectiveIndices([XK_a] + [NoSymbol] * 5,
                                    [0, 1, 0, 1, 4, 5])
        self.assertEffectiveIndices([XK_a, XK_A] + [NoSymbol] * 4,
                                    [0, 1, 0, 1, 4, 5])
        self.assertEffectiveIndices([XK_a, XK_A, XK_b] + [NoSymbol] * 3,
                                    [0, 1, 2, 3, 4, 5])
        self.assertEffectiveIndices([XK_a, XK_A, XK_b, XK_B] + [NoSymbol] * 2,
                                    [0, 1, 2, 3, 4, 5])
        self.assertEffectiveIndices([XK_a, XK_A, XK_b, XK_B, XK_c, XK_C],
                                    [0, 1, 2, 3, 4, 5])

class TestEffectiveKeysym(unittest.TestCase):
    def assertEffectiveKeysyms(self, keysyms, effective_keysyms):
        self.assertEqual(len(keysyms), len(effective_keysyms))
        for i in range(len(keysyms)):
            self.assertEqual(effective_keysym(keysyms, i), effective_keysyms[i])

    def test_empty(self):
        self.assertEffectiveKeysyms([NoSymbol] * 4,
                                    [NoSymbol] * 4)

    def test_full(self):
        self.assertEffectiveKeysyms([XK_1, XK_2, XK_3, XK_4],
                                    [XK_1, XK_2, XK_3, XK_4])

    def test_nonalpha_nosymbol(self):
        self.assertEffectiveKeysyms([XK_1, NoSymbol, NoSymbol, NoSymbol],
                                    [XK_1, XK_1, XK_1, XK_1])
        self.assertEffectiveKeysyms([NoSymbol, NoSymbol, XK_2, NoSymbol],
                                    [NoSymbol, NoSymbol, XK_2, XK_2])
        self.assertEffectiveKeysyms([XK_1, NoSymbol, XK_2, NoSymbol],
                                    [XK_1, XK_1, XK_2, XK_2])

    def test_alpha_nosymbol(self):
        # "a" and "b" are both alphabetic characters with defined lowercase
        # and uppercase Latin-1 keysyms.
        self.assertEffectiveKeysyms([XK_a, NoSymbol, NoSymbol, NoSymbol],
                                    [XK_a, XK_A, XK_a, XK_A])
        self.assertEffectiveKeysyms([NoSymbol, NoSymbol, XK_a, NoSymbol],
                                    [NoSymbol, NoSymbol, XK_a, XK_A])
        self.assertEffectiveKeysyms([XK_a, NoSymbol, XK_b, NoSymbol],
                                    [XK_a, XK_A, XK_b, XK_B])

        # "ƒ" (LATIN SMALL LETTER F WITH HOOK) has an uppercase Unicode form,
        # but there is no corresponding keysym.
        self.assertEffectiveKeysyms([XK_function, NoSymbol],
                                    [XK_function, XK_function])

        # "ả" (LATIN SMALL LETTER A WITH HOOK ABOVE) and its uppercase form
        # are both defined as Unicode keysyms. "µ" (MICRO SIGN) is defined
        # as a Latin-1 keysym, but its uppercase form falls outside of the
        # Latin-1 range. We differ from Xlib in this latter case: Xlib does
        # not consider XK_Greek_MU to be the uppercase form of XK_mu, but
        # we do.
        self.assertEffectiveKeysyms([XK_ahook, NoSymbol, XK_mu, NoSymbol],
                                    [XK_ahook, XK_Ahook, XK_mu, XK_Greek_MU])

class TestKeyboardMap(unittest.TestCase):
    def setUp(self):
        self.conn = xcb.connect()

    def tearDown(self):
        self.conn.disconnect()

    def test_init_with_cookie(self):
        cookie = self.conn.core.GetKeyboardMapping(8, 248)
        keymap = KeyboardMap(self.conn, cookie)
        self.assertEqual(len(keymap), 248)

        # Can't start with a partial keymap.
        cookie = self.conn.core.GetKeyboardMapping(8, 16)
        self.assertRaises(KeymapError, lambda: KeyboardMap(self.conn, cookie))

    def test_refresh(self):
        # We don't want other clients changing the keyboard map during this
        # test, and it's not worth processing MappingNotify events just to
        # detect such an eventuality. So we'll lazy out and run this test
        # with the whole server grabbed.
        with GrabServer(self.conn):
            keymap = KeyboardMap(self.conn)
            self.assertEqual(len(keymap), 248)
            keycode = 38 # a random keycode
            old = keymap[keycode]
            new = [XK_VoidSymbol] * 4
            try:
                self.conn.core.ChangeKeyboardMappingChecked(1, keycode,
                                                            len(new),
                                                            new).check()
                keymap.refresh(keycode, 1)
                self.assertEqual(list(keymap[keycode][:4]), new)
            finally:
                self.conn.core.ChangeKeyboardMappingChecked(1, keycode,
                                                            len(old),
                                                            old).check()
            keymap.refresh(keycode, 1)
            self.assertEqual(keymap[keycode], old)

    def test_keymap(self):
        keymap = KeyboardMap(self.conn)
        self.assertEqual(len(keymap), 248)

        # We'll assume there's a keycode that generates the symbol XK_a,
        # and that it has the usual list of keysyms bound to it.
        a = keymap.keysym_to_keycode(XK_a)
        self.assertTrue(a > 0)
        self.assertEqual(list(keymap[a][:4]), [XK_a, XK_A, XK_a, XK_A])
        self.assertEqual(keymap[(a, 0)], XK_a)
        self.assertEqual(keymap[(a, 1)], XK_A)
        self.assertEqual(keymap[(a, 2)], XK_a)
        self.assertEqual(keymap[(a, 3)], XK_A)

        # We'll make a similar assumption for XK_Escape.
        esc = keymap.keysym_to_keycode(XK_Escape)
        self.assertTrue(esc > 0)
        self.assertEqual(list(keymap[esc][:4]),
                         [XK_Escape, NoSymbol, XK_Escape, NoSymbol])
        for i in range(4):
            # Although the second element in each group is NoSymbol, the
            # effectice keysym for all four positions should be the same.
            self.assertEqual(keymap[(esc, i)], XK_Escape)

class TestPointerMap(unittest.TestCase):
    def setUp(self):
        self.conn = xcb.connect()

    def tearDown(self):
        self.conn.disconnect()

    def test_init_with_cookie(self):
        pointer_map = PointerMap(self.conn, self.conn.core.GetPointerMapping())
        self.assertTrue(len(pointer_map) >= 3)

    def test_pointer_map(self):
        with GrabServer(self.conn):
            pointer_map = PointerMap(self.conn)
            self.assertTrue(len(pointer_map) >= 3)
            self.assertTrue(0 not in pointer_map)
            old = list(pointer_map)
            new = old[:]
            shuffle(new)
            try:
                reply = self.conn.core.SetPointerMapping(len(new), new).reply()
                self.assertEqual(reply.status, MappingStatus.Success)
                pointer_map.refresh()
                self.assertEqual(list(pointer_map), new)
            finally:
                self.conn.core.SetPointerMapping(len(old), old).reply()
            pointer_map.refresh()
            self.assertEqual(list(pointer_map), old)

if __name__ == "__main__":
    unittest.main()
