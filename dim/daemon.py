# -*- mode: Python; coding: utf-8 -*-

from os import _exit, chdir, close, dup2, fork, open, setsid, O_RDWR
from signal import signal, SIGHUP, SIG_IGN
import sys

__all__ = ["daemon"]

def daemon(nochdir=False, noclose=False):
    """Detach from the controlling terminal and run in the background.

    Unless the argument nochdir is true, changes the current working directory
    to the root (/).

    Unless the argument noclose is true, redirects standard input, standard
    output, and standard error to /dev/null."""
    # A SIGHUP may be signaled when the parent exits.
    old_handler = signal(SIGHUP, SIG_IGN)
    try:
        if fork():
            _exit(0)
        setsid()
    finally:
        signal(SIGHUP, old_handler)

    if not nochdir:
        chdir("/")

    if not noclose:
        fd = open("/dev/null", O_RDWR)
        if fd == -1:
            return False
        try:
            dup2(fd, sys.stdin.fileno())
            dup2(fd, sys.stdout.fileno())
            dup2(fd, sys.stderr.fileno())
        finally:
            if fd > 2:
                close(fd)

    return True
