# -*- mode: Python; coding: utf-8 -*-

from array import array
from struct import pack, unpack
import unittest

import xcb
from xcb.xproto import *

from properties import *

class TestProp(PropertyValue):
    __propformat__ = 32
    __slots__ = ("a", "b", "c")

class TestPropertyValue(unittest.TestCase):
    def test_unpack(self):
        prop = TestProp.unpack(pack("III", 1, 2, 3))
        self.assertEqual(prop.a, 1)
        self.assertEqual(prop.b, 2)
        self.assertEqual(prop.c, 3)

    def test_pack(self):
        self.assertEqual(TestProp(1), pack("III", 1, 0, 0))
        self.assertEqual(TestProp(1, c=3), pack("III", 1, 0, 3))
        self.assertEqual(TestProp(1, 2, 3), pack("III", 1, 2, 3))

    def test_args(self):
        prop = TestProp(1, c=3)
        self.assertEqual(prop.a, 1)
        self.assertRaises(AttributeError, lambda: prop.b)
        self.assertEqual(prop.c, 3)

    def test_prop_set(self):
        prop = TestProp()
        self.assertRaises(AttributeError, lambda: prop.a)
        prop.a = 1
        self.assertEqual(prop.a, 1)

    def test_equality(self):
        self.assertEqual(TestProp(a=1, b=2, c=3), TestProp(a=1, b=2, c=3))
        self.assertNotEqual(TestProp(a=1), TestProp(a=1, b=2, c=3))
        self.assertEqual(TestProp(a=1), pack("III", 1, 0, 0))

    def test_pack_unpack(self):
        prop = TestProp(a=1, b=2, c=3)
        self.assertEqual(prop, prop.unpack(prop.pack()))

class TestPropertyVaueList(unittest.TestCase):
    def test_pack_unpack(self):
        l = [0x1234, 0x5678, 0x90ab]
        packed = array("I", l).tostring()
        p = PropertyValueList.unpack(packed)
        self.assertEqual(p, l)
        self.assertEqual(p.pack(), packed)

    def test_list(self):
        l = [0x1234, 0x5678, 0x90ab]
        p = PropertyValueList(l)
        self.assertEqual(len(p), len(l))
        self.assertEqual(list(p), l)
        self.assertEqual(p, l)
        for i in range(len(l)):
            self.assertEqual(p[i], l[i])
        p[0] = 0x4321
        self.assertEqual(p[0], 0x4321)

    def test_string(self):
        s = u"foö"
        p = StringValue(s)
        self.assertEqual(p, StringValue.unpack(s.encode("Latin-1")))
        self.assertEqual(p.pack(), s.encode("Latin-1"))
        self.assertEqual(unicode(p), s)

    def test_utf8_string(self):
        s = u"foö"
        p = UTF8String(s)
        self.assertEqual(p, StringValue.unpack(s.encode("UTF-8")))
        self.assertEqual(p.pack(), s.encode("UTF-8"))
        self.assertEqual(unicode(p), s)

class TestWMClass(unittest.TestCase):
    def test_wm_class(self):
        s = "xterm\x00XTerm\x00"
        p = WMClass.unpack(s)
        self.assertEqual(p.pack(), s)
        self.assertEqual(p.instance_and_class(), ("xterm", "XTerm"))

class TestWMSizeHints(unittest.TestCase):
    base_size = (4, 4)
    min_size = (10, 17)
    resize_inc = (6, 13)
    aspect = (16, 9)
    gravity = Gravity.NorthEast

    def test_default_size_hints(self):
        hints = WMSizeHints()
        self.assertEqual(hints.flags, 0)
        self.assertEqual(hints.min_size, (1, 1))
        self.assertEqual(hints.max_size, (0x7fffffff, 0x7fffffff))
        self.assertEqual(hints.resize_inc, (1, 1))
        self.assertEqual(hints.min_aspect, (None, None))
        self.assertEqual(hints.max_aspect, (None, None))
        self.assertEqual(hints.base_size, (1, 1))
        self.assertEqual(hints.win_gravity, Gravity.NorthWest)

    def test_base_size(self):
        hints = WMSizeHints(base_size=self.base_size)
        self.assertEqual(hints.flags, WMSizeHints.PBaseSize)
        self.assertEqual(hints.base_size, self.base_size)
        self.assertEqual(hints.min_size, self.base_size)

    def test_min_size(self):
        hints = WMSizeHints(min_size=self.min_size)
        self.assertEqual(hints.flags, WMSizeHints.PMinSize)
        self.assertEqual(hints.min_size, self.min_size)
        self.assertEqual(hints.base_size, self.min_size)

    def test_base_and_min_size(self):
        # Start with just a base size; min size will default to that.
        hints = WMSizeHints(base_size=self.base_size)
        self.assertEqual(hints.flags, WMSizeHints.PBaseSize)
        self.assertEqual(hints.base_size, self.base_size)
        self.assertEqual(hints.min_size, self.base_size)

        # Decouple them by adding a min size.
        hints.min_size = self.min_size
        self.assertEqual(hints.flags,
                         WMSizeHints.PMinSize | WMSizeHints.PBaseSize)
        self.assertEqual(hints.base_size, self.base_size)
        self.assertEqual(hints.min_size, self.min_size)

        # Deleting the base size should now cause it to default to min size.
        del hints.base_size
        self.assertEqual(hints.flags, WMSizeHints.PMinSize)
        self.assertEqual(hints.base_size, self.min_size)
        self.assertEqual(hints.min_size, self.min_size)

    def test_resize_inc(self):
        hints = WMSizeHints(resize_inc=self.resize_inc)
        self.assertEqual(WMSizeHints.PResizeInc, hints.flags)
        self.assertEqual(hints.resize_inc, self.resize_inc)

    def test_aspect(self):
        hints = WMSizeHints(min_aspect=self.aspect, max_aspect=self.aspect)
        self.assertEqual(hints.flags, WMSizeHints.PAspect)
        self.assertEqual(hints.min_aspect, self.aspect)
        self.assertEqual(hints.max_aspect, self.aspect)

    def test_win_gravity(self):
        hints = WMSizeHints(win_gravity=self.gravity)
        self.assertEqual(hints.flags, WMSizeHints.PWinGravity)
        self.assertEqual(hints.win_gravity, self.gravity)

    def test_delete_field(self):
        hints = WMSizeHints(min_size=self.min_size, resize_inc=self.resize_inc)
        self.assertEqual(hints.flags,
                         WMSizeHints.PMinSize | WMSizeHints.PResizeInc)
        del hints.min_size
        self.assertEqual(hints.flags, WMSizeHints.PResizeInc)
        self.assertEqual(hints.resize_inc, self.resize_inc)
        self.assertEqual(hints.min_size, (1, 1))

    def test_pack_unpack(self):
        hints = WMSizeHints(base_size=self.base_size,
                            min_size=self.min_size,
                            resize_inc=self.resize_inc,
                            min_aspect=self.aspect,
                            max_size=self.aspect,
                            win_gravity=self.gravity)
        self.assertEqual(hints, hints.unpack(hints.pack()))

class TestWMHints(unittest.TestCase):
    def test_default_wm_hints(self):
        hints = WMHints()
        self.assertEqual(hints.flags, 0)
        self.assertEqual(hints.input, False)
        self.assertEqual(hints.initial_state, 0)
        self.assertEqual(hints.icon_pixmap, 0)
        self.assertEqual(hints.icon_window, 0)
        self.assertEqual(hints.icon_position, (0, 0))
        self.assertEqual(hints.icon_mask, 0)
        self.assertEqual(hints.window_group, 0)

    def test_pack_unpack(self):
        hints = WMHints(input=True, icon_window=123456789, window_group=42)
        self.assertEqual(hints, hints.unpack(hints.pack()))

if __name__ == "__main__":
    unittest.main()
