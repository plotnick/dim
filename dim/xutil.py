# -*- mode: Python; coding: utf-8 -*-

from array import array
from contextlib import contextmanager
from locale import getpreferredencoding
from struct import Struct
import sys

from xcb.xproto import *
import xcb.randr
import xcb.shape

from geometry import *

__all__ = ["int16", "card16",
           "decode_argv", "encode_argv",
           "compare_timestamps", "sequence_number", "is_synthetic_event",
           "event_window", "notify_detail_name", "notify_mode_name",
           "configure_notify", "send_client_message",
           "grab_server", "mask_events",
           "get_input_focus", "get_window_geometry",
           "query_extension", "query_pointer",
           "select_values", "string16", "textitem16",
           "client_message_type", "client_message", "ClientMessage"]

def int16(x):
    """Truncate an integer to 16 bits, ignoring sign."""
    return int(x) & 0xffff

def card16(x):
    """Truncate an unsigned integer to 16 bits."""
    assert x >= 0, "invalid cardinal %d" % x
    return int(x) & 0xffff

def decode_argv(argv=None, errors="replace"):
    """Given a list of argument byte strings (e.g., sys.argv), decode them
    in accordance with the current locale."""
    if argv is None:
        argv = sys.argv
    encoding = getpreferredencoding(True)
    return [arg.decode(encoding, errors) for arg in argv]

def encode_argv(argv, errors="backslashreplace"):
    """Given a list of arguments as Unicode strings, encode them in
    accordance with the current locale."""
    encoding = getpreferredencoding(True)
    return [arg.encode(encoding, errors) for arg in argv]

def compare_timestamps(x, y, half=0x80000000, CurrentTime=Time.CurrentTime):
    """Interpreted as timestamps, return negative if x precedes y,
    zero if x is coincident with y, and positive if x is after y."""
    # From the glossary of the X Protocol Reference Manual ("Timestamp"):
    # 
    #   The server, given its current time is represented by timestamp T,
    #   always interprets timestamps from clients by treating half of the
    #   timestamp space as being earlier in time than T and half of the
    #   timestamp space as being later in time than T."""
    assert x >= 0 and y >= 0
    if x == CurrentTime:
        return y
    if y == CurrentTime:
        return -x
    d = x - y
    return d if abs(d) <= half else -d

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

event_window_types = {
    # Core events (complete).
    ButtonPressEvent: lambda e: e.event,
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
    VisibilityNotifyEvent: lambda e: e.window,

    # Extension events (only as needed).
    xcb.randr.NotifyEvent: lambda e: \
        (e.u.cc.window if e.subCode == xcb.randr.Notify.CrtcChange else
         e.u.oc.window if e.subCode == xcb.randr.Notify.OutputChange else
         e.u.op.window if e.subCode == xcb.randr.Notify.OutputProperty else
         None),
    xcb.shape.NotifyEvent: lambda e: e.affected_window
}

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

def notify_mode_name(event, modes={0: "Normal",
                                   1: "Grab",
                                   2: "Ungrab",
                                   3: "WhileGrabbed"}):
    """Return a string naming the mode of the given event."""
    return modes[event.mode]

def configure_notify(connection, window, x, y, width, height, border_width,
                     above_sibling=Window._None,
                     override_redirect=False,
                     formatter=Struct("bx2xIIIhhHHHB5x"),
                     code=22): # ConfigureNotify
    """Send a synthetic ConfigureNotify event to a window (ICCCM §4.2.3)."""
    return connection.core.SendEvent(False, window, EventMask.StructureNotify,
                                     formatter.pack(code,
                                                    window,
                                                    window,
                                                    above_sibling,
                                                    x, y, width, height,
                                                    border_width,
                                                    bool(override_redirect)))

def send_client_message(connection, destination, propagate, event_mask,
                        window, type, format, data,
                        formatters={8: Struct("bB2xII20B"),
                                    16: Struct("bB2xII10H"),
                                    32: Struct("bB2xII5I")},
                        code=33): # ClientMessage
    """Send a ClientMessage event to a window.

    The format must be one of 8, 16, or 32, and the data must be a sequence
    of exactly 20, 10, or 5 values, respectively."""
    event = formatters[format].pack(code, format, window, type, *data)
    return connection.core.SendEvent(bool(propagate), destination,
                                     event_mask, event)

@contextmanager
def grab_server(connection):
    """A context manager that executes its body with the server grabbed."""
    connection.core.GrabServer()
    try:
        yield
    finally:
        connection.core.UngrabServer()

@contextmanager
def mask_events(connection, window, event_mask, bits, checked=False):
    """A context manager that executes its body with certain bits masked
    out of the window's event mask."""
    if checked:
        def change_event_mask(mask):
            connection.core.ChangeWindowAttributesChecked(window,
                                                          CW.EventMask,
                                                          [mask]).check()
    else:
        def change_event_mask(mask):
            connection.core.ChangeWindowAttributes(window, CW.EventMask, [mask])
    change_event_mask(event_mask & ~bits)
    try:
        yield
    finally:
        change_event_mask(event_mask)

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
    except BadDrawable:
        return None
    return Geometry(reply.x, reply.y,
                    reply.width, reply.height,
                    reply.border_width)

def query_extension(connection, name, key):
    """Query the server for the extension with the given name, and, if present,
    return the corresponding extension handle."""
    ext = connection.core.QueryExtension(len(name), name).reply()
    return connection(key) if ext.present else None

def query_pointer(connection, screen):
    """Return the current pointer position."""
    if isinstance(screen, int):
        screen = connection.get_setup().roots[screen]
    reply = connection.core.QueryPointer(screen.root).reply()
    return Position(reply.root_x, reply.root_y)

def select_values(value_mask, values):
    """Create a value-list from the supplied possible values according to the
    bits in the given value-mask."""
    return [values[i] for i in range(len(values)) if value_mask & (1 << i)]

def string16(string):
    """Encode the given string as a list of CHAR2B values."""
    return [array("B", char.encode("UTF-16BE")) for char in unicode(string)]

def textitem16(string, pack_header=Struct("Bx").pack):
    """Given a string, yield a sequence of TEXTITEM16s suitable for embedding
    in a PolyText16 request. Does not support font switching or deltas."""
    string = unicode(string)
    for segment in (string[i:i + 254] for i in xrange(0, len(string), 254)):
        string16 = segment.encode("UTF-16BE")
        yield pack_header(len(string16) // 2) + string16

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
    """Pseudo-event class for client messages."""
    def __init__(self, window, format, data):
        self.window = window
        self.format = format
        self.data = data
