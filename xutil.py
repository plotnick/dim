# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple
import operator
from struct import Struct

from xcb.xproto import *

__all__ = ["power_of_2", "popcount", "int16", "card16",
           "is_synthetic_event", "event_window",
           "configure_notify", "send_client_message",
           "select_values", "value_list", "textitem16",
           "GrabButtons", "GrabServer"]

def power_of_2(x):
    """Check whether x is a power of 2."""
    return isinstance(x, int) and x > 0 and x & (x - 1) == 0

def popcount(x):
    """Count the number of 1 bits in the binary representation of x."""
    return bin(x).count("1")

def int16(x):
    """Truncate an integer to 16 bits, ignoring sign."""
    return int(x) & 0xffff

def card16(x):
    """Truncate an unsigned integer to 16 bits."""
    assert x >= 0, "invalid cardinal %d" % x
    return int(x) & 0xffff

def sequence_number(event, struct=Struct("H")):
    """Return the sequence number of the given event."""
    # Every event type except KeymapNotify contains the low-order 16 bits
    # of the sequence number of the last request issued by the client at
    # an offset of 2 bytes.
    return (struct.unpack_from(event, 2)[0]
            if not isinstance(event, KeymapNotifyEvent)
            else None)

def is_synthetic_event(event):
    """Returns True if the given event was produced via a SendEvent request."""
    # Events begin with an 8-bit type code; synthetic events have the
    # most-significant bit of this code set.
    return (ord(event[0]) & 0x80) != 0

def event_window(event,
                 event_types={ButtonPressEvent: lambda e: e.event,
                              ButtonReleaseEvent: lambda e: e.event,
                              CirculateNotifyEvent: lambda e: e.event,
                              CirculateRequestEvent: lambda e: e.event,
                              ClientMessageEvent: lambda e: e.window,
                              ColormapNotifyEvent: lambda e: e.window,
                              ConfigureNotifyEvent: lambda e: e.event,
                              ConfigureRequestEvent: lambda e: e.parent,
                              CreateNotifyEvent: lambda e: e.parent,
                              DestroyNotifyEvent: lambda e: e.event,
                              EnterNotifyEvent: lambda e: e.event,
                              ExposeEvent: lambda e: e.window,
                              FocusInEvent: lambda e: e.event,
                              FocusOutEvent: lambda e: e.event,
                              GraphicsExposureEvent: lambda e: e.drawable,
                              GravityNotifyEvent: lambda e: e.event,
                              KeymapNotifyEvent: lambda e: None,
                              KeyPressEvent: lambda e: e.event,
                              KeyReleaseEvent: lambda e: e.event,
                              LeaveNotifyEvent: lambda e: e.event,
                              MapNotifyEvent: lambda e: e.event,
                              MappingNotifyEvent: lambda e: None,
                              MapRequestEvent: lambda e: e.parent,
                              MotionNotifyEvent: lambda e: e.event,
                              NoExposureEvent: lambda e: None,
                              PropertyNotifyEvent: lambda e: e.window,
                              ReparentNotifyEvent: lambda e: e.event,
                              ResizeRequestEvent: lambda e: e.window,
                              SelectionClearEvent: lambda e: e.owner,
                              SelectionNotifyEvent: lambda e: None,
                              SelectionRequestEvent: lambda e: e.owner,
                              UnmapNotifyEvent: lambda e: e.event,
                              VisibilityNotifyEvent: lambda e: e.window}):
    """Return the window on which the given event was generated."""
    return event_types.get(type(event), lambda e: None)(event)

def configure_notify(connection, window, x, y, width, height, border_width,
                     override_redirect=False,
                     formatter=Struct("bx2xIIIhhHHHB5x")):
    """Send a synthetic ConfigureNotify event to a window, as per ICCCM §4.1.5
    and §4.2.3."""
    assert formatter.size == 32
    return connection.core.SendEvent(False, window, EventMask.StructureNotify,
                                     formatter.pack(22, # code (ConfigureNotify)
                                                    window, # event
                                                    window, # window
                                                    0, # above-sibling: None
                                                    x, y, width, height,
                                                    border_width,
                                                    override_redirect))

def send_client_message(connection, destination, window, event_mask,
                        format, type, data,
                        formatters={8: Struct("bB2xII20B"),
                                    16: Struct("bB2xII10H"),
                                    32: Struct("bB2xII5I")}):
    """Send a ClientMessage event to a window.

    The format must be one of 8, 16, or 32, and the data must be a list of
    exactly 20, 10, or 5 values, respectively."""
    formatter = formatters[format]
    return connection.core.SendEvent(False, destination, event_mask,
                                     formatter.pack(33, # code (ClientMessage)
                                                    format,
                                                    window,
                                                    type,
                                                    *data))

def select_values(value_mask, values):
    """Create a value-list from the supplied possible values according to the
    bits in the given value-mask."""
    return [values[i] for i in range(len(values)) if value_mask & (1 << i)]

def value_list(flag_class, **kwargs):
    """Construct and return a value-mask and value-list from the supplied
    keyword arguments. The flag_class should be an object with attributes
    that define the flags for the possible values."""
    flags = {}
    for attr in dir(flag_class):
        if not attr.startswith("_"):
            value = getattr(flag_class, attr, None)
            if power_of_2(value):
                flags[attr.lower()] = value
    assert len(set(flags.values())) == len(flags), \
        "Duplicate flags in %s" % (flag_class.__name__ \
                                       if hasattr(flag_class, "__name__")
                                       else flag_class)
    
    values = [(value, flags[name.replace("_", "").lower()])
              for name, value in kwargs.items()]
    return (reduce(operator.or_, map(operator.itemgetter(1), values), 0),
            map(operator.itemgetter(0),
                sorted(values, key=operator.itemgetter(1))))

def textitem16(string):
    """Given a string, yield a sequence of TEXTITEM16 byte strings suitable
    for embedding in a PolyText16 request."""
    string = unicode(string)
    segments = [string[i:i + 254] for i in range(0, len(string), 254)]
    for segment in segments:
        string16 = array("H", segment.encode("UTF-16BE"))
        yield pack("BB", len(string16), 0) + string16.tostring()

class GrabButtons(dict):
    """Helper class for managing passive grabs established with GrabButton.

    Instances of this class will be dictionaries whose keys are tuples of
    the form (button, modifiers), and whose values are event masks."""

    def merge(self, other):
        """Given another dictionary, update this instance with any new entries
        and merge the event masks (i.e., compute the logical or) of entries
        with corresponding keys."""
        for key, mask in other.items():
            if key in self:
                self[key] |= mask
            else:
                self[key] = mask
        return self

class GrabServer(object):
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.core.GrabServer()
        self.conn.flush()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.core.UngrabServer()
        self.conn.flush()
