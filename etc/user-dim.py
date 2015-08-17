# -*- mode: Python; coding: utf-8 -*-

"""DIM OF THE YARD!

The file ~/.dim.py is executed early in the Dim startup sequence in order
to support user-specific customizations.

This sample user script contains the author's personal settings for his
primary workstation. It is therefore unlikely to be of direct use to anyone
else, but it is hoped that it can serve as a model for a few of the many
kinds of customizations possible."""

__author__ = "Alex Plotnick <shrike@netaxs.com>"

from dim.client import Client
from dim.decorator import Decorator
from dim.manager import client_selector, decorator_selector
from dim.tags import intern_tagset_expr, parse_tagset_spec

class IgnoreBindingsClient(Client):
    """A client class that does not establish any key or button grabs.

    WARNING: If such a client becomes the only one available to receive
    the keyboard focus, it may be difficult to resume full window manager
    functionality."""
    def establish_grabs(self, *args, **kwargs):
        pass

@client_selector
def ignore_bindings(client, class_names=("Vncviewer", "Xephyr")):
    if client.wm_class.class_name in class_names:
        return IgnoreBindingsClient

@decorator_selector
def trivial_decoration(client, class_names=("XClock", "XEyes")):
    if client.wm_class.class_name in class_names:
        return Decorator

class UserManager(BaseWM):
    """Override and extend the built-in window manager functionality."""

    def __init__(self, *args, **kwargs):
        super(UserManager, self).__init__(*args, **kwargs)

        # Define a tagset alias for the browser and mail windows.
        self.tagset(r"z={www|mail}", show=False)

    def tagset(self, spec, show=True):
        """Parse and execute a tagset specification directly. This method
        does not send the expression via a property of the root window;
        rather, it feeds it directly into the tag machine."""
        expr = parse_tagset_spec(spec) + (["_DIM_TAGSET_SHOW"] if show else [])
        self.tag_machine.run(intern_tagset_expr(self.conn, expr,
                                                atoms=self.atoms))

    def show_mail(self, event):
        """Show, focus, and raise the mail window."""
        # I use an xterm(1) whose instance name is set to "mail".
        # You might use something different. If so, you'll probably
        # have to change the tag specs, too.
        def is_mail_client(client):
            return client.wm_class.instance_name == "mail"
        try:
            mail = next(self.find_clients(is_mail_client))
        except StopIteration:
            return
        self.tagset(r".|mail")
        self.ensure_focus(mail, event.time)
        mail.configure(stack_mode=StackMode.TopIf)

    def no_mail(self, event):
        """Hide the mail client."""
        self.tagset(r".\mail")
        self.ensure_focus()

# Use Unicode versions of the standard fonts for titles & minibuffers.
default_options.update({
    "title_font": "6x13U",
    "minibuffer_font": "10x20U"
})

# You can have my genuine IBM Model M when you noisily pry it from my cold,
# dead hands. But it has only the standard complement of modifier keys,
# and so choosing window manager key bindings that don't interfere with
# client applications can be tricky. Emacs, especially, seems to just
# gobble every possible key combination involving Control and Alt/Meta.
# Users with modifiers to spare are encouraged to experiment with the idea
# of dedicating an entire bucky bit (Hyper or Super) to Dim, and leaving
# Control and Alt to the clients.
global_key_bindings.update({
    # Control-` serves as a prefix key for a little submap of mnemonics and
    # miscellaneous shortcuts. The backtick is meant to suggest execution in
    # the Unix shell; it's also a conveniently located but underutilized key.
    ("control", XK_grave): {
        XK_Pause: lambda wm, event: spawn("xmms2 toggle"),
        XK_space: lambda wm, event: spawn("xterm"),
        XK_b: lambda wm, event: spawn("xbat"),
        XK_c: lambda wm, event: spawn("xcalc"),
        XK_e: lambda wm, event: spawn("emacsclient -nc"),
        XK_m: UserManager.show_mail,
        ("shift", XK_M): UserManager.no_mail
    }
})

# The Logitech T650 touchpad has two physical buttons (micro-switches)
# located beneath a big honkin' slab o' slippery glass. In addition to
# tap-to-click, it recognizes a handful of one-, two-, and three-finger
# gestures compatible with Windows 8; for details, see
# <http://franklinstrube.com/blog/logitech-t650-wireless-touchpad-ubuntu/>.
# Note that despite being a pointing device, the events generated for some
# of those are keycodes (possibly with modifiers), not button presses.
# Also note that I've bound keycode 206 to Hyper instead of XF86TouchpadOff.
right_edge_swipe = ("control", "super", XK_Hyper_L)
left_edge_swipe = ("alt", "super", XK_BackSpace)
top_edge_swipe = ("alt", "super", XK_Hyper_L)
two_finger_swipe_up = 4
two_finger_swipe_down = 5
two_finger_swipe_left = 13
two_finger_swipe_right = 14
three_finger_swipe_left = 8
three_finger_swipe_right = 9
three_finger_swipe_up = (XK_Super_L,)
three_finger_swipe_down = ("super", XK_d)

global_key_bindings.update({
    top_edge_swipe: BaseWM.vmax,
    right_edge_swipe: BaseWM.tmax,
    left_edge_swipe: BaseWM.hmax,
    three_finger_swipe_up: RaiseLower.raise_window,
    three_finger_swipe_down: RaiseLower.lower_window,
})

global_button_bindings.update({
    ("alt", three_finger_swipe_right): BaseWM.start_focus_cycle_next,
    ("alt", three_finger_swipe_left): BaseWM.start_focus_cycle_prev,
})

focus_cycle_button_bindings.update({
    three_finger_swipe_right: CycleFocus.cycle_focus_next,
    three_finger_swipe_left: CycleFocus.cycle_focus_prev
})

focus_cycle_key_bindings.update({
    three_finger_swipe_up: CycleFocus.raise_target_window,
    three_finger_swipe_down: CycleFocus.lower_target_window
})
