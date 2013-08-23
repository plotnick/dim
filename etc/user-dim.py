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
def ignore_bindings(client, class_names=["Xephyr"]):
    if client.wm_class.class_name in class_names:
        return IgnoreBindingsClient

@decorator_selector
def trivial_decoration(client, class_names=["XClock", "XEyes"]):
    if client.wm_class.class_name in class_names:
        return Decorator

class UserManager(BaseWM):
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

global_key_bindings.update({
    ("control", "meta", XK_m): UserManager.show_mail,
    ("control", "shift", XK_M): UserManager.no_mail
})

default_options.update({
    "title_font": "6x13U",
    "minibuffer_font": "10x20U"
})
