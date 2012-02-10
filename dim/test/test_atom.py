# -*- mode: Python; coding: utf-8 -*-

import unittest

import xcb
from xcb.xproto import *

from dim.atom import AtomCache

class TestAtomCache(unittest.TestCase):
    def setUp(self):
        self.conn = xcb.connect()
        self.atoms = AtomCache(self.conn)

    def tearDown(self):
        self.conn.disconnect()

    def assertAtom(self, x):
        self.assertTrue(isinstance(x, int) and 0 <= x < 0x1fffffff)

    def test_prime_cache(self):
        names = set(["ATOM", "BITMAP", "CARDINAL", "UTF8_STRING"])
        self.atoms.prime_cache(names)
        for name in names:
            self.assertAtom(self.atoms[name])
        self.assertEqual(set(self.atoms.atoms.keys()), names)
        self.assertEqual(set(self.atoms.names.values()), names)

    def test_null_atom(self):
        self.atoms.prime_cache([None]) # should not raise an exception
        self.assertEqual(self.atoms[None], 0)
        self.assertEqual(self.atoms.name(0), None)

    def test_predefined_atoms(self):
        for name in dir(Atom):
            if not name.startswith("_"):
                self.assertEqual(self.atoms[name], getattr(Atom, name))
        # Pre-defined atoms don't get cached using normal lookup.
        self.assertFalse(self.atoms.atoms)

    def test_atoms(self):
        # These atoms are not in the pre-defined Atom class, and so must
        # be requested and cached.
        names = set(["_NET_WM_NAME", "_NET_WM_ICON_NAME", "UTF8_STRING"])
        for name in names:
            atom = self.atoms[name]
            self.assertAtom(atom)
            self.assertTrue(name in self.atoms.atoms)
        self.assertEqual(set(self.atoms.atoms.keys()), names)

    def test_names(self):
        # Names are always requested from the server and cached.
        names = set(["ATOM", "BITMAP", "CARDINAL", "UTF8_STRING"])
        for name in names:
            atom = self.atoms[name]
            self.assertEqual(self.atoms.name(atom), name)
        self.assertEqual(set(self.atoms.names.values()), names)

    def test_encoding(self):
        foo = self.atoms[u"foö"]
        self.assertAtom(foo)
        self.assertEqual(foo, self.atoms[u"foö".encode("Latin-1")])
        self.assertEqual(foo, self.atoms.intern(u"foö", encoding="UTF-8"))
        self.assertEqual(self.atoms.name(foo), u"foö")

if __name__ == "__main__":
    unittest.main()
