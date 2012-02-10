# -*- mode: Python; coding: utf-8 -*-

import unittest

from dim.stringbuffer import *

class TestStringBuffer(unittest.TestCase):
    def assertBuffer(self, buf, contents, point=None):
        """Assert that the given buffer contains the correct text content
        and point position. Rather than specifying the point as an integer,
        it may be encoded as a caret (^) in the contents string."""
        if point is None:
            before, caret, after = contents.partition("^")
            assert caret is not None, "missing point specifier"
            assert "^" not in after, "too many carets"
            point = len(before)
            string = before + after
        else:
            assert 0 <= point <= len(contents), "invalid point specifier"
            string = contents
        self.assertEqual(str(buf), string)
        self.assertEqual(buf.point, point)

    def test_init(self):
        """initialize string buffer"""
        self.assertBuffer(StringBuffer("foo"), "foo^")

    def test_sequence_methods(self):
        """sequence methods"""
        s = "foo"
        buf = StringBuffer("foo")
        self.assertEqual(len(buf), len(s))
        self.assertEqual(list(iter(buf)), list(iter(s)))
        for i in range(len(buf)):
            self.assertEqual(buf[i], s[i])
        self.assertEqual(buf[1:-1], s[1:-1])

    def test_setitem(self):
        """__setitem__"""
        buf = StringBuffer("bar")
        buf[-1] = "z"
        self.assertBuffer(buf, "baz^")

        buf[:] = "quux"
        self.assertBuffer(buf, "quux^")

        buf.point = 1
        buf[1:1] = "u"
        self.assertBuffer(buf, "q^uuux")

        buf.end_of_buffer()
        buf[:] = "foo"
        self.assertBuffer(buf, "foo^")

    def test_insert_char(self):
        """insert-char"""
        buf = StringBuffer("abc")
        buf.insert_char("x")
        self.assertBuffer(buf, "abcx^")

        buf.point = 3
        buf.insert_char("d")
        self.assertBuffer(buf, "abcd^x")

        buf.point = 0
        buf.insert_char("0")
        self.assertBuffer(buf, "0^abcdx")

    def test_beginning_of_buffer(self):
        """beginning-of-buffer"""
        buf = StringBuffer("abc")
        buf.beginning_of_buffer()
        self.assertEqual(buf.point, 0)
        buf.beginning_of_buffer()
        self.assertEqual(buf.point, 0)

    def test_end_of_buffer(self):
        """end-of-buffer"""
        buf = StringBuffer("abc")
        buf.end_of_buffer()
        self.assertEqual(buf.point, len(buf))
        buf.end_of_buffer()
        self.assertEqual(buf.point, len(buf))

    def test_backward_char(self):
        """backward-char"""
        buf = StringBuffer("abc")
        buf.backward_char()
        self.assertEqual(buf.point, len(buf) - 1)

        buf.backward_char(buf.point)
        self.assertEqual(buf.point, 0)
        self.assertRaises(IndexError, lambda: buf.backward_char())

        buf.end_of_buffer()
        self.assertRaises(IndexError, lambda: buf.backward_char(len(buf) + 1))
        self.assertEqual(buf.point, 0)

    def test_forward_char(self):
        """forward-char"""
        buf = StringBuffer("abc")
        self.assertRaises(IndexError, lambda: buf.forward_char())

        buf.beginning_of_buffer()
        buf.forward_char()
        self.assertEqual(buf.point, 1)
        buf.forward_char(len(buf) - 1)
        self.assertEqual(buf.point, len(buf))

        buf.beginning_of_buffer()
        self.assertRaises(IndexError, lambda: buf.forward_char(len(buf) + 1))
        self.assertEqual(buf.point, len(buf))

    def test_backward_word(self):
        """backward-word"""
        buf = StringBuffer("abc xyz-123")
        buf.backward_word()
        self.assertBuffer(buf, "abc xyz-^123")

        buf.backward_word(2)
        self.assertBuffer(buf, "^abc xyz-123")
        buf.backward_word()
        self.assertBuffer(buf, "^abc xyz-123")

        buf.end_of_buffer()
        buf.backward_word(word_chars=r"[\w-]")
        self.assertBuffer(buf, "abc ^xyz-123")

    def test_forward_word(self):
        """forward-word"""
        buf = StringBuffer("abc xyz-123")
        buf.beginning_of_buffer()
        buf.forward_word()
        self.assertBuffer(buf, "abc^ xyz-123")

        buf.forward_word(2)
        self.assertBuffer(buf, "abc xyz-123^")
        buf.forward_word()
        self.assertBuffer(buf, "abc xyz-123^")

        buf.beginning_of_buffer()
        buf.forward_word(2, word_chars=r"[\w-]")
        self.assertBuffer(buf, "abc xyz-123^")

    def test_delete_backward_char(self):
        """delete-backward-char"""
        buf = StringBuffer("abc")
        buf.delete_backward_char()
        self.assertBuffer(buf, "ab^")

        buf.delete_backward_char(2)
        self.assertBuffer(buf, "^")

        buf = StringBuffer("abc")
        buf.end_of_buffer()
        self.assertRaises(IndexError, lambda: buf.delete_backward_char(4))
        self.assertBuffer(buf, "abc^")

    def test_delete_forward_char(self):
        """delete-forward-char"""
        buf = StringBuffer("abc")
        buf.beginning_of_buffer()
        buf.delete_forward_char()
        self.assertBuffer(buf, "^bc")
        buf.delete_forward_char(2)
        self.assertBuffer(buf, "^")

        buf = StringBuffer("abc")
        buf.beginning_of_buffer()
        self.assertRaises(IndexError, lambda: buf.delete_forward_char(4))
        self.assertBuffer(buf, "^abc")

    def test_delete_backward_word(self):
        """delete-backward-word"""
        buf = StringBuffer("abc xyz-123")
        buf.delete_backward_word()
        self.assertBuffer(buf, "abc xyz-^")
        buf.delete_backward_word(2)
        self.assertBuffer(buf, "^")

    def test_delete_forward_word(self):
        """delete-forward-word"""
        buf = StringBuffer("abc xyz-123")
        buf.beginning_of_buffer()
        buf.delete_forward_word()
        self.assertBuffer(buf, "^ xyz-123")
        buf.delete_forward_word(2)
        self.assertBuffer(buf, "^")

    def test_kill(self):
        """kill"""
        buf = StringBuffer("xyzzy")
        buf.kill(1, len(buf) - 1)
        self.assertBuffer(buf, "x^y")

        buf.yank()
        self.assertBuffer(buf, "xyzz^y")
        buf.yank()
        self.assertBuffer(buf, "xyzzyzz^y")

    def test_append_kill(self):
        """append to last kill"""
        buf = StringBuffer("abc")
        buf.kill(0, 1)
        buf.kill(0, 1)
        self.assertBuffer(buf, "^c")

        buf.yank()
        self.assertBuffer(buf, "ab^c")

    def test_yank_pop(self):
        """yank-pop"""
        buf = StringBuffer("foobarbaz")
        buf.kill(0, 3); buf.beginning_of_buffer()
        buf.kill(0, 3); buf.beginning_of_buffer()
        buf.kill(0, 3)
        self.assertBuffer(buf, "^")

        self.assertRaises(CommandError, buf.yank_pop)

        buf.yank()
        self.assertBuffer(buf, "baz^")
        buf.yank_pop()
        self.assertBuffer(buf, "bar^")
        buf.yank_pop()
        self.assertBuffer(buf, "foo^")

    def test_kill_word(self):
        """kill-word"""
        buf = StringBuffer("foo bar baz")
        buf.point = 3
        buf.kill_word()
        self.assertBuffer(buf, "foo^ baz")

        buf.kill_word() # append to last kill
        self.assertBuffer(buf, "foo^")

        buf.yank()
        self.assertBuffer(buf, "foo bar baz^")

    def test_backward_kill_word(self):
        """backward-kill-word"""
        buf = StringBuffer("foo bar baz")
        buf.backward_kill_word()
        self.assertBuffer(buf, "foo bar ^")

        buf.backward_kill_word() # prepend to last kill
        self.assertBuffer(buf, "foo ^")

        buf.yank()
        self.assertBuffer(buf, "foo bar baz^")

    def test_kill_line(self):
        """kill-line"""
        buf = StringBuffer("foobar")
        buf.point = 3
        buf.kill_line()
        self.assertBuffer(buf, "foo^")

        buf.yank()
        self.assertBuffer(buf, "foobar^")

    def test_kill_whole_line(self):
        """kill-whole-line"""
        buf = StringBuffer("foobar")
        buf.point = 3
        buf.kill_whole_line()
        self.assertBuffer(buf, "^")

        buf.yank()
        self.assertBuffer(buf, "foobar^")

if __name__ == "__main__":
    unittest.main()
