#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

"""Generate a Python file containing X keysym definitions.

See the comment at the top of keysymdef.h for background information.

We generate four kinds of definitions from the C header file. The first is
mnemonic names: for each mnemonic macro definition XK_foo in keysymdef.h,
we generate a Python variable with the same name and code.

The second is a map from keysym codes to names, which we represent as a
Python dictionary named "_names". These names should be the same as the
mnemonics with the prefix "XK_" removed. In the case when more than one
mnemonic is defined for the same keysym, the one that occurs first in the
header file is used.

The third generated definition is a map from Unicode characters to keysym
codes, which we represent by a Python dictionary named "_keysyms".

The fourth is a map from legacy keysym codes to Unicode characters, which
we call "_legacy_codes". It is also a dictionary."""

from operator import itemgetter
import re

# Adapted from keysymdef.h comment.
mnemonic_patterns = map(lambda pattern: re.compile(pattern, re.VERBOSE),
    (r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    (?P<code>0x[0-9a-f]+)\s*
                    /\*\ U\+(?P<code_point>[0-9A-F]{4,6})\ .*\ \*/\s*$""",
     r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    (?P<code>0x[0-9a-f]+)\s*
                    # Don't bother assigning code points to deprecated keysyms.
                    /\*\(U\+[0-9A-F]{4,6}\ .*\)\*/\s*$""",
     r"""^\#define\ XK_(?P<name>[a-zA-Z_0-9]+)\s+
                    (?P<code>0x[0-9a-f]+)\s*
                    (?:/\*\s*.*\s*\*/)?\s*$"""))

def is_legacy_keysym(keysym):
    return 0x100 <= keysym <= 0x20ff

def is_unicode_keysym(keysym):
    return (keysym & 0xff000000) == 0x01000000

def make_keysym_def(input, output):
    if input.name:
        output.write("# Automatically generated from %s.\n\n" % input.name)

    # The following dictionaries are used to generate the corresponding
    # dictionaries in the output file, but they are not quite the same.
    # In particular, all of the keys and values here are strings. When the
    # generated file is interpreted, the mnemonics will be read as variable
    # references and so will become keysyms (i.e., integers).
    names = {} # mnemonic (keysym code) → name map
    keysyms = {} # Unicode character → mnemonic (keysym code) map
    legacy_codes = {} # legacy keysym mnemonic (code) → Unicode character

    # Since we're using mnemonics as keys for the names dictionary, we
    # need another way to detect keysym code collisions. We'll keep all
    # of the keysym codes we've seen so far in the following set. This set
    # is not serialized to the output file; it's for internal use only.
    keysyms_seen = set()

    for line in input:
        for pattern in mnemonic_patterns:
            match = pattern.match(line)
            if match:
                name = match.group("name")
                code = match.group("code")
                mnemonic = "XK_%s" % name
                keysym = int(code, 16)
                try:
                    code_point = int(match.group("code_point"), 16)
                except IndexError:
                    code_point = None
                break
        else:
            continue # skip this line of input

        output.write("%s = %s\n" % (mnemonic, code))

        if is_unicode_keysym(keysym):
            # For Unicode keysyms, the keysym code is authoritative.
            # These should agree with the code points in the comments,
            # but there are bugs: e.g.,
            #     XK_approxeq = 0x1002248  /* U+2245 ALMOST EQUAL TO */
            char = unichr(keysym & 0x00ffffff)
        elif code_point:
            # Use the code point from the mnemonic definition comment.
            char = unichr(code_point)
        else:
            char = None
        if char and char not in keysyms:
            keysyms[repr(char)] = mnemonic

        if keysym not in keysyms_seen:
            names[mnemonic] = repr(name)
            if char and is_legacy_keysym(keysym):
                legacy_codes[mnemonic] = repr(char)
            keysyms_seen.add(keysym)

    def pprint_dict(name, d):
        output.write("\f\n%s = {\n" % name)
        for key, value in sorted(d.items(), key=itemgetter(0)):
            output.write("    %s: %s,\n" % (key, value))
        output.write("}\n")

    pprint_dict("_names", names)
    pprint_dict("_keysyms", keysyms)
    pprint_dict("_legacy_codes", legacy_codes)

if __name__ == "__main__":
    import os
    import sys

    try:
        input_file, output_file = sys.argv[1:]
    except ValueError:
        print >> sys.stderr, \
            "Usage: %s INPUT-FILE OUTPUT-FILE" % os.path.basename(sys.argv[0])
        sys.exit(1)
    with open(input_file) as input:
        with open(output_file, "w") as output:
            make_keysym_def(input, output)
