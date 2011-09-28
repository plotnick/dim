# -*- mode: Python; coding: utf-8 -*-

import unittest

from geometry import *

class TestIsMoveOnly(unittest.TestCase):
    """Test case for the is_move_only function."""

    def test_null_geometry(self):
        """Test is_move_only with null geometry"""
        self.assertFalse(is_move_only(None, None))
        self.assertFalse(is_move_only(None, Geometry(1, 1, 1, 1, 1)))
        self.assertFalse(is_move_only(Geometry(1, 1, 1, 1, 1), None))

    def test_is_move_only(self):
        """Test is_move_only"""
        g = Geometry(1, 1, 1, 1, 1)
        self.assertFalse(is_move_only(g, Geometry(1, 1, 1, 1, 1)))
        self.assertFalse(is_move_only(g, Geometry(2, 2, 2, 2, 1)))
        self.assertFalse(is_move_only(g, Geometry(2, 2, 1, 1, 2)))
        self.assertTrue(is_move_only(g, Geometry(2, 2, 1, 1, 1)))

if __name__ == "__main__":
    unittest.main()
