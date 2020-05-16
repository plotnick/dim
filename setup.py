#!/usr/bin/env python2
# -*- mode: Python; coding: utf-8 -*-

"""Distutils-based setup script for Dim.

Dim is a pure-Python program, but it requires a few auto-generated
modules (definitions for the standard X cursor font and keysyms).
Since Distutils has no built-in support for auto-generated Python
modules, we'll add a custom command ("generate_py") and associated
infrastructure (subclasses of "Distribution" and "build" that are
aware of the new command and its options). The actual generation
routines are in their own modules, which export a simple functional
interface that we use here.

We also add a new "test" command, which executes the test suite.
The test suite must be run on a display that does not already have
a window manager running; a nesting X server such as Xephyr or Xnest
may be useful here."""

from contextlib import contextmanager
from glob import glob
import os

from distutils.cmd import Command
from distutils.command.build import build as _build
from distutils.core import Distribution as _Distribution, setup
from distutils.dep_util import newer
from distutils.errors import *
from distutils import log

from unittest import TestLoader, TextTestRunner

from dim.util.makecursorfont import make_cursor_font
from dim.util.makekeysymdef import make_keysym_def

class AutogenDistribution(_Distribution):
    # Declare options for auto-generation command.
    autogen_modules = None
    autogen_source_dirs = None

    def has_autogen_modules(self):
        return self.autogen_modules and len(self.autogen_modules) > 0

class AutogenCommand(Command):
    def has_autogen_modules(self):
        return self.distribution.has_autogen_modules()

    sub_commands = [("generate_py", has_autogen_modules)]

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

class build(_build, AutogenCommand):
    # Sub-commands are run in order, and auto-generation must precede the
    # other build commands.
    sub_commands = AutogenCommand.sub_commands + _build.sub_commands

class TestDistribution(_Distribution):
    # Declare options for test command.
    test_packages = None
    test_modules = None

@contextmanager
def display(display_name):
    """Execute a block with the DISPLAY environment variable rebound."""
    original_display = os.environ.get("DISPLAY")
    if display_name:
        os.environ["DISPLAY"] = display_name
    try:
        yield
    finally:
        if original_display:
            os.environ["DISPLAY"] = original_display
        elif display_name:
            del os.environ["DISPLAY"]

class test(AutogenCommand):
    description = "execute the test suite"
    user_options = [("display=", "d", "the X server to contact")]

    def initialize_options(self):
        self.display = None

    def finalize_options(self):
        self.test_packages = self.distribution.test_packages or []
        self.test_modules = self.distribution.test_modules or []

    def run(self):
        for cmd_name in self.get_sub_commands():
            self.run_command(cmd_name)

        build_py = self.get_finalized_command("build_py")
        test_names = self.test_modules
        for package in self.test_packages:
            package_dir = build_py.get_package_dir(package)
            for pkg, module, f in build_py.find_package_modules(package,
                                                                package_dir):
                if module != "__init__":
                    test_names.append(".".join([pkg, module]))
        tests = TestLoader().loadTestsFromNames(test_names)
        with display(self.display):
            TextTestRunner(verbosity=self.verbose).run(tests)

class Distribution(AutogenDistribution, TestDistribution):
    pass

setup(name="dim",
      version="0.1",
      description="A window manager for the X window system",
      author="Alex Plotnick",
      author_email="shrike@netaxs.com",
      scripts=["bin/dim"],
      packages=["dim", "dim.test", "dim.util"],
      test_packages=["dim.test"],
      autogen_modules=[("cursorfont.h", "dim.cursorfont", make_cursor_font),
                       ("keysymdef.h", "dim.keysymdef", make_keysym_def)],
      autogen_source_dirs=["/usr/local/include/X11", "/usr/include/X11"],
      cmdclass={"build": build, "generate_py": generate_py, "test": test},
      distclass=Distribution)
