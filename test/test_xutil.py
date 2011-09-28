# -*- mode: Python; coding: utf-8 -*-

import unittest

from xutil import *

class TestPowerOf2(unittest.TestCase):
    def test_powers_of_2(self):
        self.assertFalse(power_of_2(None))
        self.assertFalse(power_of_2("2"))
        self.assertFalse(power_of_2(-1))
        self.assertFalse(power_of_2(0))
        self.assertFalse(power_of_2(3))
        self.assertFalse(power_of_2(2**32 - 1))

        for i in range(0, 31):
            self.assertTrue(power_of_2(2**i))

class TestValueList(unittest.TestCase):
    class Flags(object):
        X = 1
        Y = 2
        IsVisible = 8
        _foo = "foo"

    def test_value_list(self):
        self.assertEqual(value_list(self.Flags, x="X", y="Y", is_visible=1),
                         (self.Flags.X | self.Flags.Y | self.Flags.IsVisible,
                          ['X', 'Y', 1]))

    def test_invalid_args(self):
        self.assertRaises(KeyError,
                          lambda: value_list(self.Flags, x="X", z="Z"))
        self.assertRaises(KeyError,
                          lambda: value_list(self.Flags, _foo="bar"))

    def test_invalid_flags_class(self):
        class InvalidFlags(object):
            A = 1
            B = 1
        self.assertRaises(AssertionError,
                          lambda: value_list(InvalidFlags, a="a", b="b"))

if __name__ == "__main__":
    unittest.main()
