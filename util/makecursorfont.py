#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

"""Generate a Python file containing cursor font names."""

import re

cursor_pattern = re.compile(r"""^#define (XC_[a-zA-Z_0-9]+)\s+([0-9]+)$""")

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
            if input.name:
                output.write("# Automatically generated from %s.\n\n" % \
                                 input.name)

            for line in input:
                match = cursor_pattern.match(line)
                if match:
                    name = match.group(1)
                    value = match.group(2)
                    output.write("%s = %s\n" % (name, value))
