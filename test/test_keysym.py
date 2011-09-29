# -*- mode: Python; coding: utf-8 -*-

import unittest

from keysym import *

class TestKeysym(unittest.TestCase):
    def test_keysym(self):
        self.assertEqual(XK_space, 0x20)
        self.assertEqual(XK_VoidSymbol, 0xffffff)

    def test_string_to_keysym(self):
        self.assertEqual(string_to_keysym(" "), XK_space)
        self.assertEqual(string_to_keysym(u"\N{LOGICAL OR}"), XK_logicalor)
        self.assertRaises(KeyError, lambda: string_to_keysym("\0"))

    def test_keysym_to_string(self):
        self.assertEqual(keysym_to_string(XK_space), "space")
        self.assertEqual(keysym_to_string(XK_logicalor), "logicalor")
        self.assertRaises(KeyError, lambda: keysym_to_string(0))

if __name__ == "__main__":
    unittest.main()
