#!/usr/bin/env python

"""Generate a Python file containing X keysym code definitions."""

import os
import re

# Adapted from keysymdef.h comment.
mnemonic_patterns = map(re.compile,
    (r"^#define (XK_[a-zA-Z_0-9]+)\s+(0x[0-9a-f]+)\s*/\* U+([0-9A-F]{4,6}) (.*) \*/\s*$",
     r"^#define (XK_[a-zA-Z_0-9]+)\s+(0x[0-9a-f]+)\s*/\*\(U+([0-9A-F]{4,6}) (.*)\)\*/\s*$",
     r"^#define (XK_[a-zA-Z_0-9]+)\s+(0x[0-9a-f]+)\s*(/\*\s*(.*)\s*\*/)?\s*$"))

def make_keysym(input, output):
    if input.name:
        output.write("# Automatically generated from %s.\n\n" % input.name)
    for line in input:
        for pattern in mnemonic_patterns:
            m = pattern.match(line)
            if m:
                name, value = m.group(1), m.group(2)
                break
        else:
            continue # skip this line of input
        output.write("%s = %s\n" % (name, value))

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
            make_keysym(input, output)
