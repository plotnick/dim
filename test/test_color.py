# -*- mode: Python; coding: utf-8 -*-

import unittest

from color import *

class TestParseColor(unittest.TestCase):
    def test_hex_spec(self):
        self.assertEqual(parse_color("#3a7"), (0x3000, 0xa000, 0x7000))
        self.assertEqual(parse_color("#34ab78"), (0x3400, 0xab00, 0x7800))
        self.assertEqual(parse_color("#345abc789"), (0x3450, 0xabc0, 0x7890))
        self.assertEqual(parse_color("#3456abcd789a"), (0x3456, 0xabcd, 0x789a))

if __name__ == "__main__":
    unittest.main()
