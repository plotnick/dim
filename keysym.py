# -*- mode: Python; coding: utf-8 -*-

from keysymdef import *
from keysymdef import _keysyms, _names

def string_to_keysym(string):
    """Return the keysym corresponding to the given string."""
    return _keysyms[string]

def keysym_to_string(keysym):
    """Return the name of the given keysym."""
    return _names[keysym]
