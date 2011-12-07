# -*- mode: Python; coding: utf-8 -*-

from collections import MutableSequence

__all__ = ["StringBuffer"]

class StringBuffer(MutableSequence):
    """A mutable string buffer class."""

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
        if isinstance(index, slice):
            return u"".join(self.buffer[index])
        else:
            return self.buffer[index]

    def __setitem__(self, index, value):
        self.buffer[index] = value

    def __delitem__(self, index):
        del self.buffer[index]

    def insert(self, index, value):
        self.buffer.insert(index, value)

    def insert_char(self, char):
        self.insert(self.cursor, char)
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

    def delete_forward_char(self, n=1):
        if self.cursor <= len(self.buffer) - n:
            del self.buffer[self.cursor:self.cursor + n]
        else:
            raise IndexError("end of buffer")

    def delete_backward_char(self, n=1):
        if self.cursor >= n:
            del self.buffer[self.cursor - n:self.cursor]
            self.cursor -= n
        else:
            raise IndexError("beginning of buffer")
