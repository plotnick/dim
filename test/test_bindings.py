# -*- mode: Python; coding: utf-8 -*-

import exceptions
import unittest

import xcb
from xcb.xproto import *

from bindings import all_combinations, ensure_sequence, ensure_keysym, Bindings
from keymap import *
from keysym import *

class TestAuxFunctions(unittest.TestCase):
    def test_all_combinations(self):
        self.assertEqual(list(all_combinations([(0, 1), (2,), (3, 4)])),
                         [[0, 2, 3],
                          [0, 2, 4],
                          [1, 2, 3],
                          [1, 2, 4]])

    def test_ensure_sequence(self):
        self.assertEqual(ensure_sequence("foo"), ("foo",))
        self.assertEqual(ensure_sequence(("foo",)), ("foo",))
        self.assertEqual(ensure_sequence(["foo"]), ["foo"])

    def test_ensure_keysym(self):
        self.assertEqual(ensure_keysym(XK_a), XK_a)
        self.assertEqual(ensure_keysym("a"), XK_a)
        self.assertRaises(exceptions.ValueError, lambda: ensure_keysym(1.0))

class TestBindings(unittest.TestCase):
    def setUp(self):
        self.conn = xcb.connect()
        self.modmap = ModifierMap(self.conn)
        self.keymap = KeyboardMap(self.conn, modmap=self.modmap)
        self.butmap = PointerMap(self.conn)

    def tearDown(self):
        self.conn.disconnect()

    def assertKeyBinding(self, keysym, state, value):
        keycode = self.keymap.keysym_to_keycode(keysym)
        self.assertTrue(keycode)
        if value is not None:
            self.assertEqual(self.bindings.key_binding(keycode, state), value)
        else:
            self.assertRaises(KeyError,
                              lambda: self.bindings.key_binding(keycode, state))

    def test_key_bindings_no_modifiers(self):
        self.bindings = Bindings({"a": "key-a", # keysym designator
                                  XK_b: "key-b", # keysym
                                  XK_C: "key-C"}, # uppercase letter (shifted)
                                 {},
                                 self.keymap,
                                 self.modmap,
                                 self.butmap)
        self.assertKeyBinding(XK_a, 0, "key-a")
        self.assertKeyBinding(XK_b, 0, "key-b")
        self.assertKeyBinding(XK_c, 0, None)
        self.assertKeyBinding(XK_C, 0, None)
        self.assertKeyBinding(XK_c, ModMask.Shift, "key-C")
        self.assertKeyBinding(XK_C, ModMask.Shift, "key-C")

    def test_key_bindings_modifiers(self):
        # In this test we'll assume that alt and meta are both bound,
        # and to the same bucky bit.
        alt = self.keymap.alt
        meta = self.keymap.meta
        self.assertNotEqual(alt, 0)
        self.assertEqual(alt, meta)

        self.bindings = Bindings({("control", "a"): "C-a",
                                  ("meta", "a"): "M-a",
                                  ("control", "meta", "b"): "C-M-b",
                                  ("control", "alt", "c"): "C-A-c",
                                  ("control", "alt", "%"): "C-A-%"}, # shifted
                                 {},
                                 self.keymap,
                                 self.modmap,
                                 self.butmap)
        self.assertKeyBinding(XK_a, ModMask.Control, "C-a")
        self.assertKeyBinding(XK_a, alt, "M-a")
        self.assertKeyBinding(XK_a, meta, "M-a")
        self.assertKeyBinding(XK_b, ModMask.Control, None)
        self.assertKeyBinding(XK_b, ModMask.Control | alt, "C-M-b")
        self.assertKeyBinding(XK_b, ModMask.Control | meta, "C-M-b")
        self.assertKeyBinding(XK_c, ModMask.Control | alt, "C-A-c")
        self.assertKeyBinding(XK_c, ModMask.Control | meta, "C-A-c")
        self.assertKeyBinding(XK_percent, ModMask.Control | alt, None)
        self.assertKeyBinding(XK_percent,
                              ModMask.Shift | ModMask.Control | alt,
                              "C-A-%")

if __name__ == "__main__":
    unittest.main()
