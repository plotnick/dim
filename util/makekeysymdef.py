#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

"""Generate a Python file containing X keysym code definitions."""

from operator import itemgetter
import os
import re

# Adapted from keysymdef.h comment.
mnemonic_patterns = map(lambda pattern: re.compile(pattern, re.VERBOSE),
    (r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    0x(?P<code>[0-9a-f]+)\s*
                    /\*\ U\+(?P<code_point>[0-9A-F]{4,6})\ .*\ \*/\s*$""",
     r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    0x(?P<code>[0-9a-f]+)\s*
                    # Don't bother assigning code points to deprecated keysyms.
                    /\*\(U\+[0-9A-F]{4,6}\ .*\)\*/\s*$""",
     r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    0x(?P<code>[0-9a-f]+)\s*
                    (?:/\*\s*.*\s*\*/)?\s*$"""))

def is_legacy_keysym(keysym):
    return 0x100 <= keysym <= 0x20ff

def is_unicode_keysym(keysym):
    return (keysym & 0xff000000) == 0x01000000

def keysymdef(input, output):
    if input.name:
        output.write("# Automatically generated from %s.\n\n" % input.name)

    names = {} # keysym code → name map
    legacy_codes = {} # legacy keysym code → Unicode character
    keysyms = {} # Unicode character → keysym code map

    for line in input:
        for pattern in mnemonic_patterns:
            m = pattern.match(line)
            if m:
                name = m.group("name")
                code = int(m.group("code"), 16)
                try:
                    code_point = int(m.group("code_point"), 16)
                except IndexError:
                    code_point = None
                break
        else:
            continue # skip this line of input

        output.write("XK_%s = 0x%x\n" % (name, code))
        names["0x%x" % code] = repr(name)

        if is_unicode_keysym(code):
            # For Unicode keysyms, the keysym code is authoritative.
            # These should agree with the code points in the comments,
            # but there are bugs: e.g.,
            #     XK_approxeq = 0x1002248  /* U+2245 ALMOST EQUAL TO */
            keysyms[repr(unichr(code & 0x00ffffff))] = "XK_%s" % name
        elif code_point:
            char = unichr(code_point)
            if is_legacy_keysym(code):
                legacy_codes["0x%x" % code] = repr(char)
            keysyms[repr(char)] = "XK_%s" % name

    def pprint_dict(name, d):
        output.write("\f\n%s = {\n" % name)
        for key, value in sorted(d.items(), key=itemgetter(0)):
            output.write("    %s: %s,\n" % (key, value))
        output.write("}\n")

    pprint_dict("_keysyms", keysyms)
    pprint_dict("_names", names)
    pprint_dict("_legacy_codes", legacy_codes)

if __name__ == "__main__":
    import sys

    try:
        input_file, output_file = sys.argv[1:]
    except ValueError:
        print >> sys.stderr, \
            "Usage: %s INPUT-FILE OUTPUT-FILE" % os.path.basename(sys.argv[0])
        sys.exit(1)
    with open(input_file) as input:
        with open(output_file, "w") as output:
            keysymdef(input, output)
