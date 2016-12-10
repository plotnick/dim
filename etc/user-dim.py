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

# Use Unicode versions of the standard fonts for titles & minibuffers.
default_options.update({
    "title_font": "10x20U",
    "minibuffer_font": "10x20U"
})

# Extra (inet) keys
XK_XF86AudioMute = 0x1008ff12
XK_XF86AudioLowerVolume = 0x1008ff11
XK_XF86AudioRaiseVolume = 0x1008ff13
XK_XF86AudioPlay = 0x1008ff14
XK_XF86AudioStop = 0x1008ff15
XK_XF86AudioPrev = 0x1008ff16
XK_XF86AudioNext = 0x1008ff17
XK_XF86AudioMicMute = 0x1008ffb2
XK_XF86MonBrightnessDown = 0x1008ff03
XK_XF86MonBrightnessUp = 0x1008ff02
XK_XF86Display = 0x1008ff59
XK_XF86WLAN = 0x1008ff95
XK_XF86Tools = 0x1008ff81
XK_XF86Search = 0x1008ff1b
XK_XF86LaunchA = 0x1008ff4a
XK_XF86Explorer = 0x1008ff5d

# Buttons & gestures from Logitech T650 with xinput(1).
two_finger_swipe_up = 4
two_finger_swipe_down = 5
two_finger_swipe_left = 6
two_finger_swipe_right = 7
three_finger_swipe_up = 10   # 8
three_finger_swipe_down = 11 # 9
three_finger_swipe_left = 8  # 10
three_finger_swipe_right = 9 # 11
four_finger_swipe_up = 16
four_finger_swipe_down = 17
four_finger_swipe_left = 18
four_finger_swipe_right = 19

def mixer(command):
    "A trivial wrapper for amixer(1)."
    spawn("amixer set %s" % command)

global_key_bindings = {
    ("control", XK_Pause): BaseWM.debug, # Break
    -XK_Pause: BaseWM.activate_screen_saver,
    XK_Menu: BaseWM.change_tagset,

    ("super", XK_slash): BaseWM.change_tagset,
    ("super", XK_space): BaseWM.shell_command,
    ("super", XK_Tab): BaseWM.start_focus_cycle_next,
    ("super", XK_ISO_Left_Tab): BaseWM.start_focus_cycle_prev,
    ("super", XK_period): BaseWM.start_focus_cycle_warp,
    ("super", XK_F11): BaseWM.fullscreen,
    ("super", XK_Right): BaseWM.hmax,
    ("super", XK_Left): BaseWM.hmax,
    ("super", XK_Up): BaseWM.vmax,
    ("super", XK_Down): BaseWM.vmax,
    ("super", XK_equal): BaseWM.tmax,
    ("super", XK_minus): BaseWM.umax,
    ("super", XK_Next): BaseWM.next_head,
    ("super", XK_Prior): BaseWM.previous_head,
    ("super", XK_Delete): BaseWM.delete_window,

    ("super", "shift", XK_Up): RaiseLower.raise_window,
    ("super", "shift", XK_Down): RaiseLower.lower_window,

    ("super", XK_x): BaseWM.terminal,
    ("super", XK_b): BaseWM.battery,
    ("super", XK_c): BaseWM.calculator,
    ("super", XK_e): BaseWM.editor,
    ("super", XK_l): BaseWM.dictionary,
    ("super", XK_m): BaseWM.mail,
    ("super", XK_n): BaseWM.nomail,
    ("super", XK_r): BaseWM.refresh,
    ("super", XK_s): BaseWM.ssh,
    ("super", XK_t): BaseWM.top,
    ("super", XK_w): BaseWM.www,
    ("super", XK_z): BaseWM.zzz,

    XK_XF86AudioStop: lambda wm, event: spawn("xmms2 stop"),
    XK_XF86AudioPrev: lambda wm, event: spawn("xmms2 prev"),
    XK_XF86AudioPlay: lambda wm, event: spawn("xmms2 toggle"),
    XK_XF86AudioNext: lambda wm, event: spawn("xmms2 next"),
    XK_XF86AudioMute: lambda wm, event: mixer("Master toggle"),
    XK_XF86AudioLowerVolume: lambda wm, event: mixer("Master 5%-,5%-"),
    XK_XF86AudioRaiseVolume: lambda wm, event: mixer("Master 5%+,5%+"),
    XK_XF86AudioMicMute: lambda wm, event: mixer("Capture toggle"),
    XK_XF86MonBrightnessUp: BaseWM.inc_backlight,
    XK_XF86MonBrightnessDown: BaseWM.dec_backlight,
    XK_XF86Display: lambda wm, event: spawn("cheese")
}

global_button_bindings = {
    ("super", 1): MoveResize.move_window,
    ("super", 3): MoveResize.resize_window,
    ("super", 4): MoveResize.roll_window,
    ("super", 5): MoveResize.roll_window,
    ("super", 6): MoveResize.roll_window,
    ("super", 7): MoveResize.roll_window,
    ("super", "shift", 1): RaiseLower.raise_window,
    ("super", "shift", 3): RaiseLower.lower_window,
    ("super", three_finger_swipe_right): BaseWM.start_focus_cycle_next,
    ("super", three_finger_swipe_left): BaseWM.start_focus_cycle_prev,
    three_finger_swipe_up: RaiseLower.raise_window,
    three_finger_swipe_down: RaiseLower.lower_window,
    four_finger_swipe_up: BaseWM.tmax,
    four_finger_swipe_down: BaseWM.vmax,
    four_finger_swipe_left: BaseWM.tmax,
    four_finger_swipe_right: BaseWM.hmax
}

focus_cycle_button_bindings.update({
    three_finger_swipe_up: CycleFocus.raise_target_window,
    three_finger_swipe_down: CycleFocus.lower_target_window,
    three_finger_swipe_left: CycleFocus.cycle_focus_prev,
    three_finger_swipe_right: CycleFocus.cycle_focus_next
})
