#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

"""Distutils-based setup script for Dim.

Dim is a pure-Python program, but it requires a few auto-generated
modules (definitions for the standard X cursor font and keysyms).
Since Distutils has no built-in support for auto-generated Python
modules, we'll add a custom command ("generate_py") and associated
infrastructure (subclasses of "Distribution" and "build" that are
aware of the new command and its options).

The actual generation routines are in their own modules, which export
a simple functional interface that we use here."""

import os

from distutils.cmd import Command
from distutils.command.build import build as _build
from distutils.core import Distribution as _Distribution, setup
from distutils.dep_util import newer
from distutils.errors import *
from distutils import log

from dim.util.makecursorfont import make_cursor_font
from dim.util.makekeysymdef import make_keysym_def

class Distribution(_Distribution):
    # Unknown setup options are ignored by default (with a warning),
    # but defining an attribute in the distribution class is sufficient
    # to declare a new option as valid.
    autogen_modules = None
    autogen_source_dirs = None

    def has_autogen_modules(self):
        return self.autogen_modules and len(self.autogen_modules) > 0

class generate_py(Command):
    description = "auto-generate Python modules"
    user_options = [("source-dirs=", "S",
                     "list of directories to search for source files"
                     " (separated by '%s')" % os.pathsep),
                    ("force", "f", "force auto-(re)generation")]
    boolean_options = ["force"]

    def initialize_options(self):
        self.source_dirs = None
        self.force = None

    def finalize_options(self):
        self.set_undefined_options("build", ("force", "force"))
        self.autogen_modules = self.distribution.autogen_modules
        if self.source_dirs is None:
            self.source_dirs = self.distribution.autogen_source_dirs or []
        if isinstance(self.source_dirs, basestring):
            self.source_dirs = self.source_dirs.split(os.pathsep)

    def run(self):
        build_py = self.get_finalized_command("build_py")
        for source, module, generator in self.autogen_modules:
            path = module.split(".")
            package = ".".join(path[0:-1])
            package_dir = build_py.get_package_dir(package)
            module_base = path[-1]
            module_filename = os.path.join(package_dir, module_base + ".py")

            for source_dir in self.source_dirs:
                source_filename = os.path.join(source_dir, source)
                if os.path.exists(source_filename):
                    break
            else:
                raise DistutilsFileError("can't find source file '%s'" % source)

            if self.force or newer(source_filename, module_filename):
                log.info("generating %s from %s" % (module_filename,
                                                    source_filename))
                if not self.dry_run:
                    with open(source_filename, "r") as input_file:
                        with open(module_filename, "w") as output_file:
                            generator(input_file, output_file)

class build(_build):
    def has_autogen_modules(self):
        return self.distribution.has_autogen_modules()

    # Sub-commands are run in order, and auto-generation must precede the
    # other build commands.
    sub_commands = [("generate_py", has_autogen_modules)] + _build.sub_commands

setup(name="dim",
      version="0.1",
      description="A window manager for the X window system",
      author="Alex Plotnick",
      author_email="shrike@netaxs.com",
      scripts=["bin/dim"],
      packages=["dim", "dim.test", "dim.util"],
      autogen_modules=[("cursorfont.h", "dim.cursorfont", make_cursor_font),
                       ("keysymdef.h", "dim.keysymdef", make_keysym_def)],
      autogen_source_dirs=["/usr/local/include/X11", "/usr/include/X11"],
      cmdclass={"build": build, "generate_py": generate_py},
      distclass=Distribution)
