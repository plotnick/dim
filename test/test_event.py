# -*- mode: Python; coding: utf-8 -*-

import unittest

from event import *

class Event(object):
    def __init__(self):
        self.handled_by = []

class FooEvent(Event): pass
class BarEvent(Event): pass
class BazEvent(Event): pass
class QuuxEvent(Event): pass

class FooHandler(EventHandler):
    @handler(FooEvent)
    def handle_foo(self, event):
        event.handled_by += [FooHandler]

class BarHandler(FooHandler):
    @handler(BarEvent)
    def handle_bar(self, event):
        event.handled_by += [BarHandler]

class BazHandler(BarHandler):
    @handler(FooEvent)
    def handle_foo(self, event):
        event.handled_by += [BazHandler]

    @handler(BarEvent)
    def handle_bar(self, event):
        event.handled_by += [BazHandler]
        raise StopPropagation(event)

    @handler(QuuxEvent)
    def handle_quux(self, event):
        event.handled_by += [BazHandler]

    def unhandled_event(self, event):
        return False

class QuuxHandler(EventHandler):
    @handler(QuuxEvent)
    def handle_quux(self, event):
        event.handled_by += [QuuxHandler]

class SuperHandler(BazHandler, QuuxHandler):
    pass

class MultiHandler(EventHandler):
    @handler((FooEvent, BarEvent, BazEvent))
    def handle_foo_bar_baz(self, event):
        event.handled_by = [MultiHandler]

class TestEventHandler(unittest.TestCase):
    def test_base_handler(self):
        """Basic event dispatch and handling"""
        handler = FooHandler()
        foo = FooEvent(); handler.handle_event(foo)
        self.assertEqual(foo.handled_by, [FooHandler])
        self.assertRaises(UnhandledEvent,
                          lambda: handler.handle_event(BarEvent()))

    def test_derived_handler(self):
        """Inheritance of event handlers"""
        handler = BarHandler()
        foo = FooEvent(); handler.handle_event(foo)
        bar = BarEvent(); handler.handle_event(bar)
        self.assertEqual(foo.handled_by, [FooHandler])
        self.assertEqual(bar.handled_by, [BarHandler])

    def test_default_event_handler(self):
        """Default event handler"""
        handler = BazHandler()
        baz = BazEvent(); handler.handle_event(baz)
        self.assertFalse(baz.handled_by)

    def test_propagation(self):
        """Event propagation"""
        handler = BazHandler()
        foo = FooEvent(); handler.handle_event(foo)
        self.assertEqual(foo.handled_by, [BazHandler, FooHandler])

    def test_stop_propagation(self):
        """Stop propagation"""
        handler = BazHandler()
        bar = BarEvent(); handler.handle_event(bar)
        self.assertEqual(bar.handled_by, [BazHandler])

    def test_super_handler(self):
        """Multiple superclass handler inheritance"""
        handler = SuperHandler()
        quux = QuuxEvent(); handler.handle_event(quux)
        self.assertEqual(quux.handled_by, [BazHandler, QuuxHandler])

    def test_multi_handler(self):
        """One handler for many event types"""
        handler = MultiHandler()
        foo = FooEvent(); handler.handle_event(foo)
        bar = BarEvent(); handler.handle_event(bar)
        baz = BazEvent(); handler.handle_event(baz)
        self.assertEqual(foo.handled_by, [MultiHandler])
        self.assertEqual(bar.handled_by, [MultiHandler])
        self.assertEqual(baz.handled_by, [MultiHandler])
        self.assertRaises(UnhandledEvent,
                          lambda: handler.handle_event(QuuxEvent()))

if __name__ == "__main__":
    unittest.main()
