# -*- mode: Python; coding: utf-8 -*-

import unittest
from operator import itemgetter
from random import choice, shuffle

import xcb
from xcb.xproto import *

from keymap import *
from keymap import effective_index, effective_keysym
from keysym import *

def flatten(l):
    return [l[i][j] for i in range(len(l)) for j in range(len(l[i]))]

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

class MappingTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = xcb.connect()

        # We don't want other clients changing the mappings during these
        # tests, and it's not worth processing MappingNotify events just
        # to detect such an eventuality. So we'll lazy out and run them
        # with the whole server grabbed.
        self.conn.core.GrabServer()

    def tearDown(self):
        self.conn.core.UngrabServer()
        self.conn.disconnect()

class TestKeyboardMap(MappingTestCase):
    def setUp(self):
        super(TestKeyboardMap, self).setUp()
        self.keymap = KeyboardMap(self.conn)

    def change_keyboard_mapping(self, first_keycode, keysyms):
        """Given an initial keycode and a list of lists of keysyms, make an
        appropriate ChangeKeyboardMapping request. All of the keysym lists
        must be of the same length."""
        keycode_count = len(keysyms)
        keysyms_per_keycode = len(keysyms[0])
        keysyms = flatten(keysyms)
        self.assertEqual(len(keysyms), keycode_count * keysyms_per_keycode)
        self.conn.core.ChangeKeyboardMappingChecked(keycode_count,
            first_keycode, keysyms_per_keycode, keysyms).check()

    def test_init_with_cookie(self):
        cookie = self.conn.core.GetKeyboardMapping(8, 248)
        keymap = KeyboardMap(self.conn, cookie)
        self.assertEqual(len(keymap), 248)

        # Can't start with a partial keymap.
        cookie = self.conn.core.GetKeyboardMapping(8, 16)
        self.assertRaises(KeymapError, lambda: KeyboardMap(self.conn, cookie))

    def test_full_refresh(self):
        keysyms = self.keymap.values()
        self.keymap.refresh()
        self.assertEqual(keysyms, self.keymap.values())

    def test_partial_refresh(self):
        def make_keysym_list(letters=[chr(ord("a") + i) for i in range(26)]):
            keysym = string_to_keysym(choice(letters))
            return [keysym, upper(keysym), keysym, upper(keysym)]

        n = 10 # a random number of keycodes
        keycode = 38 # a random keycode
        old = [self.keymap[keycode + i] for i in range(n)]
        new = [make_keysym_list() for i in range(n)]
        try:
            self.change_keyboard_mapping(keycode, new)
            self.keymap.refresh(keycode, n)
            self.assertEqual([list(self.keymap[keycode + i][:4])
                              for i in range(n)],
                             new)
        finally:
            self.change_keyboard_mapping(keycode, old)
        self.keymap.refresh(keycode, n)
        self.assertEqual([self.keymap[keycode + i] for i in range(n)], old)

    def test_failed_partial_refresh(self):
        def make_keysym_list(length):
            # We should be able to just use lists consisting of nothing
            # but VoidSymbol, but some servers seem to special-case trailing
            # VoidSymbols, so we'll use numbers instead.
            return [string_to_keysym(chr(ord("1") + i)) for i in range(length)]

        keycode = 42 # another random keycode
        m = self.keymap.keysyms_per_keycode
        old = [self.keymap[keycode]]
        new = [make_keysym_list(m + 2)]
        try:
            self.change_keyboard_mapping(keycode, new)
            try:
                # This should fail, because keysyms-per-keycode in the reply
                # to the GetKeyboardMapping request will not match the cached
                # value.
                self.keymap.refresh(keycode, 1)
            except KeymapError:
                # However, a full refresh should succeed, since it can just
                # re-initialize the whole mapping.
                self.keymap.refresh()
                self.assertTrue(self.keymap.keysyms_per_keycode >= m + 2)
                self.assertEqual([list(self.keymap[keycode][:m + 2])], new)
            else:
                self.fail("partial refresh unexpectedly succeeded")
        finally:
            self.change_keyboard_mapping(keycode, old)
        self.keymap.refresh()
        # It's possible that the server might keep the new keysyms-per-keycode
        # (it is free to do so, even though it's no longer necessary), so we'll
        # check against the old value.
        self.assertEqual([self.keymap[keycode][:m]], old)

    def test_keycode_to_keysym(self):
        # We'll assume that there's a keycode that generates the symbol XK_a,
        # and that it has the usual list of keysyms bound to it.
        a = self.keymap.keysym_to_keycode(XK_a)
        self.assertTrue(a > 0)
        self.assertEqual(list(self.keymap[a][:4]), [XK_a, XK_A, XK_a, XK_A])
        self.assertEqual(self.keymap[(a, 0)], XK_a)
        self.assertEqual(self.keymap[(a, 1)], XK_A)
        self.assertEqual(self.keymap[(a, 2)], XK_a)
        self.assertEqual(self.keymap[(a, 3)], XK_A)

        # We'll make a similar assumption for XK_Escape.
        esc = self.keymap.keysym_to_keycode(XK_Escape)
        self.assertTrue(esc > 0)
        self.assertEqual(list(self.keymap[esc][:4]),
                         [XK_Escape, NoSymbol, XK_Escape, NoSymbol])
        for i in range(4):
            # Although the second element in each group is NoSymbol, the
            # effectice keysym for all four positions should be the same.
            self.assertEqual(self.keymap[(esc, i)], XK_Escape)

class TestModifierMap(MappingTestCase):
    def test_init_with_cookie(self):
        modmap = ModifierMap(self.conn, self.conn.core.GetModifierMapping())
        self.assertTrue(len(modmap) == 8)
        for i in range(8):
            self.assertEqual(len(modmap[i]), modmap.keycodes_per_modifier)

    def test_modmap(self):
        keymap = KeyboardMap(self.conn)
        shift_l, shift_r, control_l, control_r = \
            map(keymap.keysym_to_keycode,
                (XK_Shift_L, XK_Shift_R, XK_Control_L, XK_Control_R))

        modmap = ModifierMap(self.conn)
        # We'll assume a standard modifier layout for shift & control
        # wherein both the left and right keycodes are bound.
        self.assertTrue(shift_l in modmap[MapIndex.Shift] and
                        shift_r in modmap[MapIndex.Shift])
        self.assertTrue(control_l in modmap[MapIndex.Control] and
                        control_r in modmap[MapIndex.Control])

    def test_refresh(self):
        modmap = ModifierMap(self.conn)
        n = modmap.keycodes_per_modifier
        old = modmap.values()
        new = old[:]
        shuffle(new)
        try:
            reply = self.conn.core.SetModifierMapping(n, flatten(new)).reply()
            self.assertEqual(reply.status, MappingStatus.Success)
            modmap.refresh()
            self.assertEqual(modmap.values(), new)
        finally:
            self.conn.core.SetModifierMapping(n, flatten(old)).reply()
        modmap.refresh()
        self.assertEqual(modmap.values(), old)

class TestPointerMap(MappingTestCase):
    def test_init_with_cookie(self):
        pointer_map = PointerMap(self.conn, self.conn.core.GetPointerMapping())
        self.assertTrue(len(pointer_map) >= 3)

    def test_pointer_map(self):
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
