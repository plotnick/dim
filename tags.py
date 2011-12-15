# -*- mode: Python; coding: utf-8 -*-

from collections import defaultdict
import logging

from manager import WindowManager, WindowManagerProperties
from properties import PropertyDescriptor, AtomList, WMState

__all__ = ["TagManager"]

log = logging.getLogger("tags")

class StackUnderflow(Exception):
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

class TagManagerProperties(WindowManagerProperties):
    tagset_update = PropertyDescriptor("_DIM_TAGSET_UPDATE", AtomList, [])

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
        self.properties.register_change_handler("_DIM_TAGSET_UPDATE",
                                                self.update_tagset)

    def manage(self, window):
        client = super(TagManager, self).manage(window)
        if client:
            self.note_tags(client)
            client.properties.register_change_handler("_DIM_TAGS",
                                                      self.tags_changed)
        return client

    def unmanage(self, client):
        client.properties.unregister_change_handler("_DIM_TAGS",
                                                    self.tags_changed)
        super(TagManager, self).unmanage(client)

    def note_tags(self, client):
        for tag in client.properties.dim_tags:
            log.debug("Adding client window 0x%x to tagset %s.",
                      client.window, self.atoms.name(tag, "UTF-8"))
            self.tagsets[tag].add(client)

    def tags_changed(self, window, name, deleted, time):
        client = self.get_client(window, True)
        for tagset in self.tagsets.values():
            tagset.discard(client)
        if not deleted:
            self.note_tags(client)

    def update_tagset(self, window, name, deleted, time):
        assert window == self.screen.root
        if deleted:
            return
        try:
            self.tag_machine.run(self.properties.tagset_update)
        except StackUnderflow:
            log.warning("Stack underflow while executing tagset update.")
        try:
            self.ensure_focus(time=time)
        except AttributeError:
            pass
