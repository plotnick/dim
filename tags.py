# -*- mode: Python; coding: utf-8 -*-

from collections import defaultdict
import logging

from event import handler
from manager import client_message_type, ClientMessage, WindowManager
from properties import WMState

__all__ = ["TagManager"]

log = logging.getLogger("tags")

class TagsetUpdateMessage(ClientMessage):
    @property
    def tags(self):
        # Most update messages may include up to five tags (the maximum
        # number of atoms that fit in a ClientMessage event). Null atoms
        # are ignored.
        return [tag for tag in self.data.data32 if tag]

@client_message_type("_DIM_TAGSET_SHOW")
class TagsetShow(TagsetUpdateMessage):
    @property
    def tags(self):
        # The "show" operator accepts exactly one tag; we'll take the first
        # (even if it's None) and ignore the rest.
        return self.data.data32[:1]

    @property
    def function(self):
        return lambda x, y: y

@client_message_type("_DIM_TAGSET_UNION")
class TagsetUnion(TagsetUpdateMessage):
    @property
    def function(self):
        return set.union

@client_message_type("_DIM_TAGSET_INTERSECTION")
class TagsetIntersection(TagsetUpdateMessage):
    @property
    def function(self):
        return set.intersection

@client_message_type("_DIM_TAGSET_DIFFERENCE")
class TagsetDifference(TagsetUpdateMessage):
    @property
    def function(self):
        return set.difference

class TagManager(WindowManager):
    def __init__(self, *args, **kwargs):
        self.tagsets = defaultdict(set) # sets of clients, indexed by tag
        super(TagManager, self).__init__(*args, **kwargs)

    def note_tags(self, client):
        for tagset in self.tagsets.values():
            tagset.discard(client)
        for tag in client.dim_tags:
            log.debug("Adding client window 0x%x to tagset %s.",
                      client.window, self.atoms.name(tag))
            self.tagsets[tag].add(client)

    def manage(self, window):
        client = super(TagManager, self).manage(window)
        if client:
            self.note_tags(client)
        return client

    def update_tagset(self, function, tags):
        def tagset(tag):
            if not tag:
                # The null atom denotes the set of client windows with no tags.
                return set(c for c in self.clients.values() if not c.dim_tags)
            elif tag == self.atoms["_DIM_ALL_WINDOWS"]:
                return set(c for c in self.clients.values())
            elif tag == self.atoms["_DIM_EMPTY_TAGSET"]:
                return set()
            else:
                return self.tagsets.get(tag, set())
        if self.atoms["_DIM_ALL_TAGS"] in tags:
            tags = self.tagsets.keys()
        log.debug("Updating from tagsets %s." % map(self.atoms.name, tags))
        u = set(self.clients.values())
        s = reduce(function,
                   map(tagset, tags),
                   set(c for c in u if c.wm_state == WMState.NormalState))
        for c in u - s:
            c.unmap()
        for c in s:
            c.map()

    @handler([TagsetShow, TagsetUnion, TagsetIntersection, TagsetDifference])
    def handle_tagset_update(self, message):
        self.update_tagset(message.function, message.tags)
