#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

"""Request a tagset update."""

from optparse import OptionParser
from sys import exit, stdin

import xcb
from xcb.xproto import *

from tags import parse_tagset_spec, send_tagset_expression

if __name__ == "__main__":
    optparser = OptionParser("Usage: %prog [OPTIONS] TAGSET-SPEC")
    optparser.add_option("-d", "--display", dest="display",
                         help="the X server display name")
    (options, args) = optparser.parse_args()
    if len(args) == 0:
        exit(0)
    elif len(args) != 1:
        optparser.print_help()
        exit(1)
    spec = unicode(args[0], stdin.encoding)
    conn = xcb.connect(options.display)
    send_tagset_expression(conn, parse_tagset_spec(spec))
    conn.flush()
