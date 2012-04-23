# -*- mode: Python; coding: utf-8 -*-

from keysymdef import *
from keysymdef import _names, _keysyms, _legacy_codes

NoSymbol = 0

def is_latin1_key(keysym):
    return keysym < 0x100

def is_unicode_key(keysym):
    return (keysym & 0xff000000) == 0x01000000

def is_legacy_key(keysym):
    return 0x100 <= keysym <= 0x20ff

def is_keypad_key(keysym):
    return XK_KP_Space <= keysym <= XK_KP_Equal

def is_private_keypad_key(keysym):
    return 0x11000000 <= keysym <= 0x1100ffff

def is_modifier_key(keysym):
    return (XK_Shift_L <= keysym <= XK_Hyper_R or
            keysym == XK_Mode_switch or
            keysym == XK_Num_Lock)

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
    return (unichr(keysym) if is_latin1_key(keysym) else
            unichr(keysym & 0x00ffffff) if is_unicode_key(keysym) else
            _legacy_codes.get(keysym, ""))

def upper(keysym):
    """Return the corresponding uppercase keysym."""
    return string_to_keysym(keysym_to_string(keysym).upper()) or keysym

def lower(keysym):
    """Return the corresponding lowercase keysym."""
    return string_to_keysym(keysym_to_string(keysym).lower()) or keysym
