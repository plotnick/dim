# -*- mode: Python; coding: utf-8 -*-

import unittest

from event import *

class Event(object):
    def __init__(self):
        self.handled = False

class FooEvent(Event): pass
class BarEvent(Event): pass
class BazEvent(Event): pass
class QuxEvent(Event): pass

class FooHandler(EventHandler):
    @handler(FooEvent)
    def handle_foo(self, event):
        event.handled = True
        return event

class BarHandler(FooHandler):
    @handler(BarEvent)
    def handle_bar(self, event):
        event.handled = True
        return event

class BazHandler(BarHandler):
    @handler(BarEvent)
    def decline_handle_bar(self, event):
        event.declined = True
        raise UnhandledEvent(event)

    @handler(QuxEvent)
    def decline_handle_qux(self, event):
        event.declined = True
        raise UnhandledEvent(event)

    def unhandled_event(self, event):
        return False

class TestEventHandler(unittest.TestCase):
    def test_base_handler(self):
        """Test basic event dispatch and handling"""
        foo_handler = FooHandler()
        self.assertTrue(foo_handler.handle_event(FooEvent()).handled)
        self.assertRaises(UnhandledEvent,
                          lambda: foo_handler.handle_event(BarEvent()))

    def test_derived_handler(self):
        """Test inheritance of event handling"""
        bar_handler = BarHandler()
        self.assertTrue(bar_handler.handle_event(FooEvent()).handled)
        self.assertTrue(bar_handler.handle_event(BarEvent()).handled)

    def test_default_event_handler(self):
        """Test default event handler"""
        baz_handler = BazHandler()
        baz = BazEvent()
        self.assertEqual(baz_handler.handle_event(baz), False)
        self.assertFalse(baz.handled)

    def test_declined_handler(self):
        """Test declined handler"""
        baz_handler = BazHandler()
        bar = BarEvent()
        self.assertEqual(baz_handler.handle_event(bar), bar)
        self.assertTrue(bar.declined)
        self.assertTrue(bar.handled)

    def test_unhandled_decline(self):
        """Test decline of last applicable handler"""
        baz_handler = BazHandler()
        qux = QuxEvent()
        self.assertEqual(baz_handler.handle_event(qux), False)
        self.assertTrue(qux.declined)
        self.assertFalse(qux.handled)

if __name__ == "__main__":
    unittest.main()
