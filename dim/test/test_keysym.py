# -*- mode: Python; coding: utf-8 -*-

import unittest

from dim.keysym import *
from dim.keysym import _keysyms # borrow private dictionary from keysymdef
from dim import keysymdef

class TestKeysym(unittest.TestCase):
    def test_mnemonics(self):
        self.assertEqual(XK_VoidSymbol, 0xffffff)
        self.assertEqual(XK_space, 0x20)

    def test_keysym_name(self):
        self.assertEqual(keysym_name(XK_space), "space")
        self.assertEqual(keysym_name(XK_eacute), "eacute")
        self.assertEqual(keysym_name(XK_logicalor), "logicalor")
        self.assertEqual(keysym_name(XK_VoidSymbol), "VoidSymbol")
        self.assertEqual(keysym_name(NoSymbol), None)

        # F12 and L2 are both mnemonics for the same keysym; make sure
        # that we have the former as the canonical name.
        self.assertEqual(keysym_name(XK_F12), "F12")

        # Verify that we have names for all the (non-deprecated) mnemonics.
        mnemonics = [name for name in dir(keysymdef) if name.startswith("XK_")]
        for mnemonic in mnemonics:
            keysym = keysymdef.__dict__[mnemonic]
            try:
                self.assertEqual(keysym_name(keysym), mnemonic[len("XK_"):])
            except AssertionError:
                # Maybe the mnemonic is deprecated; let's try to find
                # a non-deprecated one with the same value.
                for name in mnemonics:
                    other = keysymdef.__dict__[name]
                    if (other == keysym and name != mnemonic):
                        break
                else:
                    raise

    def test_string_to_keysym(self):
        self.assertEqual(string_to_keysym(" "), XK_space)
        self.assertEqual(string_to_keysym(u"é"), XK_eacute)
        self.assertEqual(string_to_keysym(u"\N{LOGICAL OR}"), XK_logicalor)
        self.assertEqual(string_to_keysym("\x00"), NoSymbol)

        for keysym in _keysyms.values():
            if is_unicode_key(keysym):
                # For Unicode characters for which we have a keysym, that
                # keysym should correspond directly to the character.
                char = unichr(keysym & 0x00ffffff)
                self.assertEqual(string_to_keysym(char), keysym)

    def test_keysym_to_string(self):
        self.assertEqual(keysym_to_string(XK_space), u" ")
        self.assertEqual(keysym_to_string(XK_eacute), u"é")
        self.assertEqual(keysym_to_string(XK_logicalor), u"\N{LOGICAL OR}")
        self.assertEqual(keysym_to_string(XK_VoidSymbol), "")

        for keysym in _keysyms.values():
            if is_unicode_key(keysym):
                # For Unicode keysyms, we can be very precise: the string
                # should be equal to the equivalent Unicode character.
                char = unichr(keysym & 0x00ffffff)
                self.assertEqual(keysym_to_string(keysym), char)
            else:
                # For everything else, we'll just insist that the string
                # be non-null.
                self.assertTrue(keysym_to_string(keysym))

    def test_case_conversion(self):
        def case_pair(keysym):
            return (lower(keysym), upper(keysym))

        self.assertEqual(case_pair(NoSymbol), (NoSymbol, NoSymbol))
        self.assertEqual(case_pair(XK_a), (XK_a, XK_A))
        self.assertEqual(case_pair(XK_A), (XK_a, XK_A))
        self.assertEqual(case_pair(XK_1), (XK_1, XK_1))
        self.assertEqual(case_pair(XK_function), (XK_function, XK_function))

        for keysym in _keysyms.values():
            l, u = case_pair(keysym)
            self.assertTrue(keysym_to_string(u))
            self.assertTrue(keysym_to_string(l))
            self.assertTrue(keysym_to_string(keysym) == keysym_to_string(u) or
                            keysym_to_string(keysym) == keysym_to_string(l))

if __name__ == "__main__":
    unittest.main()
