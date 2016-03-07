# -*- mode: Python; coding: utf-8 -*-

"""Client windows may be assigned zero or more "tags" via a list of X atoms
stored in a property on that window. Each tag thus implicitly defines a set
of clients, called a "tagset". By combining tagsets in various ways, the
user may specify exactly the set of clients they wish to see at any given
time. Tags thus serve a purpose similar to virtual desktops, but with a
great deal more flexibility."""

from __future__ import unicode_literals

from collections import defaultdict
import logging
import re

from xcb.xproto import *

from atom import AtomCache
from manager import WindowManager
from properties import PropertyDescriptor, AtomList, WMState

__all__ = ["SpecSyntaxError", "parse_tagset_spec", "send_tagset_expr",
           "TagManager"]

log = logging.getLogger("tags")

class TagMachineError(Exception):
    pass

class TagMachine(object):
    """A small virtual stack machine for operating on tagsets.

    The operations of the machine are simply its one-argument methods.
    For flexibility and ease of testing, the format of the instruction
    stream is configurable at machine-initialization time; e.g., a window
    manger might use atoms, whereas a test might use simple strings.
    Objects in the instruction stream that are not registered as opcodes
    are taken to be tagset names, the contents of which are implicitly
    pushed onto the stack."""

    def __init__(self, clients, tagsets, opcodes={}, wild=None,
                 default_tagset=lambda tag: []):
        self.clients = clients
        self.tagsets = tagsets
        self.opcodes = dict((code, getattr(self, name))
                            for code, name in opcodes.items())
        self.wild = wild
        self.default_tagset = default_tagset

        self.ip = iter([])
        self.stack = []
        self.push = self.stack.append
        self.pop = self.stack.pop

    def tagset(self, tag):
        self.push(self.tagsets.get(tag) or set(self.default_tagset(tag)))

    def run(self, instructions):
        self.ip = iter(instructions)
        for x in self.ip:
            op = self.opcodes.get(x, None)
            if op:
                op()
            else:
                self.tagset(x)
        if self.stack:
            log.debug("Tagset stack: %r.", self.stack)

    def nop(self):
        pass

    def dup(self):
        self.push(self.stack[-1])

    def swap(self):
        x, y = self.pop(), self.pop()
        self.push(x)
        self.push(y)

    def clear(self):
        if self.stack:
            log.debug("Discarding %d elements from stack.", len(self.stack))
            del self.stack[:]

    def quote(self):
        self.push(next(self.ip))

    def begin(self):
        """Pull instructions off the instruction stream until a matching end
        is found, and push a list containing the instructions so collected."""
        l = []
        while True:
            x = next(self.ip)
            op = self.opcodes.get(x, None)
            if op == self.end:
                break
            elif op == self.begin:
                self.begin()
                x = self.pop()
            l.append(x)
        self.push(l)

    def end(self):
        # List endings are actually handled in begin.
        raise TagMachineError("unexpected list end")

    def assign(self):
        value = self.pop()
        name = self.pop()
        if isinstance(value, set):
            # Tagset assignment.
            self.opcodes.pop(name, None)
            self.tagsets[name] = set(value)
            self.tagset(name)
        elif isinstance(value, list):
            # Procedure assignment.
            self.tagsets.pop(name, None)
            self.opcodes[name] = lambda: self.run(value)
            self.run(value)
        else:
            raise TagMachineError("invalid assignment")

    def union(self):
        self.push(self.pop() | self.pop())

    def intersection(self):
        self.push(self.pop() & self.pop())

    def difference(self):
        x, y = self.pop(), self.pop()
        self.push(y - x)

    def complement(self):
        self.all_clients()
        self.swap()
        self.difference()

    def show(self):
        if self.wild:
            self.push(self.tagsets.get(self.wild, set()))
            self.union()
        self.dup()
        self.complement()
        for client in self.pop():
            client.iconify()
        for client in self.pop():
            client.normalize()
        self.clear()

    def all_tags(self):
        self.push(reduce(set.union, self.tagsets.values(), set()))

    def all_clients(self):
        self.push(set(self.clients.values()))

    def empty_set(self):
        self.push(set())

    def current_set(self):
        self.push(set(client
                      for client in self.clients.values()
                      if client.wm_state == WMState.NormalState))

# Sequences of tag machine instructions will generally be provided by the
# user in the form of infix expressions which we call tagset specifications.
# Such expressions are tokenized, parsed, converted to postfix, and then
# encoded as operations for the tag machine.

class SpecSyntaxError(Exception):
    pass

operator_tokens = {}

class OpTokenClass(type):
    def __new__(metaclass, name, bases, namespace):
        cls = super(OpTokenClass, metaclass).__new__(metaclass, name,
                                                     bases, namespace)
        if "str_symbol" in namespace and "unicode_symbol" in namespace:
            operator_tokens[namespace["str_symbol"]] = cls
            operator_tokens[namespace["unicode_symbol"]] = cls
        return cls

class OpToken(object):
    """For convenience and aesthetic reasons, most operators have both
    an ASCII and a non-ASCII Unicode character representation, which are
    treated identically by the tokenizer.

    They also each have a representation as an atom. The atom names must
    correspond with the opcodes established for the virtual tag machine."""

    __metaclass__ = OpTokenClass

    def __str__(self):
        return self.str_symbol

    def __unicode__(self):
        return self.unicode_symbol

    def __eq__(self, other):
        return (str(self) == other if isinstance(other, str) else
                unicode(self) == other if isinstance(other, unicode) else
                type(self) == type(other) if isinstance(other, OpToken) else
                False)

    def __ne__(self, other):
        return not (self == other)

class Assign(OpToken):
    str_symbol = "="
    unicode_symbol = "="
    atom = "_DIM_TAGSET_ASSIGN"

class Begin(OpToken):
    str_symbol = "{"
    unicode_symbol = "{"
    atom = "_DIM_TAGSET_BEGIN"

class End(OpToken):
    str_symbol = "}"
    unicode_symbol = "}"
    atom = "_DIM_TAGSET_END"

class Quote(OpToken):
    str_symbol = "'"
    unicode_symbol = "'"
    atom = "_DIM_TAGSET_QUOTE"

class Union(OpToken):
    str_symbol = "|"
    unicode_symbol = "∪"
    atom = "_DIM_TAGSET_UNION"

class Intersection(OpToken):
    str_symbol = "&"
    unicode_symbol = "∩"
    atom = "_DIM_TAGSET_INTERSECTION"

class Difference(OpToken):
    str_symbol = "\\"
    unicode_symbol = "∖"
    atom = "_DIM_TAGSET_DIFFERENCE"

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
        elif string[i] in operator_tokens:
            yield operator_tokens[string[i]]()
            i += 1
        else:
            raise SpecSyntaxError("invalid token\n  %s\n  %*c" %
                                  (string, i + 1, "^"))
    if level != 0:
        raise SpecSyntaxError("unmatched parenthesis")

class Expr(object):
    """Base class for tagset specification expressions."""

    def postfix(self):
        return []

class Tag(Expr, unicode):
    """A Unicode string representing a tag (a terminal expression)."""

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, unicode.__repr__(self))

    def postfix(self):
        return [self]

class UnaryOp(Expr):
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

class BinOp(Expr):
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
        expr = []
        expr.extend(self.lhs.postfix())
        expr.extend(self.rhs.postfix())
        expr.append(self.op)
        return expr

class QuotedExpr(Expr):
    """A quoted expression."""

    def __init__(self, expr):
        self.expr = expr

    def __str__(self):
        return "'(%s)" % (self.expr,)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.expr)

    def postfix(self):
        expr = [Quote()]
        expr.extend(self.expr.postfix())
        return expr

class ListExpr(Expr):
    """A list of sub-expressions."""

    def __init__(self, expr):
        self.expr = expr

    def __str__(self):
        return "{%s}" % (self.expr,)

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.expr)

    def postfix(self):
        expr = [Begin()]
        expr.extend(self.expr.postfix())
        expr.append(End())
        return expr

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
            raise SpecSyntaxError("trailing garbage: '%s'" % (self.token,))
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
            raise SpecSyntaxError("expected '%s', got '%s'" %
                                  (token, self.token))
        self.advance()

    def spec(self):
        """spec → expr | tag = expr"""
        e = self.expr()
        if self.token == "=":
            if not isinstance(e, Tag):
                raise SpecSyntaxError("invalid assignment lhs '%s'" % (e,))
            op = self.token
            self.advance()
            e = BinOp(op, QuotedExpr(e), self.expr())
        return e

    def expr(self):
        """expr → term | term [∪∖] term"""
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
        """fact → (expr) | {expr} | tag"""
        if self.token == "(":
            try:
                self.eat("(")
                return self.expr()
            finally:
                self.eat(")")
        elif self.token == "{":
            try:
                self.eat("{")
                return ListExpr(self.expr())
            finally:
                self.eat("}")
        elif isinstance(self.token, basestring):
            try:
                return Tag(self.token)
            finally:
                self.advance()
        else:
            raise SpecSyntaxError("unexpected token '%s'" % (self.token,))

def parse_tagset_spec(spec):
    """Tokenize and parse a tagset specification."""
    return SpecParser().parse(tokenize(spec)).postfix()

def intern_tagset_expr(conn, expr, atoms=None,
                       aliases={"*": "_DIM_ALL_TAGS",
                                ".": "_DIM_CURRENT_SET",
                                "∅": "_DIM_EMPTY_SET",
                                "0": "_DIM_EMPTY_SET"}):
    def intern(x, atoms=atoms or AtomCache(conn)):
        return atoms.intern(x.atom
                            if isinstance(x, OpToken)
                            else aliases.get(x, x),
                            "UTF-8")
    return map(intern, expr)

def send_tagset_expr(conn, expr, show=True, screen=None, atoms=None):
    """Given a tag machine expression, encode it as a list of atoms and
    send it to the window manager via a property on the root window."""
    if show:
        expr += ["_DIM_TAGSET_SHOW"]
    expr = intern_tagset_expr(conn, expr, atoms)
    screen = conn.pref_screen if screen is None else screen
    root = conn.get_setup().roots[screen].root
    conn.core.ChangeProperty(PropMode.Replace,
                             root,
                             atoms.intern("_DIM_TAGSET_EXPR"),
                             atoms.intern("ATOM"),
                             *AtomList(expr).change_property_args())

# Finally, we have a manager class that maintains the tagsets and tag machine.

class TagManager(WindowManager):
    tagset_expr = PropertyDescriptor("_DIM_TAGSET_EXPR", AtomList, [])

    def __init__(self, **kwargs):
        super(TagManager, self).__init__(**kwargs)

        self.tagsets = defaultdict(set) # sets of clients, indexed by tag
        opcodes = {None: "nop",
                   "_DIM_TAGSET_BEGIN": "begin",
                   "_DIM_TAGSET_END": "end",
                   "_DIM_TAGSET_QUOTE": "quote",
                   "_DIM_TAGSET_ASSIGN": "assign",
                   "_DIM_TAGSET_UNION": "union",
                   "_DIM_TAGSET_INTERSECTION": "intersection",
                   "_DIM_TAGSET_DIFFERENCE": "difference",
                   "_DIM_TAGSET_COMPLEMENT": "complement",
                   "_DIM_TAGSET_SHOW": "show",
                   "_DIM_ALL_TAGS": "all_tags",
                   "_DIM_EMPTY_SET": "empty_set",
                   "_DIM_CURRENT_SET": "current_set"}
        self.atoms.prime_cache(list(opcodes.keys()) + ["*"])
        self.tag_machine = TagMachine(self.clients, self.tagsets,
                                      dict((self.atoms[code], name)
                                           for code, name in opcodes.items()),
                                      wild=self.atoms["*"],
                                      default_tagset=self.default_tagset)
        self.register_property_change_handler("_DIM_TAGSET_EXPR",
                                              self.tagset_expr_changed)

    def shutdown(self, *args):
        super(TagManager, self).shutdown(*args)
        for tagset in self.tagsets.values():
            assert not tagset

    def manage(self, window, adopted=False):
        client = super(TagManager, self).manage(window, adopted)
        if client:
            self.note_tags(client)
            client.register_property_change_handler("_DIM_TAGS",
                                                    self.tags_changed)
        return client

    def unmanage(self, client, **kwargs):
        self.forget_tags(client)
        client.unregister_property_change_handler("_DIM_TAGS",
                                                  self.tags_changed)
        super(TagManager, self).unmanage(client, **kwargs)

    def change_state(self, client, initial, final):
        super(TagManager, self).change_state(client, initial, final)

        if (initial, final) == (WMState.WithdrawnState, WMState.NormalState):
            tags = self.auto_tag(client)
            if tags:
                log.debug("Auto-tagging client window 0x%x with tags [%s].",
                          client.window,
                          ", ".join(self.atoms.name(atom, "UTF-8")
                                    for atom in tags))
                client.dim_tags = AtomList(tags)

    def auto_tag(self, client):
        """Return a list of tags which should be applied to the new client."""
        # We use a few simple heuristics to choose the default tags.
        # (1) If there are existing tags, don't apply any new ones.
        # (2) Try to copy the tags of the currently focused window.
        # (3) If there is no current focus, examine the the last tagset
        # expression; if it begins with a valid tag name but there aren't
        # any windows so tagged, return that. The idea here is that if the
        # user switches to a new tag, the next window created should be
        # tagged thus.
        if client.dim_tags:
            return None
        elif (self.current_focus and
              self.current_focus.wm_state == WMState.NormalState):
            return self.current_focus.dim_tags[:]
        elif (self.tagset_expr and
              self.tagset_expr[0] not in self.tag_machine.opcodes and
              not self.tagsets.get(self.tagset_expr[0])):
            return [self.tagset_expr[0]]

    def default_tagset(self, tag):
        """Yield client for the given tag, which does not name a tagset.
        We treat the client's class and instance names (ICCCM §4.1.2.5)
        as implicit tags."""
        for client in self.clients.values():
            if any(x and self.atoms.intern(x, "UTF-8") == tag
                   for x in client.wm_class):
                yield client

    def note_tags(self, client):
        for tag in client.dim_tags:
            log.debug("Adding client window 0x%x to tagset %s.",
                      client.window, self.atoms.name(tag, "UTF-8"))
            self.tagsets[tag].add(client)

    def forget_tags(self, client):
        for tagset in self.tagsets.values():
            tagset.discard(client)

    def tags_changed(self, window, name, deleted, time):
        client = self.get_client(window, True)
        self.forget_tags(client)
        if not deleted:
            self.note_tags(client)

    def tagset_expr_changed(self, window, name, deleted, time):
        assert window == self.screen.root
        if deleted:
            return
        try:
            self.tag_machine.run(self.tagset_expr)
        except IndexError:
            log.warning("Stack underflow while evaluating tagset expression.")
        self.ensure_focus(time=time)

    def tagset(self, spec, show=True):
        """Parse and execute a tagset specification directly.
        Does not use or set the _DIM_TAGSET_EXPR property."""
        expr = parse_tagset_spec(spec) + (["_DIM_TAGSET_SHOW"] if show else [])
        self.tag_machine.run(intern_tagset_expr(self.conn, expr,
                                                atoms=self.atoms))
