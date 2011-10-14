# -*- mode: Python; coding: utf-8 -*-

import xcb
from xcb.xproto import *

__all__ = ["AtomCache"]

class AtomCache(object):
    """A simple cache for X atoms."""

    def __init__(self, conn, names=[]):
        assert isinstance(conn, xcb.Connection)
        self.conn = conn
        self.atoms = {}
        self.names = {}
        if names:
            self.prime_cache(names)

    def prime_cache(self, names):
        cookies = [self.conn.core.InternAtom(False, len(name), name)
                   for name in names]
        for name, cookie in zip(names, cookies):
            atom = cookie.reply().atom
            self.atoms[name] = atom
            self.names[atom] = name

    def __getitem__(self, name):
        """Return the atom with the given name."""
        try:
            # Is it in the cache?
            return self.atoms[name]
        except KeyError:
            pass
        try:
            # Is it one of the pre-defined atoms?
            return getattr(Atom, name)
        except AttributeError:
            pass
        # Request the atom from the server and cache it.
        atom = self.conn.core.InternAtom(False, len(name), name).reply().atom
        self.atoms[name] = atom
        return atom

    def name(self, atom):
        """Return the name of the given atom."""
        try:
            return self.names[atom]
        except KeyError:
            name = str(self.conn.core.GetAtomName(atom).reply().name.buf())
            self.names[atom] = name
            return name
