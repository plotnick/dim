#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

"""Generate a Python file containing X keysym code definitions."""

from operator import itemgetter
import os
import re

# Adapted from keysymdef.h comment.
mnemonic_patterns = map(lambda pattern: re.compile(pattern, re.VERBOSE),
    (r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    (?P<code>0x[0-9a-f]+)\s*
                    /\*\ U\+(?P<code_point>[0-9A-F]{4,6})\ .*\ \*/\s*$""",
     r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    (?P<code>0x[0-9a-f]+)\s*
                    # We don't bother assigning code points to legacy keysyms.
                    /\*\(U\+[0-9A-F]{4,6}\ .*\)\*/\s*$""",
     r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    (?P<code>0x[0-9a-f]+)\s*
                    (?:/\*\s*.*\s*\*/)?\s*$"""))

def keysymdef(input, output):
    if input.name:
        output.write("# Automatically generated from %s.\n\n" % input.name)

    keysyms = {} # Unicode character → keysym code map
    names = {} # keysym code → name map
    for line in input:
        for pattern in mnemonic_patterns:
            m = pattern.match(line)
            if m:
                break
        else:
            continue # skip this line of input

        output.write("XK_%s = %s\n" % (m.group("name"), m.group("code")))
        names[m.group("code")] = repr(m.group("name"))
        try:
            keysyms[repr(unichr(int(m.group("code_point"), 16)))] = \
                "XK_%s" % m.group("name")
        except IndexError:
            pass

    def pprint_dict(name, d):
        output.write("\f\n%s = {\n" % name)
        for key, value in sorted(d.items(), key=itemgetter(0)):
            output.write("    %s: %s,\n" % (key, value))
        output.write("}\n")

    pprint_dict("_keysyms", keysyms)
    pprint_dict("_names", names)

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
