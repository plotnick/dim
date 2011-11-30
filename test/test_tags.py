# -*- mode: Python; coding: utf-8 -*-

from __future__ import unicode_literals

from math import sqrt
import unittest

from tags import StackUnderflow, TagMachine, TagManager

def primes(n):
    """Return prime numbers < n. Thanks to Ulf Bartelt, via the Python
    Programming FAQ."""
    return filter(None,
                  map(lambda y: y * reduce(lambda x, y: x * y != 0,
                                           map(lambda x, y=y: y % x,
                                               range(2, int(sqrt(y)) + 1)),
                                           1),
                      range(2, n)))

class TestTagMachine(unittest.TestCase):
    def setUp(self):
        n = 100
        self.clients = dict(zip(range(n), range(n)))
        self.clients[None] = -1 # distinguished client with no tag
        self.tagless = set([self.clients[None]])
        self.all_clients = set(self.clients.values())
        self.tagsets = {
            "even": set(self.clients[i] for i in range(n) if i % 2 == 0),
            "odd": set(self.clients[i] for i in range(n) if i % 2 != 0),
            "big": set(self.clients[i] for i in range(n) if i > n / 2),
            "small": set(self.clients[i] for i in range(n) if i <= n / 2),
            "square": set(self.clients[i*i] for i in range(int(sqrt(n)))),
            "prime": set(self.clients[i] for i in primes(n))
        }
        self.opcodes = {"∪": "union",
                        "∩": "intersection",
                        "∖": "difference",
                        "∁": "complement",
                        "*": "all_tags",
                        ".": "current_set",
                        "∅": "empty_set"}
        self.tvm = TagMachine(self.clients, self.tagsets, self.opcodes)

    def test_stack_ops(self):
        x, y = object(), object()
        self.tvm.push(x)
        self.tvm.push(y)
        self.assertEqual(self.tvm.pop(), y)
        self.assertEqual(self.tvm.pop(), x)
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.push(x)
        self.tvm.push(y)
        self.tvm.swap()
        self.tvm.dup()
        self.assertEqual(self.tvm.pop(), x)
        self.assertEqual(self.tvm.pop(), x)
        self.assertEqual(self.tvm.pop(), y)
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.push(x)
        self.tvm.push(y)
        self.tvm.clear()
        self.assertRaises(StackUnderflow, self.tvm.pop)
        self.tvm.clear()
        self.assertRaises(StackUnderflow, self.tvm.pop)

    def test_tags(self):
        self.tvm.tag("square")
        self.assertEqual(self.tvm.pop(), self.tagsets["square"])
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.all_tags()
        self.assertEqual(self.tvm.pop(), self.all_clients - self.tagless)
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.all_clients()
        self.assertEqual(self.tvm.pop(), self.all_clients)
        self.assertRaises(StackUnderflow, self.tvm.pop)

    def test_set_ops(self):
        self.tvm.run(["even", "prime", "∩"])
        self.assertEqual(self.tvm.pop(), set([2]))
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.run(["even", "odd", "∪", "prime", "∩"])
        self.assertEqual(self.tvm.pop(), self.tagsets["prime"])
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.run(["big", "prime", "∖"])
        self.assertEqual(self.tvm.pop(),
                         self.tagsets["big"] - self.tagsets["prime"])
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.run(["even", "∁"])
        self.assertEqual(self.tvm.pop(), self.tagsets["odd"] | self.tagless)
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.run(["square", "∅", "∩"])
        self.assertEqual(self.tvm.pop(), set())
        self.assertRaises(StackUnderflow, self.tvm.pop)

        self.tvm.run(["∅", "∁"])
        self.assertEqual(self.tvm.pop(), self.all_clients)
        self.assertRaises(StackUnderflow, self.tvm.pop)

if __name__ == "__main__":
    unittest.main()
