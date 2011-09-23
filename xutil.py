import operator
from xcb.xproto import *

MAX_CARD32 = 2**32 - 1

class AtomCache(object):
    """A simple cache for X atoms."""

    def __init__(self, conn, names=[]):
        self.conn = conn
        self.atoms = {}
        if names:
            self.prime_cache(names)

    def prime_cache(self, names):
        cookies = [self.conn.core.InternAtom(False, len(name), name)
                   for name in names]
        for name, cookie in zip(names, cookies):
            self.atoms[name] = cookie.reply().atom

    def __getitem__(self, name):
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

def select_values(value_mask, values):
    """Create a value-list from the supplied possible values according to the
    bits in the given value-mask."""
    return [values[i] for i in range(len(values)) if value_mask & (1 << i)]

def power_of_2(x):
    """Check whether x is a power of 2.

    >>> power_of_2(0)
    False
    >>> power_of_2(1)
    True
    >>> power_of_2(2)
    True
    >>> power_of_2(3)
    False
    >>> power_of_2(4)
    True
    """
    return isinstance(x, int) and x > 0 and x & (x - 1) == 0

def popcount(x):
    """Count the number of 1 bits in the binary representation of x."""
    return bin(x).count("1")

def value_list(flag_class, **kwargs):
    """Construct and return a value-mask and value-list from the supplied
    keyword arguments. The flag_class should be an object with attributes
    that define the flags for the possible values.

    >>> value_list(ConfigWindow, x="X", y="Y", stack_mode="Above")
    (67, ['X', 'Y', 'Above'])
    >>> value_list(ConfigWindow, x="X", y="Y", z="Z")
    Traceback (most recent call last):
      ...
    KeyError: 'z'
    >>> value_list(type('Foo', (object,), dict(a=1, b=1)), a="a", b="b")
    Traceback (most recent call last):
      ...
    AssertionError: Duplicate flags in Foo
    """
    flags = {}
    for attr in dir(flag_class):
        if not attr.startswith("_"):
            value = getattr(flag_class, attr, None)
            if power_of_2(value):
                flags[attr.lower()] = value
    assert len(set(flags.values())) == len(flags), \
        "Duplicate flags in %s" % (flag_class.__name__ \
                                       if hasattr(flag_class, "__name__")
                                       else flag_class)
    
    values = [(value, flags[name.replace("_", "").lower()])
              for name, value in kwargs.items()]
    return (reduce(operator.or_, map(operator.itemgetter(1), values), 0),
            map(operator.itemgetter(0),
                sorted(values, key=operator.itemgetter(1))))

if __name__ == "__main__":
    import doctest
    doctest.testmod()
