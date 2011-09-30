# -*- mode: Python; coding: utf-8 -*-

import unittest

from keymap import Keymap, effective_index, effective_keysym
from keysym import *

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

    def test_full(self):
        self.assertEffectiveKeysyms([XK_1, XK_2, XK_3, XK_4],
                                    [XK_1, XK_2, XK_3, XK_4])

    def test_nonalpha_nosymbol(self):
        self.assertEffectiveKeysyms([XK_1, NoSymbol, NoSymbol, NoSymbol],
                                    [XK_1, XK_1, XK_1, XK_1])
        self.assertEffectiveKeysyms([XK_1, NoSymbol, XK_2, NoSymbol],
                                    [XK_1, XK_1, XK_2, XK_2])

    def test_alpha_nosymbol(self):
        # "a" and "b" are both alphabetic characters with defined lowercase
        # and uppercase Latin-1 keysyms.
        self.assertEffectiveKeysyms([XK_a, NoSymbol, NoSymbol, NoSymbol],
                                    [XK_a, XK_A, XK_a, XK_A])
        self.assertEffectiveKeysyms([XK_a, NoSymbol, XK_b, NoSymbol],
                                    [XK_a, XK_A, XK_b, XK_B])

        # "ƒ" (LATIN SMALL LETTER F WITH HOOK) and "µ" (MICRO SIGN) are
        # both defined as Latin-1 keysyms, but because their uppercase forms
        # fall outside of the Latin-1 range, they do not have corresponding
        # uppercase keysyms.
        self.assertEffectiveKeysyms([XK_function, NoSymbol, XK_mu, NoSymbol],
                                    [XK_function, XK_function, XK_mu, XK_mu])

        # "ả" (LATIN SMALL LETTER A WITH HOOK ABOVE) and its uppercase form
        # are both defined as Unicode keysyms.
        self.assertEffectiveKeysyms([XK_ahook, NoSymbol, XK_ahook, NoSymbol],
                                    [XK_ahook, XK_Ahook, XK_ahook, XK_Ahook])

if __name__ == "__main__":
    unittest.main()
