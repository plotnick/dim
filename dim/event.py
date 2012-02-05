# -*- mode: Python; coding: utf-8 -*-

"""Event handling utilities."""

from collections import defaultdict

class StopPropagation(Exception):
    """Raised by an event handler to signal that no further handlers should
    be invoked for the given event."""
    pass

class UnhandledEvent(Exception):
    """Raised by the default event handler."""
    def __init__(self, event, *args):
        self.event = event
        super(UnhandledEvent, self).__init__(*args)

def handler(event_classes):
    """A decorator factory for event handling methods. Requires that the
    metaclass be EventHandler or a subclass thereof.

    Usage:
        class C(EventHandler):
            @handler(FooEvent)
            def handle_foo(self, event):
                ...
    The event_classes argument is a designator for a sequence of event types;
    the decorated method will be registered as a handler for each one."""
    def set_handler(method):
        try:
            method.handler_for = tuple(event_classes)
        except TypeError:
            method.handler_for = (event_classes,)
        return method
    return set_handler

class EventHandlerClass(type):
    """Metaclass supporting handler registration via @handlers decorator."""

    def __new__(metaclass, name, bases, namespace):
        cls = super(EventHandlerClass, metaclass).__new__(metaclass, name,
                                                          bases, namespace)
        cls.__handlers__ = defaultdict(list)
        for method in filter(callable, namespace.values()):
            for event_class in getattr(method, "handler_for", ()):
                cls.__handlers__[event_class] += [method]
        return cls

class EventHandler(object):
    """Base class supporting automatically registered handler methods."""

    __metaclass__ = EventHandlerClass

    def handle_event(self, event):
        """Dispatch an event to all handlers registered for that type.

        Handlers are run in method resolution order. If any handler raises
        a StopPropagation exception, no further handlers are invoked. If no
        handlers are found, the unhandled_event method is called.

        Subclasses may, but generally should not, override this method."""
        event_class = type(event)
        handled = False
        for cls in self.__class__.__mro__:
            try:
                handlers = cls.__handlers__[event_class]
            except (AttributeError, KeyError):
                continue
            for handler in handlers:
                try:
                    handler(self, event)
                    handled = True
                except StopPropagation:
                    return
        if not handled:
            return self.unhandled_event(event)

    def unhandled_event(self, event):
        """Handle an event for which no other handler has been registered.
        Subclasses may, and generally should, override this method."""
        raise UnhandledEvent(event)
