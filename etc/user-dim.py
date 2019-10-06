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

class UserWM(BaseWM):
    """Override and extend the built-in window manager functionality
    by defining new event handlers for custom commands."""

    def __init__(self, *args, **kwargs):
        super(UserWM, self).__init__(*args, **kwargs)

        # Define a tagset alias for the browser and mail windows.
        self.tagset(r"z={www|mail}", show=False)

    def next_head(self, event):
        """Move the currently focused window to the next head."""
        self.heads.move_client(self.current_focus, +1)

    def previous_head(self, event):
        """Move the currently focused window to the previous head."""
        self.heads.move_client(self.current_focus, -1)

    def browser(self, event):
        """Focus & raise the most recently focused visible browser window."""
        def is_visible_browser(client):
            return (client.wm_state == WMState.NormalState and
                    client.wm_window_role == "browser")
        try:
            browser = next(self.find_focus_clients(is_visible_browser))
        except StopIteration:
            return
        self.ensure_focus(browser, event.time)
        browser.configure(stack_mode=StackMode.TopIf)

    def mail(self, event):
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

    def nomail(self, event):
        """Hide the mail client."""
        self.tagset(r".\mail")
        self.ensure_focus(None, event.time)

    def inc_backlight(self, event):
        """Make the primary output's backlight brighter."""
        try:
            self.heads.adjust_backlight(self.heads.primary_output, 5, "inc")
        except AttributeError:
            return

    def dec_backlight(self, event):
        """Make the primary output's backlight dimmer."""
        try:
            self.heads.adjust_backlight(self.heads.primary_output, 5, "dec")
        except AttributeError:
            return

    def battery(self, event):
        spawn("xbat -d", True) # shell function

    def calculator(self, event):
        spawn("xcalc")

    def editor(self, event):
        spawn("emacsclient -nc")

    def refresh(self, event):
        spawn("xrefresh")

    def ssh(self, event):
        spawn("xterm -e ssh home")

    def terminal(self, event):
        spawn("xterm")

    def top(self, event):
        spawn("xterm -e top")

    def dictionary(self, event):
        "Look up the selected word in the dictionary."
        def lookup(string):
            spawn('dict "%s" 2>&1 | xmessage -nearmouse -file -' % \
                  shquote(string.strip()))
        self.call_with_primary_selection(lookup,
                                         requestor=self.default_focus_window,
                                         time=event.time)

    def www(self, event,
            scheme=re.compile(r"^(https?|ftp|file)://", re.IGNORECASE),
            spaces=re.compile(r"\s+", re.UNICODE),
            angles=re.compile(r"<([^>]+)>"),
            quotes=re.compile(r'"([^"]+)"')):
        """Invoke a web browser with the selected URI.
        See RFC 3986, Appendix C: Delimiting a URI in Context."""
        def browse(string):
            string = spaces.sub("", string)
            delims = angles.match(string) or quotes.match(string)
            string = delims.group(1) if delims else string
            spawn('x-www-browser "%s"' % shquote(string) if scheme.match(string)
                  else "x-www-browser")
        self.call_with_primary_selection(browse,
                                         requestor=self.default_focus_window,
                                         time=event.time)

    def zzz(self, event):
        spawn("zzz", True) # command on BSD, alias on GNU/Linux

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
    ("control", XK_Pause): UserWM.debug, # Break
    -XK_Pause: UserWM.activate_screen_saver,
    XK_Menu: UserWM.change_tagset,

    ("super", XK_slash): UserWM.change_tagset,
    ("super", XK_space): UserWM.shell_command,
    ("super", XK_Tab): UserWM.start_focus_cycle_next,
    ("super", XK_ISO_Left_Tab): UserWM.start_focus_cycle_prev,
    ("super", XK_period): UserWM.start_focus_cycle_warp,
    ("super", XK_F11): UserWM.fullscreen,
    ("super", XK_Right): UserWM.hmax,
    ("super", XK_Left): UserWM.hmax,
    ("super", XK_Up): UserWM.vmax,
    ("super", XK_Down): UserWM.vmax,
    ("super", XK_equal): UserWM.tmax,
    ("super", XK_minus): UserWM.umax,
    ("super", XK_Next): UserWM.next_head,
    ("super", XK_Prior): UserWM.previous_head,
    ("super", XK_Delete): UserWM.delete_window,
    ("super", XK_BackSpace): UserWM.delete_window,

    ("super", "shift", XK_Up): RaiseLower.raise_window,
    ("super", "shift", XK_Down): RaiseLower.lower_window,

    ("super", XK_apostrophe): UserWM.browser,
    ("super", XK_x): UserWM.terminal,
    ("super", XK_b): UserWM.battery,
    ("super", XK_c): UserWM.calculator,
    ("super", XK_e): UserWM.editor,
    ("super", XK_l): UserWM.dictionary,
    ("super", XK_m): UserWM.mail,
    ("super", XK_n): UserWM.nomail,
    ("super", XK_r): UserWM.refresh,
    ("super", XK_s): UserWM.ssh,
    ("super", XK_t): UserWM.top,
    ("super", XK_w): UserWM.www,
    ("super", XK_z): UserWM.zzz,

    XK_XF86AudioStop: lambda wm, event: spawn("xmms2 stop"),
    XK_XF86AudioPrev: lambda wm, event: spawn("xmms2 prev"),
    XK_XF86AudioPlay: lambda wm, event: spawn("xmms2 toggle"),
    XK_XF86AudioNext: lambda wm, event: spawn("xmms2 next"),
    XK_XF86AudioMute: lambda wm, event: mixer("Master toggle"),
    XK_XF86AudioLowerVolume: lambda wm, event: mixer("Master 5%-,5%-"),
    XK_XF86AudioRaiseVolume: lambda wm, event: mixer("Master 5%+,5%+"),
    XK_XF86AudioMicMute: lambda wm, event: mixer("Capture toggle"),
    XK_XF86MonBrightnessUp: UserWM.inc_backlight,
    XK_XF86MonBrightnessDown: UserWM.dec_backlight,
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
    ("super", three_finger_swipe_right): UserWM.start_focus_cycle_next,
    ("super", three_finger_swipe_left): UserWM.start_focus_cycle_prev,
    three_finger_swipe_up: RaiseLower.raise_window,
    three_finger_swipe_down: RaiseLower.lower_window,
    four_finger_swipe_up: UserWM.tmax,
    four_finger_swipe_down: UserWM.vmax,
    four_finger_swipe_left: UserWM.tmax,
    four_finger_swipe_right: UserWM.hmax
}

focus_cycle_button_bindings.update({
    three_finger_swipe_up: CycleFocus.raise_target_window,
    three_finger_swipe_down: CycleFocus.lower_target_window,
    three_finger_swipe_left: CycleFocus.cycle_focus_prev,
    three_finger_swipe_right: CycleFocus.cycle_focus_next
})
