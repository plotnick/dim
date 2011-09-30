# -*- mode: Python; coding: utf-8 -*-

import unittest

from keysym import *
from keysym import _keysyms # borrow private dictionary from keysymdef

class TestKeysym(unittest.TestCase):
    def test_keysym(self):
        self.assertEqual(XK_VoidSymbol, 0xffffff)
        self.assertEqual(XK_space, 0x20)

    def test_keysym_name(self):
        self.assertEqual(keysym_name(XK_space), "space")
        self.assertEqual(keysym_name(XK_eacute), "eacute")
        self.assertEqual(keysym_name(XK_logicalor), "logicalor")
        self.assertEqual(keysym_name(XK_VoidSymbol), "VoidSymbol")
        self.assertRaises(KeyError, lambda: keysym_name(NoSymbol))

    def test_string_to_keysym(self):
        self.assertEqual(string_to_keysym(" "), XK_space)
        self.assertEqual(string_to_keysym(u"é"), XK_eacute)
        self.assertEqual(string_to_keysym(u"\N{LOGICAL OR}"), XK_logicalor)
        self.assertRaises(KeyError, lambda: string_to_keysym("\x00"))

        for keysym in _keysyms.values():
            if is_unicode(keysym):
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
            if is_unicode(keysym):
                # For Unicode keysyms, we can be very precise: the string
                # should be equal to the equivalent Unicode character.
                char = unichr(keysym & 0x00ffffff)
                self.assertEqual(keysym_to_string(keysym), char)
            else:
                # For everything else, we'll just insist that the string
                # be non-null.
                self.assertTrue(keysym_to_string(keysym))

    def test_case_conversion(self):
        for keysym in _keysyms.values():
            u, l = upper(keysym), lower(keysym)
            self.assertTrue(keysym_to_string(u))
            self.assertTrue(keysym_to_string(l))
            self.assertTrue(keysym_to_string(keysym) == keysym_to_string(u) or
                            keysym_to_string(keysym) == keysym_to_string(l))

if __name__ == "__main__":
    unittest.main()
