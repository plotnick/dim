"""Event handling utilities."""

class UnhandledEvent(Exception):
    pass

def handler(event_class):
    """A decorator factory for event handling methods. Requires that the
    metaclass be EventHandler or a subclass thereof.

    Usage:
        class C(EventHandler):
            @handler(FooEvent)
            def handle_foo(self, event):
                ...
    """
    def set_handler(method):
        method.__handler_for__ = event_class
        return method
    return set_handler

class EventHandlerClass(type):
    """Metaclass supporting handler registration via @handlers decorator."""

    def __new__(metaclass, name, bases, namespace):
        cls = super(EventHandlerClass, metaclass).__new__(metaclass, name,
                                                          bases, namespace)
        cls.__handlers__ = {}
        for base in bases:
            cls.__handlers__.update(getattr(base, "__handlers__", dict()))
        for x in namespace.values():
            event_class = getattr(x, "__handler_for__", None)
            if event_class:
                cls.__handlers__[event_class] = x
        return cls

class EventHandler(object):
    """Base class supporting automatically registered handler methods."""

    __metaclass__ = EventHandlerClass

    def handle_event(self, event):
        """Dispatch an event to the registered handler. Subclasses may, but
        generally should not, override this method."""
        try:
            self.__handlers__[type(event)](self, event)
        except KeyError:
            self.unhandled_event(event)

    def unhandled_event(self, event):
        """Handle an event for which no specific handler has been registered.
        Subclasses may freely override this method."""
        raise UnhandledEvent, event
