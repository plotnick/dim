# -*- mode: Python; coding: utf-8 -*-

from __future__ import unicode_literals

from collections import defaultdict
import logging
import re

from xcb.xproto import *

from atom import *
from manager import WindowManager, WindowManagerProperties
from properties import PropertyDescriptor, AtomList, WMState

__all__ = ["TagError", "TagManager",
           "parse_tagset_spec", "send_tagset_expression"]

log = logging.getLogger("tags")

class TagError(Exception):
    pass

class StackUnderflow(TagError):
    pass

class TagMachine(object):
    """A small virtual stack machine for updating the set of visible clients
    via operations on tagsets."""

    def __init__(self, clients, tagsets, opcodes={}, stack=[]):
        self.clients = clients
        self.tagsets = tagsets
        self.opcodes = dict((code, getattr(self, name))
                            for code, name in opcodes.items())
        self.stack = stack

    def run(self, instructions):
        for x in instructions:
            op = self.opcodes.get(x, None)
            if op:
                op()
            else:
                self.tag(x)
        if self.stack:
            log.debug("Tagset stack: %r.", self.stack)

    def nop(self):
        pass

    def push(self, x):
        self.stack.append(x)
        return x

    def pop(self):
        if not self.stack:
            raise StackUnderflow
        top = self.stack[-1]
        del self.stack[-1]
        return top

    def dup(self):
        if not self.stack:
            raise StackUnderflow
        return self.push(self.stack[-1])

    def swap(self):
        x, y = self.pop(), self.pop()
        self.push(x)
        self.push(y)

    def clear(self):
        if self.stack:
            log.debug("Discarding %d elements from stack.", len(self.stack))
            del self.stack[:]

    def union(self):
        return self.push(self.pop() | self.pop())

    def intersection(self):
        return self.push(self.pop() & self.pop())

    def difference(self):
        x, y = self.pop(), self.pop()
        return self.push(y - x)

    def complement(self):
        self.all_clients()
        self.swap()
        return self.difference()

    def show(self):
        self.dup()
        self.complement()
        for client in self.pop():
            client.iconify()
        for client in self.pop():
            client.normalize()
        self.clear()

    def tag(self, tag):
        return self.push(self.tagsets.get(tag, set()))

    def all_tags(self):
        return self.push(reduce(set.union, self.tagsets.values(), set()))

    def all_clients(self):
        return self.push(set(self.clients.values()))

    def current_set(self):
        return self.push(set(client
                             for client in self.clients.values()
                             if client.properties.wm_state == WMState.NormalState))

    def empty_set(self):
        return self.push(set())

# Sequences of tag machine instructions will generally be provided by the
# user in the form of infix expressions which we call tagset specifications.
# Such expressions are tokenized, parsed, converted to postfix, and then
# encoded as operations for the tag machine.

class TokenizationError(TagError):
    pass

class SpecSyntaxError(TagError):
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
        return (str(self) == other if isinstance(other, str) else
                unicode(self) == other if isinstance(other, unicode) else
                type(self) == type(other) if isinstance(other, OpToken) else
                False)

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

def parse_tagset_spec(spec):
    """Tokenize and parse a tagset specification, returning a list of tag
    machine instructions."""
    return SpecParser().parse(tokenize(spec)).postfix()

def send_tagset_expression(conn, pexpr, show=True, atoms=None):
    """Given a tag machine expression, encode it as a list of atoms and
    send it to the window manager via a property on the root window."""
    def atom(x,
             atoms=atoms if atoms else AtomCache(conn),
             aliases={"*": "_DIM_ALL_TAGS",
                      ".": "_DIM_CURRENT_TAGSET",
                      "∅": "_DIM_EMPTY_TAGSET",
                      "0": "_DIM_EMPTY_TAGSET"}):
        if isinstance(x, OpToken):
            x = x.atom
        else:
            x = aliases.get(x, x)
        return atoms.intern(x, "UTF-8")
    if show:
        pexpr += ["_DIM_TAGSET_SHOW"]
    root = conn.get_setup().roots[conn.pref_screen].root
    conn.core.ChangeProperty(PropMode.Replace,
                             root,
                             atom("_DIM_TAGSET_EXPRESSION"),
                             atom("ATOM"),
                             *AtomList(map(atom, pexpr)).change_property_args())

# Finally, we have a manager class that maintains the tagsets and tag machine.

class TagManagerProperties(WindowManagerProperties):
    tagset_expr = PropertyDescriptor("_DIM_TAGSET_EXPRESSION", AtomList, [])

class TagManager(WindowManager):
    property_class = TagManagerProperties

    def __init__(self, *args, **kwargs):
        super(TagManager, self).__init__(*args, **kwargs)

        self.tagsets = defaultdict(set) # sets of clients, indexed by tag
        opcodes = {"_DIM_TAGSET_UNION": "union",
                   "_DIM_TAGSET_INTERSECTION": "intersection",
                   "_DIM_TAGSET_DIFFERENCE": "difference",
                   "_DIM_TAGSET_COMPLEMENT": "complement",
                   "_DIM_TAGSET_SHOW": "show",
                   "_DIM_ALL_TAGS": "all_tags",
                   "_DIM_CURRENT_TAGSET": "current_set",
                   "_DIM_EMPTY_TAGSET": "empty_set",
                   None: "nop"}
        self.atoms.prime_cache(opcodes.keys())
        self.tag_machine = TagMachine(self.clients, self.tagsets,
                                      dict((self.atoms[code], name)
                                           for code, name in opcodes.items()))
        self.properties.register_change_handler("_DIM_TAGSET_EXPRESSION",
                                                self.tagset_expression_changed)

    def shutdown(self):
        super(TagManager, self).shutdown()
        for tagset in self.tagsets.values():
            assert not tagset

    def manage(self, window):
        client = super(TagManager, self).manage(window)
        if client:
            self.note_tags(client)
            client.properties.register_change_handler("_DIM_TAGS",
                                                      self.tags_changed)
        return client

    def unmanage(self, client, **kwargs):
        self.forget_tags(client)
        client.properties.unregister_change_handler("_DIM_TAGS",
                                                    self.tags_changed)
        super(TagManager, self).unmanage(client, **kwargs)

    def note_tags(self, client):
        for tag in client.properties.dim_tags:
            log.debug("Adding client window 0x%x to tagset %s.",
                      client.window, self.atoms.name(tag, "UTF-8"))
            self.tagsets[tag].add(client)

        # We'll use the client's instance and class names (ICCCM §4.1.2.5)
        # as implicit tags.
        def atom(string):
            return self.atoms.intern(string, "UTF-8")
        instance, cls = tuple(client.properties.wm_class)
        if instance:
            self.tagsets[atom(instance)].add(client)
        if cls:
            self.tagsets[atom(cls)].add(client)

    def forget_tags(self, client):
        for tagset in self.tagsets.values():
            tagset.discard(client)

    def tags_changed(self, window, name, deleted, time):
        client = self.get_client(window, True)
        self.forget_tags(client)
        if not deleted:
            self.note_tags(client)

    def tagset_expression_changed(self, window, name, deleted, time):
        assert window == self.screen.root
        if deleted:
            return
        try:
            self.tag_machine.run(self.properties.tagset_expr)
        except StackUnderflow:
            log.warning("Stack underflow while evaluating tagset expression.")
        self.ensure_focus(time=time)
