# -*- mode: Python; coding: utf-8 -*-

import unittest

from dim.cycle import ModalKeyBindingMap
from dim.keysym import *

class TestModalKeyBindingMap(unittest.TestCase):
    def test_parse_bindings(self):
        bindings = {XK_a: "a", None: 0}
        alt = frozenset(["alt"])
        control = frozenset(["control"])
        void = frozenset([])
        self.assertEqual(ModalKeyBindingMap(void, bindings),
                         {(void, XK_a, True): "a"})
        self.assertEqual(ModalKeyBindingMap(alt | control, bindings),
                         {(alt, XK_Alt_L, False): 0,
                          (alt, XK_Alt_R, False): 0,
                          (control, XK_Control_L, False): 0,
                          (control, XK_Control_R, False): 0,
                          (alt | control, XK_a, True): "a"})

if __name__ == "__main__":
    unittest.main()
