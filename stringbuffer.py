# -*- mode: Python; coding: utf-8 -*-

from collections import Sequence
import re

__all__ = ["StringBuffer"]

word_chars = re.compile(r"\w", re.UNICODE)

class StringBuffer(Sequence):
    """A string buffer supporting cursor-relative modifications."""

    def __init__(self, initial_value):
        self.buffer = list(unicode(initial_value))
        self.cursor = len(self.buffer)

    def __str__(self):
        return "".join(self.buffer)

    def __unicode__(self):
        return u"".join(self.buffer)

    def __len__(self):
        return len(self.buffer)

    def __iter__(self):
        return iter(self.buffer)

    def __getitem__(self, index):
        return unicode(self)[index]

    def insert_char(self, char):
        self.buffer.insert(self.cursor, char)
        self.cursor += 1

    def beginning_of_buffer(self):
        self.cursor = 0

    def end_of_buffer(self):
        self.cursor = len(self.buffer)

    def forward_char(self, n=1):
        if self.cursor <= len(self.buffer) - n:
            self.cursor += n
        else:
            self.end_of_buffer()
            raise IndexError("end of buffer")

    def backward_char(self, n=1):
        if self.cursor >= n:
            self.cursor -= n
        else:
            self.beginning_of_buffer()
            raise IndexError("beginning of buffer")

    def forward_word(self, n=1, word_chars=word_chars):
        for i in range(n):
            while (self.cursor < len(self.buffer) and
                   not re.match(word_chars, self.buffer[self.cursor])):
                self.cursor += 1
            while (self.cursor < len(self.buffer) and
                   re.match(word_chars, self.buffer[self.cursor])):
                self.cursor += 1

    def backward_word(self, n=1, word_chars=word_chars):
        for i in range(n):
            self.cursor -= 1
            while (self.cursor >= 0 and
                   not re.match(word_chars, self.buffer[self.cursor])):
                self.cursor -= 1
            while (self.cursor >= 0 and
                   re.match(word_chars, self.buffer[self.cursor])):
                self.cursor -= 1
            self.cursor += 1

    def delete_forward_char(self, n=1):
        if self.cursor > len(self.buffer) - n:
            raise IndexError("end of buffer")
        del self.buffer[self.cursor:self.cursor + n]

    def delete_backward_char(self, n=1):
        if self.cursor < n:
            raise IndexError("beginning of buffer")
        del self.buffer[self.cursor - n:self.cursor]
        self.cursor -= n

    def delete_forward_word(self, n=1, word_chars=word_chars):
        mark = self.cursor
        try:
            self.forward_word(n, word_chars)
            del self.buffer[mark:self.cursor]
        except IndexError:
            raise
        finally:
            self.cursor = mark

    def delete_backward_word(self, n=1, word_chars=word_chars):
        mark = self.cursor
        try:
            self.backward_word(n, word_chars)
            del self.buffer[self.cursor:mark]
        except IndexError:
            self.cursor = mark
            raise

    def kill_line(self):
        del self.buffer[self.cursor:]

    def kill_whole_line(self):
        del self.buffer[:]
        self.cursor = 0
