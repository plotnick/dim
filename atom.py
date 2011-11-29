# -*- mode: Python; coding: utf-8 -*-

import xcb
from xcb.xproto import Atom

__all__ = ["AtomCache"]

class AtomCache(object):
    """A simple cache for X atoms."""

    def __init__(self, conn, names=[], encoding="Latin-1", errors="strict"):
        assert isinstance(conn, xcb.Connection)
        self.conn = conn
        self.atoms = {} # atom cache
        self.names = {} # name cache
        if names:
            self.prime_cache(names, encoding, errors)

    def intern_atom(self, name, encoding="Latin-1", errors="strict"):
        """Intern the given name and return a cookie for the request.
        Does not wait for a reply."""
        bytes = name.encode(encoding, errors)
        return self.conn.core.InternAtom(False, len(bytes), bytes)

    def prime_cache(self, names, encoding="Latin-1", errors="strict"):
        """Prime the atom cache with the given names."""
        names = [(name if isinstance(name, unicode) else
                  unicode(name, encoding, errors))
                 for name in names
                 if name is not None]
        cookies = [self.intern_atom(name, encoding, errors)
                   for name in names]
        for name, cookie in zip(names, cookies):
            atom = cookie.reply().atom
            self.atoms[name] = atom
            self.names[atom] = name

    def __getitem__(self, name):
        return self.intern(name)

    def intern(self, name, encoding="Latin-1", errors="strict"):
        """Return the atom with the given name."""
        # Maybe it's one of the pre-defined atoms.
        if name is None:
            return 0
        elif isinstance(name, str):
            try:
                return getattr(Atom, name)
            except AttributeError:
                pass

        # From now on we'll insist that the name be a Unicode string. Just
        # because X treats atoms as byte strings doesn't mean we have to.
        name = (name if isinstance(name, unicode) else
                unicode(name, encoding, errors))

        # Check the cache.
        try:
            return self.atoms[name]
        except KeyError:
            pass

        # Intern & cache the atom.
        atom = self.intern_atom(name, encoding, errors).reply().atom
        self.atoms[name] = atom
        self.names[atom] = name
        return atom

    def name(self, atom, encoding="Latin-1", errors="strict"):
        """Return the name of the given atom as a Unicode string."""
        if atom == 0:
            return None
        try:
            return self.names[atom]
        except KeyError:
            name = unicode(self.conn.core.GetAtomName(atom).reply().name.buf(),
                           encoding, errors)
            self.atoms[name] = atom
            self.names[atom] = name
            return name
