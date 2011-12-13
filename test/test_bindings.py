# -*- mode: Python; coding: utf-8 -*-

import exceptions
import unittest

import xcb
from xcb.xproto import *

from bindings import all_combinations, ensure_sequence, ensure_keysym, Bindings
from keymap import *
from keysym import *
from xutil import GrabServer

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

    def assertBinding(self, binding, symbol, state, value):
        if value is not None:
            self.assertEqual(binding(symbol, state), value)
        else:
            self.assertRaises(KeyError, lambda: binding(symbol, state))

    def assertKeyBinding(self, keysym, state, value):
        keycode = self.keymap.keysym_to_keycode(keysym)
        self.assertTrue(keycode)
        self.assertBinding(self.bindings.key_binding, keycode, state, value)

    def assertButtonBinding(self, button, state, value):
        self.assertBinding(self.bindings.button_binding, button, state, value)

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

    def test_pointer_bindings(self):
        # We need a predictable pointer mapping, so we'll have to set one.
        # We'll only use the first three buttons, and we'll swap 2 & 3.
        old = list(self.butmap)
        new = [1, 3, 2] + range(4, len(old) + 1)
        self.assertEqual(len(old), len(new))
        try:
            reply = self.conn.core.SetPointerMapping(len(new), new).reply()
            self.assertEqual(reply.status, MappingStatus.Success)
            self.butmap.refresh()
            self.assertEqual(list(self.butmap), new)

            self.bindings = Bindings({},
                                     {1: "button-1",
                                      ("control", 1): "C-button-1",
                                      ("shift", 2): "S-button-2",
                                      3: "button-3"},
                                     self.keymap,
                                     self.modmap,
                                     self.butmap)
            self.assertButtonBinding(1, 0, "button-1")
            self.assertButtonBinding(1, ModMask.Shift, "button-1")
            self.assertButtonBinding(1, ModMask.Control, "C-button-1")
            self.assertButtonBinding(3, 0, None)
            self.assertButtonBinding(3, ModMask.Shift, "S-button-2")
            self.assertButtonBinding(2, ModMask.Shift, "button-3")
        finally:
            # Restore the original pointer mapping.
            self.conn.core.SetPointerMapping(len(old), old).reply()

if __name__ == "__main__":
    unittest.main()