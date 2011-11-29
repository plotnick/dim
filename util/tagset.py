#!/usr/bin/env python
# -*- mode: Python; coding: utf-8 -*-

"""Request a tagset update."""

from __future__ import unicode_literals

import re

import xcb
from xcb.xproto import *

from atom import *
from xutil import *

class TagsetError(StandardError):
    pass

class TokenizationError(TagsetError):
    pass

class SpecSyntaxError(TagsetError):
    pass

operators = {}
def operator(cls):
    """Register a class as an operator token."""
    operators[cls.str_symbol] = cls
    operators[cls.unicode_symbol] = cls
    return cls

class OpToken(object):
    """For convenience and aesthetic reasons, all operators have both an
    ASCII and a non-ASCII Unicode character representation, which are
    treated identically by the tokenizer.

    They also each have a representation as an atom. The atom names must
    correspond with the opcodes established for the virtual tag machine."""

    def __str__(self):
        return self.str_symbol

    def __unicode__(self):
        return self.unicode_symbol

    def __eq__(self, other):
        if isinstance(other, str):
            return str(self) == other
        elif isinstance(other, unicode):
            return unicode(self) == other
        elif isinstance(other, OpToken):
            return type(self) == type(other)
        else:
            return False

@operator
class Union(OpToken):
    str_symbol = "|"
    unicode_symbol = "∪"
    atom = "_DIM_TAGSET_UNION"

@operator
class Intersection(OpToken):
    str_symbol = "&"
    unicode_symbol = "∩"
    atom = "_DIM_TAGSET_INTERSECTION"

@operator
class Difference(OpToken):
    str_symbol = "\\"
    unicode_symbol = "∖"
    atom = "_DIM_TAGSET_DIFFERENCE"

@operator
class Complement(OpToken):
    str_symbol = "~"
    unicode_symbol = "∁"
    atom = "_DIM_TAGSET_COMPLEMENT"

def tokenize(string,
             whitespace=re.compile(r"\s*", re.UNICODE),
             tag=re.compile(r"([\w-]+|\*|∅|\.)", re.UNICODE)):
    """Yield tokens of a string representation of a tagset specification."""
    level = 0
    i = 0
    while i < len(string):
        # Skip over whitespace.
        m = whitespace.match(string, i)
        if m:
            i = m.end()

        m = tag.match(string, i)
        if m:
            yield m.group()
            i = m.end()
        elif string[i] == "(":
            yield "("
            level += 1
            i += 1
        elif string[i] == ")":
            yield ")"
            level -= 1
            i += 1
        elif string[i] in operators:
            yield operators[string[i]]()
            i += 1
        else:
            raise TokenizationError("invalid token\n  %s\n  %*c" %
                                    (string, i+1, "^"))
    if level != 0:
        raise SpecSyntaxError("unmatched parenthesis")

class Expression(object):
    """Base class for infix tagset specification expressions."""

    def postfix(self):
        return []

class Tag(Expression, unicode):
    """A Unicode string representing a tag (a terminal expression)."""

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, unicode.__repr__(self))

    def postfix(self):
        return [self]

class UnaryOp(Expression):
    """A prefix unary operator."""

    def __init__(self, op, arg):
        self.op = op
        self.arg = arg

    def __str__(self):
        return "(%s %s)" % (self.op, self.arg)

    def __repr__(self):
        return "%s(%r, %r)" % (self.__class__.__name__, self.op, self.arg)

    def postfix(self):
        return self.arg.postfix() + [self.op]

class BinOp(Expression):
    """An infix binary operator."""

    def __init__(self, op, lhs, rhs):
        self.op = op
        self.lhs = lhs
        self.rhs = rhs

    def __str__(self):
        return "(%s %s %s)" % (self.lhs, self.op, self.rhs)

    def __repr__(self):
        return "%s(%r, %r, %r)" % (self.__class__.__name__,
                                   self.op, self.lhs, self.rhs)
    def postfix(self):
        pexpr = []
        pexpr.extend(self.lhs.postfix())
        pexpr.extend(self.rhs.postfix())
        pexpr.append(self.op)
        return pexpr

class SpecParser(object):
    """A recursive-descent parser for tagset specifications. Adapted from
    the partial grammar for the AWK language given in "The AWK Programming
    Language" by Alfred V. Aho, Brian W. Kernighan, and Peter J. Weinberger
    (Addison-Wesley, 1988)."""

    def parse(self, tokens):
        """Parse and return a tagset specification expression."""
        self.tokens = iter(tokens)
        self.advance()
        spec = self.spec()
        if self.token:
            raise SpecSyntaxError("trailing garbage: %s" % self.token)
        return spec

    def advance(self):
        """Get the next token from the token source and stash it in the token
        attribute. If there is no next token, None is used instead."""
        try:
            self.token = self.tokens.next()
        except StopIteration:
            self.token = None

    def eat(self, token):
        """Check that the current token matches the given one, and advance."""
        if self.token != token:
            raise SpecSyntaxError("expected %s, got %s" % (token, self.token))
        self.advance()

    def spec(self):
        """spec → term | term [∪∖] term"""
        e = self.term()
        while self.token == "∪" or self.token == "∖":
            op = self.token
            self.advance()
            e = BinOp(op, e, self.term())
        return e

    def term(self):
        """term → comp | comp ∩ comp"""
        e = self.comp()
        while self.token == "∩":
            op = self.token
            self.advance()
            e = BinOp(op, e, self.comp())
        return e

    def comp(self):
        """comp → fact | ∁ fact"""
        if self.token == "∁":
            op = self.token
            self.advance()
            return UnaryOp(op, self.fact())
        else:
            return self.fact()

    def fact(self):
        """fact → (spec) | tag"""
        if self.token == "(":
            try:
                self.eat("(")
                return self.spec()
            finally:
                self.eat(")")
        elif isinstance(self.token, basestring):
            try:
                return Tag(self.token)
            finally:
                self.advance()
        else:
            raise SpecSyntaxError("unexpected token %s" % self.token)

def update_tagset(conn, pexpr, show=True):
    """Given a postfix tagset specification expression (i.e., a list of
    tag machine instructions), encode the expression as a list of atoms
    and send it to the window manager via ClientMessage events on the
    root window."""
    def atom(x,
             atoms=AtomCache(conn),
             aliases={"*": "_DIM_ALL_TAGS",
                      ".": "_DIM_CURRENT_TAGSET",
                      "∅": "_DIM_EMPTY_TAGSET",
                      "0": "_DIM_EMPTY_TAGSET"}):
        if isinstance(x, OpToken):
            x = x.atom
        else:
            x = aliases.get(x, x)
        return atoms.intern(x, "UTF-8")

    # We can only fit five atoms in a ClientMessage event, so we'll
    # split the expression into chunks and send as many as we need to.
    # This works because the window manager maintains the tag machine
    # stack contents until a "show" operation is executed.
    def pad(sequence, padding=0, n=5):
        return sequence + [padding] * (n - len(sequence))
    if show:
        pexpr += ["_DIM_TAGSET_SHOW"]
    root = conn.get_setup().roots[conn.pref_screen].root
    for i in range(0, len(pexpr), 5):
        send_client_message(conn, root, root,
                            (EventMask.SubstructureNotify |
                             EventMask.SubstructureRedirect),
                            32, atom("_DIM_TAGSET_UPDATE"),
                            pad(map(atom, pexpr[i:i + 5])))

if __name__ == "__main__":
    from doctest import testmod
    from optparse import OptionParser
    from sys import exit, stdin

    optparser = OptionParser("Usage: %prog [OPTIONS] TAGSET-SPEC")
    optparser.add_option("-d", "--display", dest="display",
                         help="the X server display name")
    (options, args) = optparser.parse_args()
    if len(args) == 0:
        testmod()
        exit(0)
    elif len(args) != 1:
        optparser.print_help()
        exit(1)
    spec = unicode(args[0], stdin.encoding)
    conn = xcb.connect(options.display)
    parser = SpecParser()
    update_tagset(conn, parser.parse(tokenize(spec)).postfix())
    conn.flush()
