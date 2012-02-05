# -*- mode: Python; coding: utf-8 -*-

import unittest

from xutil import *

class TestTimestamps(unittest.TestCase):
    def assertBefore(self, x, y):
        self.assertTrue(compare_timestamps(x, y) < 0)
        self.assertTrue(compare_timestamps(y, x) > 0)

    def assertCoincident(self, x, y):
        self.assertTrue(compare_timestamps(x, y) == 0)
        self.assertTrue(compare_timestamps(y, x) == 0)

    def assertAfter(self, x, y):
        self.assertTrue(compare_timestamps(x, y) > 0)
        self.assertTrue(compare_timestamps(y, x) < 0)

    def test_compare_timestamps(self):
        t1 = 0x00000001
        t2 = 0x20000000
        t3 = 0x40000000
        t4 = 0x80000000
        t5 = 0xa0000000
        t6 = 0xc0000000
        t7 = 0xffffffff

        for t in (0, t1, t2, t3, t4, t5, t6, t7):
            self.assertCoincident(t, t)

        # CurrentTime is after everything except itself.
        for t in (t1, t2, t3, t4, t5, t6, t7):
            self.assertAfter(0, t)

        self.assertBefore(t1, t2)
        self.assertBefore(t1, t3)
        self.assertBefore(t1, t4)
        self.assertAfter(t1, t5) # wrapped around
        self.assertAfter(t1, t6) # wrapped around
        self.assertAfter(t1, t7) # wrapped around
        self.assertBefore(t2, t3)
        self.assertBefore(t2, t4)
        self.assertBefore(t2, t5)
        self.assertAfter(t2, t6) # wrapped around
        self.assertAfter(t2, t7) # wrapped around
        self.assertAfter(t3, t7) # wrapped around
        self.assertBefore(t4, t7)
        self.assertBefore(t5, t7)
        self.assertBefore(t6, t7)

if __name__ == "__main__":
    unittest.main()
