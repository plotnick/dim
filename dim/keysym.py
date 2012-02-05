# -*- mode: Python; coding: utf-8 -*-

from keysymdef import *
from keysymdef import _names, _keysyms, _legacy_codes

NoSymbol = 0

def is_latin1(keysym):
    return keysym < 0x100

def is_unicode(keysym):
    return (keysym & 0xff000000) == 0x01000000

def is_legacy(keysym):
    return 0x100 <= keysym <= 0x20ff

def is_keypad(keysym):
    return 0xff80 <= keysym <= 0xffbd or 0x11000000 <= keysym <= 0x1100ffff

def keysym_name(keysym):
    """Return the name of the given keysym."""
    return _names.get(keysym, None)

def string_to_keysym(string):
    """Return the keysym corresponding to the given string."""
    return _keysyms.get(string, NoSymbol)

def keysym_to_string(keysym):
    """Return the string denoted by the given keysym, or the empty string if
    no such string exists.

    Note that this is different than the Xlib function XKeysymToString, which
    is equivalent to our keysym_name function."""
    if is_latin1(keysym):
        return unichr(keysym)
    elif is_unicode(keysym):
        return unichr(keysym & 0x00ffffff)
    else:
        try:
            return _legacy_codes[keysym]
        except KeyError:
            return ""

def upper(keysym):
    """Return the corresponding uppercase keysym."""
    return string_to_keysym(keysym_to_string(keysym).upper()) or keysym

def lower(keysym):
    """Return the corresponding lowercase keysym."""
    return string_to_keysym(keysym_to_string(keysym).lower()) or keysym
