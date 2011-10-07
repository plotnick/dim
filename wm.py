#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

if __name__ == "__main__":
    from optparse import OptionParser
    import logging
    import sys
    import xcb

    from stacking import StackingWindowManager

    optparser = OptionParser("Usage: %prog [OPTIONS]")
    optparser.add_option("-D", "--debug", action="store_true", dest="debug",
                         help="show debugging messages")
    optparser.add_option("-V", "--verbose", action="store_true", dest="verbose",
                         help="be prolix, loquacious, and multiloquent")
    optparser.add_option("-v", "--version", action="store_true", dest="version",
                         help="output version information and exit")
    optparser.add_option("-d", "--display", dest="display",
                         help="the X server display name")
    (options, args) = optparser.parse_args()
    if options.version:
        print "Python Window Manager version 0.0"
        sys.exit(0)
    logging.basicConfig(level=logging.DEBUG if options.debug else \
                              logging.INFO if options.verbose else \
                              logging.WARNING,
                        format="%(levelname)s: %(message)s")

    wm = StackingWindowManager(xcb.connect(options.display))
    try:
        wm.event_loop()
    except KeyboardInterrupt:
        pass