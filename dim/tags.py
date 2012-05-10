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
from manager import WindowManager, WindowManagerProperties
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

    def __init__(self, clients, tagsets, opcodes={}, wild=None):
        self.clients = clients
        self.tagsets = tagsets
        self.opcodes = dict((code, getattr(self, name))
                            for code, name in opcodes.items())
        self.wild = wild

        self.ip = iter([])
        self.stack = []
        self.push = self.stack.append
        self.pop = self.stack.pop

    def run(self, instructions):
        def tagset(tag):
            self.push(self.tagsets.get(tag, set()))

        self.ip = iter(instructions)
        for x in self.ip:
            op = self.opcodes.get(x, None)
            if op:
                op()
            else:
                tagset(x)
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
            try:
                x = next(self.ip)
            except StopIteration:
                raise TagMachineError("invalid list")
            op = self.opcodes.get(x, None)
            if op == self.end:
                break
            elif op == self.begin:
                self.begin()
                x = self.pop()
            else:
                l.append(x)
        self.push(l)

    def end(self):
        # List endings are actually handled in begin.
        raise TagMachineError("unexpected list end")

    def assign(self):
        name = self.pop()
        value = self.pop()
        if isinstance(value, set):
            # Tagset assignment.
            self.tagsets[name] = set(value)
        elif isinstance(value, list):
            # Procedure assignment.
            self.opcodes[name] = lambda: self.run(value)
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
                      if client.properties.wm_state == WMState.NormalState))

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
            raise SpecSyntaxError("trailing garbage: '%s'" % self.token)
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
            raise SpecSyntaxError("unexpected token '%s'" % self.token)

def parse_tagset_spec(spec):
    """Tokenize and parse a tagset specification."""
    return SpecParser().parse(tokenize(spec)).postfix()

def send_tagset_expr(conn, expr, show=True, screen=None, atoms=None):
    """Given a tag machine expression, encode it as a list of atoms and
    send it to the window manager via a property on the root window."""
    def atom(x,
             atoms=atoms if atoms else AtomCache(conn),
             aliases={"*": "_DIM_ALL_TAGS",
                      ".": "_DIM_CURRENT_SET",
                      "∅": "_DIM_EMPTY_SET",
                      "0": "_DIM_EMPTY_SET"}):
        if isinstance(x, OpToken):
            x = x.atom
        else:
            x = aliases.get(x, x)
        return atoms.intern(x, "UTF-8")
    if show:
        expr += ["_DIM_TAGSET_SHOW"]
    screen = conn.pref_screen if screen is None else screen
    root = conn.get_setup().roots[screen].root
    conn.core.ChangeProperty(PropMode.Replace,
                             root,
                             atom("_DIM_TAGSET_EXPR"),
                             atom("ATOM"),
                             *AtomList(map(atom, expr)).change_property_args())

# Finally, we have a manager class that maintains the tagsets and tag machine.

class TagManagerProperties(WindowManagerProperties):
    tagset_expr = PropertyDescriptor("_DIM_TAGSET_EXPR", AtomList, [])

class TagManager(WindowManager):
    property_class = TagManagerProperties

    def __init__(self, **kwargs):
        super(TagManager, self).__init__(**kwargs)

        self.tagsets = defaultdict(set) # sets of clients, indexed by tag
        opcodes = {None: "nop",
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
                                      wild=self.atoms["*"])
        self.properties.register_change_handler("_DIM_TAGSET_EXPR",
                                                self.tagset_expr_changed)

    def shutdown(self, *args):
        super(TagManager, self).shutdown(*args)
        for tagset in self.tagsets.values():
            assert not tagset

    def manage(self, window, adopted=False):
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

    def change_state(self, client, initial, final):
        super(TagManager, self).change_state(client, initial, final)

        # If a newly-normalized client doesn't have any tags yet,
        # try to copy the tags of the currently focused window.
        if (initial == WMState.WithdrawnState and
            final == WMState.NormalState and
            not client.properties.dim_tags):
            focus = self.current_focus
            if focus and focus.properties.wm_state == WMState.NormalState:
                tags = focus.properties.dim_tags
                if tags:
                    log.debug("Auto-tagging client window 0x%x with tags [%s].",
                              client.window,
                              ", ".join(self.atoms.name(atom, "UTF-8")
                                        for atom in tags))
                    client.properties.dim_tags = AtomList(tags[:])

    def note_tags(self, client):
        for tag in client.properties.dim_tags:
            log.debug("Adding client window 0x%x to tagset %s.",
                      client.window, self.atoms.name(tag, "UTF-8"))
            self.tagsets[tag].add(client)

        # We'll use the client's class name (ICCCM §4.1.2.5) as an implicit
        # tag. Note that this will not show up in the client's tags list,
        # since we're adding it directly to the tagset.
        instance, class_name = tuple(client.properties.wm_class)
        if class_name:
            self.tagsets[self.atoms.intern(class_name, "UTF-8")].add(client)

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
            self.tag_machine.run(self.properties.tagset_expr)
        except IndexError:
            log.warning("Stack underflow while evaluating tagset expression.")
        except TagMachineError as e:
            log.warning("Tag machine execution error: %s", e)
        self.ensure_focus(time=time)
