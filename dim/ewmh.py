# -*- mode: Python; coding: utf-8 -*-

"""Support for the Extended Window Manager Hints (EWMH) specification."""

import logging

import xcb
from xcb.xproto import *

from event import EventHandlerClass
from focus import FocusPolicy
from manager import WindowManager
from properties import *
from xutil import *

log = logging.getLogger("net")

class EWMHCapability(WindowManager):
    net_supported = PropertyDescriptor("_NET_SUPPORTED", AtomList, [])

    def start(self):
        properties = (set(self.properties) |
                      set(self.default_client_class.properties))
        self.net_supported = AtomList([AtomProperty(self.atoms[name])
                                       for name in sorted(properties)
                                       if name.startswith("_NET")])
        super(EWMHCapability, self).start()

class CheckWindowProperties(PropertyManager):
    net_wm_name = PropertyDescriptor("_NET_WM_NAME", UTF8StringProperty, "")
    net_supporting_wm_check = PropertyDescriptor("_NET_SUPPORTING_WM_CHECK",
                                                 WindowProperty)

class NetSupportingWMCheck(EWMHCapability, FocusPolicy):
    net_supporting_wm_check = PropertyDescriptor("_NET_SUPPORTING_WM_CHECK",
                                                 WindowProperty)

    def start(self):
        # We'll use the default focus window as the supporting WM check
        # window. This is the only reason we inherit from FocusPolicy.
        window = self.default_focus_window
        self.net_supporting_wm_check = WindowProperty(window)
        window_properties = CheckWindowProperties(self.conn, window, self.atoms)
        window_properties.net_wm_name = "Dim"
        window_properties.net_supporting_wm_check = WindowProperty(window)

        super(NetSupportingWMCheck, self).start()

class NetClientList(EWMHCapability):
    net_client_list = PropertyDescriptor("_NET_CLIENT_LIST", WindowList, [])

    def start(self):
        self.net_client_list = WindowList([])
        super(NetClientList, self).start()

    def manage(self, window, adopted=False):
        client = super(NetClientList, self).manage(window, adopted)
        if client:
            self.net_client_list += [WindowProperty(client.window)]
        return client

    def unmanage(self, client, **kwargs):
        self.net_client_list = WindowList([window
                                           for window in self.net_client_list
                                           if window != client.window])
        super(NetClientList, self).unmanage(client, **kwargs)


class EWMHManager(NetSupportingWMCheck, NetClientList):
    pass
