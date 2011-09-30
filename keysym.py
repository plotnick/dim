# -*- mode: Python; coding: utf-8 -*-

from keysymdef import *
from keysymdef import _keysyms, _names, _legacy_codes

NoSymbol = 0

def is_latin1(keysym):
    return keysym < 0x100

def is_unicode(keysym):
    return (keysym & 0xff000000) == 0x01000000

def is_legacy(keysym):
    return 0x100 <= keysym <= 0x20ff

def keysym_name(keysym):
    """Return the name of the given keysym."""
    return _names[keysym]

def string_to_keysym(string):
    """Return the keysym corresponding to the given string."""
    return _keysyms[string]

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

def _convert_keysym(keysym, convert):
    if is_latin1(keysym):
        # Some characters have upper- or lower-case variants that fall
        # outside the Latin-1 range. These generally don't have keysym
        # definitions, so we have to be careful.
        converted = ord(convert(unichr(keysym)))
        return converted if is_latin1(converted) else keysym
    elif is_unicode(keysym):
        # We'll assume that Unicode keysyms have the proper case variants.
        return ord(convert(unichr(keysym & 0x00ffffff))) | 0x01000000
    elif is_legacy(keysym):
        # Some of the legacy keysyms also don't have corresponding
        # upper- or lower-case variants, even though their Unicode
        # equivalents do.
        try:
            return string_to_keysym(convert(_legacy_codes[keysym]))
        except KeyError:
            return keysym
    else:
        return keysym

def upper(keysym, convert=lambda c: c.upper()):
    """Return the corresponding uppercase keysym."""
    return _convert_keysym(keysym, convert)

def lower(keysym, convert=lambda c: c.lower()):
    """Return the corresponding lowercase keysym."""
    return _convert_keysym(keysym, convert)
