# -*- mode: Python; coding: utf-8 -*-

import unittest

import xcb
from xcb.xproto import *

from dim.ewmh import *
from dim.geometry import *
from dim.properties import *

from test_manager import TestClient, WMTestCase

class EWMHTestCase(WMTestCase):
    wm_class = EWMHManager

    def assertSupported(self, atom):
        if isinstance(atom, basestring):
            atom = self.atoms[atom]
        self.assertTrue(atom in self.get_root_property("_NET_SUPPORTED",
                                                       AtomList))

    def test_net_supporting_wm_check(self):
        """_NET_SUPPORTING_WM_CHECK"""
        self.assertSupported("_NET_SUPPORTING_WM_CHECK")

        w = self.get_root_property("_NET_SUPPORTING_WM_CHECK", WindowProperty)
        self.loop(lambda: (self.getprop(w, "_NET_WM_NAME",
                                        UTF8StringProperty) == "Dim" and
                           self.getprop(w, "_NET_SUPPORTING_WM_CHECK",
                                        WindowProperty) == w))

    def test_net_client_list(self):
        """_NET_CLIENT_LIST"""
        self.assertSupported("_NET_CLIENT_LIST")

        def get_client_list():
            return self.get_root_property("_NET_CLIENT_LIST", WindowList)
        def make_client_list_test(clients):
            return lambda: get_client_list() == [client.window
                                                 for client in clients]

        # This test assumes that no other clients are being managed.
        self.loop(make_client_list_test([]))
        c1 = self.add_client(TestClient(Geometry(0, 0, 100, 100, 1)))
        c2 = self.add_client(TestClient(Geometry(10, 10, 10, 10, 1)))
        c3 = self.add_client(TestClient(Geometry(100, 100, 1, 1, 1)))
        c1.map(); c2.map(); c3.map()
        self.loop(make_client_list_test([c1, c2, c3]))
        c2.unmap()
        self.loop(make_client_list_test([c1, c3]))
        c2.map()
        self.loop(make_client_list_test([c1, c3, c2]))
        c1.unmap()
        self.loop(make_client_list_test([c3, c2]))
        c2.unmap()
        self.loop(make_client_list_test([c3]))
        c3.unmap()
        self.loop(make_client_list_test([]))
        c1.map()
        self.loop(make_client_list_test([c1]))

if __name__ == "__main__":
    unittest.main()
