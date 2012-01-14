# -*- mode: Python; coding: utf-8 -*-

from collections import namedtuple
from contextlib import contextmanager
import operator
from struct import Struct

from xcb.xproto import *

from geometry import *

__all__ = ["power_of_2", "popcount", "int16", "card16",
           "sequence_number", "is_synthetic_event",
           "event_window", "notify_detail_name",
           "configure_notify", "send_client_message", "grab_server",
           "get_input_focus", "get_window_geometry", "query_pointer",
           "select_values", "value_list", "textitem16", "GrabButtons",
           "client_message_type", "client_message", "ClientMessage"]

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

event_window_types = {ButtonPressEvent: lambda e: e.event,
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
                      VisibilityNotifyEvent: lambda e: e.window}

def event_window(event):
    """Return the window on which the given event was generated."""
    return event_window_types.get(type(event), lambda e: None)(event)

def notify_detail_name(event, detail={0: "Ancestor",
                                      1: "Virtual",
                                      2: "Inferior",
                                      3: "Nonlinear",
                                      4: "NonlinearVirtual",
                                      5: "Pointer",
                                      6: "PointerRoot",
                                      7: "None"}):
    """Return a string naming the detail code of the given event."""
    return detail[event.detail]

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

@contextmanager
def grab_server(connection):
    """A context manager that executes its body with the server grabbed."""
    connection.core.GrabServer()
    try:
        yield
    finally:
        connection.core.UngrabServer()

def get_input_focus(connection, screen=None):
    """Return the window that has the input focus."""
    focus = connection.core.GetInputFocus().reply().focus
    if focus == InputFocus.PointerRoot:
        # If we're in PointerRoot mode, we need to query the server
        # again for the window currently containing the pointer.
        if screen is None:
            screen = connection.pref_screen
        if isinstance(screen, int):
            screen = connection.get_setup().roots[screen]
        return connection.core.QueryPointer(screen.root).reply().child
    else:
        return focus

def get_window_geometry(connection, window):
    """Request a window's geometry from the X server and return it as a
    Geometry instance."""
    cookie = connection.core.GetGeometry(window)
    try:
        reply = cookie.reply()
    except BadWindow:
        return None
    return Geometry(reply.x, reply.y,
                    reply.width, reply.height,
                    reply.border_width)

def query_pointer(connection, root):
    """Return the current pointer position relative to the given root window."""
    reply = connection.core.QueryPointer(root).reply()
    return Position(reply.root_x, reply.root_y)

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

def textitem16(string, pack_header=Struct("Bx").pack):
    """Given a string, yield a sequence of TEXTITEM16s suitable for embedding
    in a PolyText16 request. Does not support font switching or deltas."""
    string = unicode(string)
    for segment in (string[i:i + 254] for i in xrange(0, len(string), 254)):
        string16 = segment.encode("UTF-16BE")
        yield pack_header(len(string16) // 2) + string16

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

client_message_types = {}

def client_message_type(type_name):
    """Look up a type name in the table of registered client message types."""
    return client_message_types[type_name]

def client_message(type_name):
    """A class decorator factory that registers a client message type."""
    def register_client_message_type(cls):
        client_message_types[type_name] = cls
        event_window_types[cls] = lambda e: e.window
        return cls
    return register_client_message_type

class ClientMessage(object):
    def __init__(self, window, format, data):
        self.window = window
        self.format = format
        self.data = data
