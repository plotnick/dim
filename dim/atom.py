# -*- mode: Python; coding: utf-8 -*-

import xcb
from xcb.xproto import Atom

__all__ = ["AtomCache"]

def ensure_unicode(string, encoding, errors):
    return (string
            if isinstance(string, unicode)
            else unicode(string, encoding, errors))

class AtomCache(object):
    """A simple cache for X atoms and their names."""

    def __init__(self, conn, names=[], encoding="Latin-1", errors="strict"):
        assert isinstance(conn, xcb.Connection)
        self.conn = conn
        self.atoms = {}
        self.names = {}
        if names:
            self.prime_cache(names, encoding, errors)

    def prime_cache(self, names, encoding="Latin-1", errors="strict"):
        """Prime the atom cache with the given names."""
        names = [ensure_unicode(name, encoding, errors)
                 for name in names
                 if name is not None]
        cookies = [self.intern_atom(name, encoding, errors)
                   for name in names]
        for name, cookie in zip(names, cookies):
            atom = cookie.reply().atom
            self.atoms[name] = atom
            self.names[atom] = name

    def intern_atom(self, name, encoding="Latin-1", errors="strict"):
        """Intern the given name and return a cookie for the request.
        Does not wait for a reply."""
        buf = name.encode(encoding, errors)
        return self.conn.core.InternAtom(False, len(buf), buf)

    def __getitem__(self, name):
        return self.intern(name)

    def intern(self, name, encoding="Latin-1", errors="strict"):
        """Return the atom with the given name."""
        # Maybe it's one of the pre-defined atoms.
        if name is None:
            return 0
        elif isinstance(name, int):
            return name
        elif isinstance(name, str):
            try:
                return getattr(Atom, name)
            except AttributeError:
                pass

        # From now on we'll insist that the name be a Unicode string. Just
        # because X treats atoms as byte strings doesn't mean we have to.
        name = ensure_unicode(name, encoding, errors)

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
            buf = self.conn.core.GetAtomName(atom).reply().name.buf()
            name = unicode(buf, encoding, errors)
            self.atoms[name] = atom
            self.names[atom] = name
            return name
