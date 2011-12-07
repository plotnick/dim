# -*- mode: Python; coding: utf-8 -*-

import itertools

from xcb.xproto import *

def all_combinations(lists):
    if lists:
        for x in lists[0]:
            for combo in all_combinations(lists[1:]):
                yield [x] + combo
    else:
        yield []

class Bindings(object):
    def __init__(self, bindings, keymap, modmap, butmap):
        self.bindings = bindings
        self.keymap = keymap
        self.modmap = modmap
        self.butmap = butmap

    def __getitem__(self, event):
        if isinstance(event, KeyPressEvent):
            self.key_binding(event.detail, event.state)
        elif isinstance(event, ButtonPressEvent):
            self.button_binding(event.detail, event.state)
        else:
            raise KeyError("unhandled event type")

    def key_binding(self, keycode, state):
        def mods(bit, keymap=self.keymap):
            if bit == KeyButMask.Shift:
                yield "shift"
            if bit == KeyButMask.Control:
                yield "control"
            if bit == keymap.meta:
                yield "meta"
            if bit == keymap.alt:
                yield "alt"
            if bit == keymap.super:
                yield "super"
            if bit == keymap.hyper:
                yield "hyper"
        mod_lists = filter(None,
                           (tuple(mods(bit))
                            for bit in (1 << i for i in range(8))))
        return mod_lists

    def button_binding(self, button, state):
        pass
