# -*- mode: Python; coding: utf-8 -*-

import unittest

from stringbuffer import StringBuffer

class TestStringBuffer(unittest.TestCase):
    def assertBuffer(self, buf, string, cursor):
        self.assertEqual(str(buf), string)
        self.assertEqual(buf.cursor, cursor)

    def test_init(self):
        self.assertBuffer(StringBuffer("foo"), "foo", 3)

    def test_sequence_methods(self):
        s = "foo"
        buf = StringBuffer("foo")
        self.assertEqual(len(buf), len(s))
        self.assertEqual(list(iter(buf)), list(iter(s)))
        for i in range(len(buf)):
            self.assertEqual(buf[i], s[i])
        self.assertEqual(buf[1:-1], s[1:-1])

    def test_insert_char(self):
        buf = StringBuffer("abc")
        buf.insert_char("x")
        self.assertBuffer(buf, "abcx", 4)

        buf.cursor = 3
        buf.insert_char("d")
        self.assertBuffer(buf, "abcdx", 4)

        buf.cursor = 0
        buf.insert_char("0")
        self.assertBuffer(buf, "0abcdx", 1)

    def test_beginning_of_buffer(self):
        buf = StringBuffer("abc")
        buf.beginning_of_buffer()
        self.assertEqual(buf.cursor, 0)
        buf.beginning_of_buffer()
        self.assertEqual(buf.cursor, 0)

    def test_end_of_buffer(self):
        buf = StringBuffer("abc")
        buf.end_of_buffer()
        self.assertEqual(buf.cursor, 3)
        buf.end_of_buffer()
        self.assertEqual(buf.cursor, 3)

    def test_backward_char(self):
        buf = StringBuffer("abc")
        buf.backward_char()
        self.assertEqual(buf.cursor, 2)

        buf.backward_char(2)
        self.assertEqual(buf.cursor, 0)
        self.assertRaises(IndexError, lambda: buf.backward_char())

        buf.end_of_buffer()
        self.assertRaises(IndexError, lambda: buf.backward_char(4))
        self.assertEqual(buf.cursor, 0)

    def test_forward_char(self):
        buf = StringBuffer("abc")
        self.assertRaises(IndexError, lambda: buf.forward_char())

        buf.beginning_of_buffer()
        buf.forward_char()
        self.assertEqual(buf.cursor, 1)
        buf.forward_char(2)
        self.assertEqual(buf.cursor, 3)

        buf.beginning_of_buffer()
        self.assertRaises(IndexError, lambda: buf.forward_char(4))
        self.assertEqual(buf.cursor, 3)

    def test_backward_word(self):
        buf = StringBuffer("abc xyz-123")
        buf.backward_word()
        self.assertEqual(buf.cursor, 8)

        buf.backward_word(2)
        self.assertEqual(buf.cursor, 0)
        buf.backward_word()
        self.assertEqual(buf.cursor, 0)

        buf.end_of_buffer()
        buf.backward_word(word_chars=r"[\w-]")
        self.assertEqual(buf.cursor, 4)

    def test_forward_word(self):
        buf = StringBuffer("abc xyz-123")
        buf.beginning_of_buffer()
        buf.forward_word()
        self.assertEqual(buf.cursor, 3)

        buf.forward_word(2)
        self.assertEqual(buf.cursor, len(buf))
        buf.forward_word()
        self.assertEqual(buf.cursor, len(buf))

        buf.cursor = 3
        buf.forward_word(word_chars=r"[\w-]")
        self.assertEqual(buf.cursor, len(buf))

    def test_delete_backward_char(self):
        buf = StringBuffer("abc")
        buf.delete_backward_char()
        self.assertBuffer(buf, "ab", 2)

        buf.delete_backward_char(2)
        self.assertBuffer(buf, "", 0)

    def test_delete_backward_char_too_many(self):
        buf = StringBuffer("abc")
        buf.end_of_buffer()
        self.assertRaises(IndexError, lambda: buf.delete_backward_char(4))
        self.assertBuffer(buf, "abc", 3)

    def test_delete_forward_char(self):
        buf = StringBuffer("abc")
        buf.beginning_of_buffer()
        buf.delete_forward_char()
        self.assertBuffer(buf, "bc", 0)
        buf.delete_forward_char(2)
        self.assertBuffer(buf, "", 0)

    def test_delete_forward_char_too_many(self):
        buf = StringBuffer("abc")
        buf.beginning_of_buffer()
        self.assertRaises(IndexError, lambda: buf.delete_forward_char(4))
        self.assertBuffer(buf, "abc", 0)

    def test_delete_backward_word(self):
        buf = StringBuffer("abc xyz-123")
        buf.delete_backward_word()
        self.assertBuffer(buf, "abc xyz-", 8)
        buf.delete_backward_word(2)
        self.assertBuffer(buf, "", 0)

    def test_delete_forward_word(self):
        buf = StringBuffer("abc xyz-123")
        buf.beginning_of_buffer()
        buf.delete_forward_word()
        self.assertBuffer(buf, " xyz-123", 0)
        buf.delete_forward_word(2)
        self.assertBuffer(buf, "", 0)

    def test_kill_line(self):
        buf = StringBuffer("foo bar")
        buf.cursor = 3
        buf.kill_line()
        self.assertBuffer(buf, "foo", 3)

    def test_kill_whole_line(self):
        buf = StringBuffer("foo bar")
        buf.cursor = 3
        buf.kill_whole_line()
        self.assertBuffer(buf, "", 0)

if __name__ == "__main__":
    unittest.main()
