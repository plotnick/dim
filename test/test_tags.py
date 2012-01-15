# -*- mode: Python; coding: utf-8 -*-

from __future__ import unicode_literals

from collections import defaultdict
from random import randint
from math import sqrt
import unittest

from xcb.xproto import *

from event import *
from geometry import *
from properties import AtomList
from tags import StackUnderflow, TagMachine, TagManager

from test_manager import TestClient, WMTestCase

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
        """Tag machine stack operations"""
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
        """Tag machine tags"""
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
        """Tag machine set operations"""
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

class TaggedClient(TestClient):
    def __init__(self, tags):
        # The geometry is irrelevant, so we'll use a random one.
        super(TaggedClient, self).__init__(Geometry(randint(0, 100),
                                                    randint(0, 100),
                                                    randint(50, 100),
                                                    randint(50, 100),
                                                    1))

        self.tagged = False
        args = AtomList(map(self.atoms.intern, tags)).change_property_args()
        self.conn.core.ChangePropertyChecked(PropMode.Replace,
                                             self.window,
                                             self.atoms["_DIM_TAGS"],
                                             self.atoms["ATOM"],
                                             *args).check()

    @handler(PropertyNotifyEvent)
    def handle_property_notify(self, event):
        assert event.window == self.window
        if event.atom == self.atoms["_DIM_TAGS"]:
            self.tagged = (event.state == Property.NewValue)

class TestTagManager(WMTestCase):
    wm_class = TagManager

    def setUp(self):
        super(TestTagManager, self).setUp()
        self.tagsets = defaultdict(set)
        self.all_clients = []

    def eval(self, pexpr, show=True):
        if show:
            pexpr += ["_DIM_TAGSET_SHOW"]
        def intern(op):
            return self.atoms.intern(op, "UTF-8")
        args = AtomList(map(intern, pexpr)).change_property_args()
        self.conn.core.ChangePropertyChecked(PropMode.Replace,
                                             self.screen.root,
                                             self.atoms["_DIM_TAGSET_EXPRESSION"],
                                             self.atoms["ATOM"],
                                             *args).check()

    def make_client(self, tags):
        client = self.add_client(TaggedClient(tags))
        client.map()
        for tag in tags:
            self.tagsets[tag].add(client)
        return client

    def make_ready_test(self):
        return lambda: all(client.mapped and client.managed and client.tagged
                           for client in self.clients)

    def make_mapped_test(self, clients):
        return lambda: (all(client.mapped for client in clients) and
                        not any(client.mapped
                                for client in set(self.clients) - set(clients)))

    def test_tagsets(self):
        """Tagsets"""
        self.make_client(["a"])
        self.make_client(["b"])
        self.make_client(["c"])
        self.make_client(["a", "b"])
        self.make_client(["a", "c"])
        self.make_client(["b", "c"])
        self.make_client(["a", "b", "c"])
        self.loop(self.make_ready_test())

        self.eval(["a"])
        self.loop(self.make_mapped_test(self.tagsets["a"]))

        self.eval(["a", "b", "_DIM_TAGSET_UNION"])
        self.loop(self.make_mapped_test(self.tagsets["a"] | self.tagsets["b"]))

        self.eval(["b", "c", "_DIM_TAGSET_INTERSECTION"])
        self.loop(self.make_mapped_test(self.tagsets["b"] & self.tagsets["c"]))

        self.eval(["a", "c", "_DIM_TAGSET_DIFFERENCE"])
        self.loop(self.make_mapped_test(self.tagsets["a"] - self.tagsets["c"]))

        self.eval(["_DIM_EMPTY_TAGSET"])
        self.loop(self.make_mapped_test(set()))

        self.eval(["_DIM_EMPTY_TAGSET", "_DIM_TAGSET_COMPLEMENT"])
        self.loop(self.make_mapped_test(self.clients))

    def test_wild(self):
        """Wild tags"""
        self.make_client(["a"])
        self.make_client(["b"])
        self.make_client(["*"])
        self.loop(self.make_ready_test())

        wild = self.tagsets["*"]
        self.assertTrue(wild)

        self.eval(["a"])
        self.loop(self.make_mapped_test(self.tagsets["a"] | wild))

        self.eval(["b"])
        self.loop(self.make_mapped_test(self.tagsets["b"] | wild))

        self.eval(["∅"])
        self.loop(self.make_mapped_test(wild))

if __name__ == "__main__":
    import logging
    from tags import log

    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)

    unittest.main()
