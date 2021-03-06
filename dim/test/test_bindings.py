# -*- mode: Python; coding: utf-8 -*-

import exceptions
import unittest

import xcb
from xcb.xproto import *

from dim.bindings import (all_combinations, ensure_sequence, ensure_keysym,
                          InvalidSymbol,
                          KeyBindingMap, ButtonBindingMap,
                          KeyBindings, ButtonBindings)
from dim.keymap import *
from dim.keysym import *

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
        self.assertRaises(InvalidSymbol, lambda: ensure_keysym(1.0))

class TestBindings(unittest.TestCase):
    def setUp(self):
        self.conn = xcb.connect()
        self.modmap = ModifierMap(self.conn)
        self.keymap = KeyboardMap(self.conn, modmap=self.modmap)

    def tearDown(self):
        self.conn.disconnect()

    def assertBinding(self, key, value):
        self.assertTrue(key)
        if value is None:
            try:
                print self.bindings[key]
            except KeyError:
                pass
            self.assertRaises(KeyError, lambda: self.bindings[key])
        elif isinstance(value, tuple):
            self.assertTrue(self.bindings[key] in value)
        else:
            self.assertEqual(self.bindings[key], value)

    def assertKeyBinding(self, keysym, state, value, press=True):
        self.assertBinding((keysym, state, press), value)

    def assertButtonBinding(self, button, state, value, press=True):
        self.assertBinding((button, state, press), value)

    def test_key_bindings_no_modifiers(self):
        self.bindings = KeyBindings({"a": "key-a", # keysym designator
                                     XK_b: "key-b", # keysym
                                     XK_C: "key-C"}, # uppercase letter
                                    self.keymap,
                                    self.modmap)
        self.assertKeyBinding(XK_a, 0, "key-a")
        self.assertKeyBinding(XK_b, 0, "key-b")
        self.assertKeyBinding(XK_c, 0, None)
        self.assertKeyBinding(XK_C, 0, "key-C")
        self.assertKeyBinding(XK_C, ModMask.Shift, "key-C")

    def test_key_press_release_bindings(self):
        self.bindings = KeyBindings({XK_a: "press-a",
                                     -XK_a: "release-a",
                                     ("control", -XK_a): "release-C-a"},
                                     self.keymap,
                                     self.modmap)
        self.assertKeyBinding(XK_a, 0, "press-a", True)
        self.assertKeyBinding(XK_a, 0, "release-a", False)
        self.assertKeyBinding(XK_a, ModMask.Control, "release-C-a", False)

    def test_key_bindings_aliases(self):
        # In this test, we'll assume that NumLock is bound to some modifier,
        # and that the mappings for both the normal and keypad "1" key are
        # the usual ones (i.e., 1/exclam and KP_1/KP_End).
        num_lock = self.keymap.num_lock
        self.assertNotEqual(num_lock, 0)

        key_bindings = KeyBindingMap({XK_1: "1",
                                      XK_End: "end"},
                                     aliases={XK_KP_1: XK_1,
                                              XK_KP_End: XK_End})
        self.bindings = KeyBindings(key_bindings, self.keymap, self.modmap)
        self.assertKeyBinding(XK_1, 0, "1")
        self.assertKeyBinding(XK_End, 0, "end")
        self.assertKeyBinding(XK_KP_1, 0, ("1", "end"))
        self.assertKeyBinding(XK_KP_1, num_lock, ("1", "end"))

    def test_binding_inheritance(self):
        # We'll need a NumLock modifier for this test, too.
        num_lock = self.keymap.num_lock
        self.assertNotEqual(num_lock, 0)

        base_bindings = KeyBindingMap({XK_1: "1"},
                                      aliases={XK_KP_1: XK_1})
        child_bindings = KeyBindingMap({XK_2: "2"},
                                       parent=base_bindings,
                                       aliases={XK_KP_2: XK_2})
        self.bindings = KeyBindings(child_bindings, self.keymap, self.modmap)
        self.assertKeyBinding(XK_1, 0, "1")
        self.assertKeyBinding(XK_KP_1, num_lock, "1")
        self.assertKeyBinding(XK_2, 0, "2")
        self.assertKeyBinding(XK_KP_2, num_lock, "2")

    def test_key_bindings_modifiers(self):
        # In this test we'll assume that alt and meta are both bound,
        # and to the same bucky bit.
        alt = self.keymap.alt
        meta = self.keymap.meta
        self.assertNotEqual(alt, 0)
        self.assertEqual(alt, meta)

        self.bindings = KeyBindings({("control", "a"): "C-a",
                                     ("meta", "a"): "M-a",
                                     ("meta", "%"): "C-A-%", # shifted
                                     ("control", "meta", "b"): "C-M-b",
                                     ("control", "alt", "c"): "C-A-c"},
                                    self.keymap,
                                    self.modmap)
        self.assertKeyBinding(XK_a, ModMask.Control, "C-a")
        self.assertKeyBinding(XK_a, alt, "M-a")
        self.assertKeyBinding(XK_a, meta, "M-a")
        self.assertKeyBinding(XK_percent, ModMask.Shift | meta, "C-A-%")
        self.assertKeyBinding(XK_b, ModMask.Control, None)
        self.assertKeyBinding(XK_b, ModMask.Control | alt, "C-M-b")
        self.assertKeyBinding(XK_b, ModMask.Control | meta, "C-M-b")
        self.assertKeyBinding(XK_c, ModMask.Control | alt, "C-A-c")
        self.assertKeyBinding(XK_c, ModMask.Control | meta, "C-A-c")
        self.assertKeyBinding(XK_percent, ModMask.Control | alt, None)

    def test_button_bindings(self):
        self.bindings = ButtonBindings({1: "button-1",
                                        ("control", 1): "C-button-1",
                                        ("shift", 2): "S-button-2",
                                        -2: "release-2",
                                        3: "button-3"},
                                       self.keymap,
                                       self.modmap)
        self.assertButtonBinding(1, 0, "button-1")
        self.assertButtonBinding(1, ModMask.Shift, "button-1")
        self.assertButtonBinding(1, ModMask.Control, "C-button-1")
        self.assertButtonBinding(2, 0, None)
        self.assertButtonBinding(2, 0, "release-2", False)
        self.assertButtonBinding(2, ModMask.Shift, "S-button-2")
        self.assertButtonBinding(3, ModMask.Shift, "button-3")

if __name__ == "__main__":
    unittest.main()
