# -*- mode: Python; coding: utf-8 -*-

"""Event handling utilities."""

class UnhandledEvent(Exception):
    pass

def handler(event_classes):
    """A decorator factory for event handling methods. Requires that the
    metaclass be EventHandler or a subclass thereof.

    Usage:
        class C(EventHandler):
            @handler(FooEvent)
            def handle_foo(self, event):
                ...
    If a handler method returns normally, it is assumed to have handled the
    event. A handler may decline to handle an event by raising an UnhandledEvent
    exception. In that case, the next registered handler (or the default handler
    if no more handlers are available) will be invoked."""
    def set_handler(method):
        method.__handler_for__ = event_classes \
            if isinstance(event_classes, (list, tuple)) \
            else (event_classes,)
        return method
    return set_handler

class EventHandlerClass(type):
    """Metaclass supporting handler registration via @handlers decorator."""

    def __new__(metaclass, name, bases, namespace):
        cls = super(EventHandlerClass, metaclass).__new__(metaclass, name,
                                                          bases, namespace)
        cls.__handlers__ = {}
        for base in bases:
            for ev, handlers in getattr(base, "__handlers__", dict()).items():
                cls.__handlers__[ev] = cls.__handlers__.get(ev, []) + handlers
        for obj in filter(callable, namespace.values()):
            for ev in getattr(obj, "__handler_for__", ()):
                cls.__handlers__[ev] = [obj] + cls.__handlers__.get(ev, [])
        return cls

class EventHandler(object):
    """Base class supporting automatically registered handler methods."""

    __metaclass__ = EventHandlerClass

    def handle_event(self, event):
        """Dispatch an event to the registered handler. Subclasses may, but
        generally should not, override this method."""
        try:
            handlers = self.__handlers__[type(event)]
        except KeyError:
            return self.unhandled_event(event)
        for handler in handlers:
            try:
                return handler(self, event)
            except UnhandledEvent:
                # Handler declined to handle the event; try the next one.
                pass
        else:
            return self.unhandled_event(event)

    def unhandled_event(self, event):
        """Handle an event for which no specific handler has been registered.
        Subclasses may freely override this method."""
        raise UnhandledEvent(event)
