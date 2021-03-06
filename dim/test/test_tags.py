# -*- mode: Python; coding: utf-8 -*-

from __future__ import unicode_literals

from collections import defaultdict
from random import randint
from math import sqrt
import unittest

from xcb.xproto import *

from dim.event import *
from dim.geometry import *
from dim.properties import AtomList
from dim.tags import (TagMachineError, TagMachine, TagManager, SpecSyntaxError,
                      tokenize, parse_tagset_spec, send_tagset_expr)

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

class IntTagMachine(TagMachine):
    """Just like a regular tag machine, but with special support for integers
    as clients."""

    def current_set(self):
        # We'll consider even numbers to be "normal" for no particular reason.
        self.push(set(client
                      for client in self.clients.values()
                      if client % 2 == 0))

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
        self.opcodes = {"{": "begin",
                        "}": "end",
                        "'": "quote",
                        "=": "assign",
                        "∪": "union",
                        "∩": "intersection",
                        "∖": "difference",
                        "∁": "complement",
                        "*": "all_tags",
                        ".": "current_set",
                        "∅": "empty_set"}
        self.default_tagset_values = ["de", "fault"]
        self.tvm = IntTagMachine(self.clients, self.tagsets, self.opcodes,
                                 default_tagset=self.default_tagset)

    def assertStackEmpty(self, tvm):
        self.assertRaises(IndexError, tvm.pop)

    def assertStackEqual(self, tvm, *values):
        for x in values:
            self.assertEqual(tvm.pop(), x)
        self.assertStackEmpty(tvm)

    def default_tagset(self, tag):
        if tag == "default":
            return self.default_tagset_values
        return []

    def test_stack_ops(self):
        """Tag machine stack operations"""
        x, y = object(), object()
        self.tvm.push(x)
        self.tvm.push(y)
        self.assertStackEqual(self.tvm, y, x)

        self.tvm.push(x)
        self.tvm.push(y)
        self.tvm.swap()
        self.tvm.dup()
        self.assertStackEqual(self.tvm, x, x, y)

        self.tvm.push(x)
        self.tvm.push(y)
        self.tvm.clear()
        self.assertStackEmpty(self.tvm)
        self.tvm.clear()
        self.assertStackEmpty(self.tvm)

    def test_tags(self):
        """Tag machine tags"""
        self.tvm.run(["square"])
        self.assertStackEqual(self.tvm, self.tagsets["square"])

        self.tvm.all_tags()
        self.assertStackEqual(self.tvm, self.all_clients - self.tagless)

        self.tvm.all_clients()
        self.assertStackEqual(self.tvm, self.all_clients)

        self.tvm.current_set()
        self.assertStackEqual(self.tvm, self.tagsets["even"])

    def test_default_tags(self):
        """Tag machine default tagset support"""
        self.tvm.run(["foo"])
        self.assertStackEqual(self.tvm, set([]))

        self.tvm.run(["default"])
        self.assertStackEqual(self.tvm, set(self.default_tagset_values))

    def test_set_ops(self):
        """Tag machine set operations"""
        self.tvm.run(["even", "prime", "∩"])
        self.assertStackEqual(self.tvm, set([2]))

        self.tvm.run(["even", "odd", "∪", "prime", "∩"])
        self.assertStackEqual(self.tvm, self.tagsets["prime"])

        self.tvm.run(["big", "prime", "∖"])
        self.assertStackEqual(self.tvm,
                         self.tagsets["big"] - self.tagsets["prime"])

        self.tvm.run(["even", "∁"])
        self.assertStackEqual(self.tvm, self.tagsets["odd"] | self.tagless)

        self.tvm.run(["square", "∅", "∩"])
        self.assertStackEqual(self.tvm, set())

        self.tvm.run(["∅", "∁"])
        self.assertStackEqual(self.tvm, self.all_clients)

    def test_list(self):
        """Tag machine list support"""
        self.assertRaises(StopIteration, lambda: self.tvm.run(["{"]))
        self.assertRaises(TagMachineError, lambda: self.tvm.run(["}"]))

        x, y, z, w = object(), object(), object(), object()
        self.tvm.run(["{", x, "{", y, z, "}", w, "}"])
        self.assertStackEqual(self.tvm, [x, [y, z], w])

    def test_quote(self):
        """Tag machine quote instruction"""
        self.assertRaises(StopIteration, lambda: self.tvm.run(["'"]))

        x = object()
        self.tvm.run(["'", x])
        self.assertStackEqual(self.tvm, x)

    def test_assign(self):
        """Tag machine assignment"""
        self.assertRaises(IndexError, lambda: self.tvm.run(["="]))
        self.assertRaises(IndexError, lambda: self.tvm.run(["'", "x", "="]))

        # Tagset assignment
        big_even = self.tagsets["big"] & self.tagsets["even"]
        self.tvm.run(["'", "big-even", "big", "even", "∩", "="])
        self.assertStackEqual(self.tvm, big_even)
        self.assertEqual(self.tagsets["big-even"], big_even)

        # Expression (alias) assignment
        big_odd = self.tagsets["big"] & self.tagsets["odd"]
        self.tvm.run(["'", "big-odd", "{", "big", "odd", "∩", "}", "="])
        self.assertStackEqual(self.tvm, big_odd)
        self.assertFalse("big-odd" in self.tagsets)
        self.tvm.run(["big-odd"])
        self.assertStackEqual(self.tvm, big_odd)

class TestTokenizer(unittest.TestCase):
    def test_tag(self):
        """Tokenize tags"""
        self.assertEqual(list(tokenize("foo-bar báz quüx")),
                         ["foo-bar", "báz", "quüx"])

    def test_tokenize_spec(self):
        """Tokenize tagset specs"""
        self.assertEqual(list(tokenize(r"~(a | b) \ c")),
                         ["∁", "(", "a", "∪", "b", ")", "∖", "c"])

        self.assertEqual(list(tokenize("a ∩ b ∪ ∁ c")),
                         ["a", "∩", "b", "∪", "∁", "c"])

    def test_invalid_token(self):
        """Invalid token"""
        tokens = tokenize("a + b")
        self.assertEqual(tokens.next(), "a")
        self.assertRaises(SpecSyntaxError, tokens.next)

    def test_unbalanced_parens(self):
        """Unbalanced parenthesis"""
        tokens = tokenize("((a)")
        self.assertEqual(tokens.next(), "(")
        self.assertEqual(tokens.next(), "(")
        self.assertEqual(tokens.next(), "a")
        self.assertEqual(tokens.next(), ")")
        self.assertRaises(SpecSyntaxError, tokens.next)

class TestParser(unittest.TestCase):
    def test_parse_spec(self):
        """Parse tagset specification"""
        self.assertEqual(parse_tagset_spec(r"~(a | b) \ c & ~d"),
                         ["a", "b", "∪", "∁", "c", "d", "∁", "∩", "∖"])

    def test_syntax_errors(self):
        """Tagset specification syntax errors"""
        self.assertRaises(SpecSyntaxError, lambda: parse_tagset_spec("| x"))
        self.assertRaises(SpecSyntaxError, lambda: parse_tagset_spec("(x)y"))
        self.assertRaises(SpecSyntaxError, lambda: parse_tagset_spec("x~y"))
        self.assertRaises(SpecSyntaxError, lambda: parse_tagset_spec("x&|y"))

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

    def send_tagset_expr(self, expr):
        send_tagset_expr(self.conn, expr, show=True, atoms=self.atoms)
        self.conn.flush()

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

        self.send_tagset_expr(["a"])
        self.loop(self.make_mapped_test(self.tagsets["a"]))

        self.send_tagset_expr(["a", "b", "_DIM_TAGSET_UNION"])
        self.loop(self.make_mapped_test(self.tagsets["a"] | self.tagsets["b"]))

        self.send_tagset_expr(["b", "c", "_DIM_TAGSET_INTERSECTION"])
        self.loop(self.make_mapped_test(self.tagsets["b"] & self.tagsets["c"]))

        self.send_tagset_expr(["a", "c", "_DIM_TAGSET_DIFFERENCE"])
        self.loop(self.make_mapped_test(self.tagsets["a"] - self.tagsets["c"]))

        self.send_tagset_expr(["_DIM_EMPTY_SET"])
        self.loop(self.make_mapped_test(set()))

        self.send_tagset_expr(["_DIM_EMPTY_SET", "_DIM_TAGSET_COMPLEMENT"])
        self.loop(self.make_mapped_test(self.clients))

    def test_wild(self):
        """Wild tags"""
        self.make_client(["a"])
        self.make_client(["b"])
        self.make_client(["*"])
        self.loop(self.make_ready_test())

        wild = self.tagsets["*"]
        self.assertTrue(wild)

        self.send_tagset_expr(["a"])
        self.loop(self.make_mapped_test(self.tagsets["a"] | wild))

        self.send_tagset_expr(["b"])
        self.loop(self.make_mapped_test(self.tagsets["b"] | wild))

        self.send_tagset_expr(["∅"])
        self.loop(self.make_mapped_test(wild))

if __name__ == "__main__":
    unittest.main()
