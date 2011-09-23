import unittest

from event import *

class Event(object):
    def __init__(self):
        self.handled = False

class FooEvent(Event): pass
class BarEvent(Event): pass
class BazEvent(Event): pass

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
    def unhandled_event(self, event):
        return None

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
        baz_event = BazEvent()
        self.assertEqual(baz_handler.handle_event(baz_event), None)
        self.assertFalse(baz_event.handled)

if __name__ == "__main__":
    unittest.main()
