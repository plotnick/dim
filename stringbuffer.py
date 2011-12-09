# -*- mode: Python; coding: utf-8 -*-

from collections import deque, Sequence
from functools import wraps
import re

__all__ = ["StringBuffer"]

def command(method):
    """A decorator for interactive commands."""
    @wraps(method)
    def wrapper(instance, *args, **kwargs):
        # We'll only record this method as the last command if it's not
        # being invoked from within another command.
        try:
            instance.command_level += 1
            return method(instance, *args, **kwargs)
        finally:
            instance.command_level -= 1
            if instance.command_level == 0:
                instance.last_command = method.__name__
    return wrapper

class StringBuffer(Sequence):
    """A string buffer supporting cursor-relative modifications."""

    word_chars = re.compile(r"\w", re.UNICODE)
    kill_command = re.compile(r"(^|_)kill(_|$)")

    def __init__(self, initial_value="", kill_ring_max=10):
        self.buffer = list(unicode(initial_value))
        self.cursor = len(self.buffer)
        self.kill_ring = deque([], kill_ring_max)
        self.last_command = ""
        self.command_level = 0

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

    @command
    def insert(self, chars):
        self.buffer[self.cursor:self.cursor] = list(chars)
        self.cursor += len(chars)

    @command
    def insert_char(self, char, n=1):
        self.insert(char * n)

    @command
    def yank(self):
        self.insert(self.kill_ring[-1])

    @command
    def yank_pop(self):
        if not self.last_command.startswith("yank"):
            raise IndexError("previous command was not a yank")
        mark = self.cursor
        self.cursor -= len(self.kill_ring[-1])
        assert self.cursor >= 0
        del self.buffer[self.cursor:mark]
        self.kill_ring.rotate(1)
        self.yank()

    @command
    def kill(self, start, end):
        forwards = start <= end
        if not forwards:
            start, end = end, start
        kill = self.buffer[start:end]
        if self.kill_command.search(self.last_command):
            # Append or prepend to the last kill.
            self.kill_ring[-1] = (self.kill_ring[-1] + kill
                                  if forwards
                                  else kill + self.kill_ring[-1])
        else:
            # Make a new entry in the kill ring.
            self.kill_ring.append(kill)
        del self.buffer[start:end]
        self.cursor = start

    @command
    def beginning_of_buffer(self):
        self.cursor = 0

    @command
    def end_of_buffer(self):
        self.cursor = len(self.buffer)

    @command
    def forward_char(self, n=1):
        if self.cursor <= len(self.buffer) - n:
            self.cursor += n
        else:
            self.end_of_buffer()
            raise IndexError("end of buffer")

    @command
    def backward_char(self, n=1):
        if self.cursor >= n:
            self.cursor -= n
        else:
            self.beginning_of_buffer()
            raise IndexError("beginning of buffer")

    @command
    def forward_word(self, n=1, word_chars=word_chars):
        for i in range(n):
            while (self.cursor < len(self.buffer) and
                   not re.match(word_chars, self.buffer[self.cursor])):
                self.cursor += 1
            while (self.cursor < len(self.buffer) and
                   re.match(word_chars, self.buffer[self.cursor])):
                self.cursor += 1

    @command
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

    @command
    def delete_forward_char(self, n=1):
        if self.cursor > len(self.buffer) - n:
            raise IndexError("end of buffer")
        del self.buffer[self.cursor:self.cursor + n]

    @command
    def delete_backward_char(self, n=1):
        if self.cursor < n:
            raise IndexError("beginning of buffer")
        del self.buffer[self.cursor - n:self.cursor]
        self.cursor -= n

    @command
    def delete_forward_word(self, n=1, word_chars=word_chars):
        mark = self.cursor
        try:
            self.forward_word(n, word_chars)
            del self.buffer[mark:self.cursor]
        except IndexError:
            raise
        finally:
            self.cursor = mark

    @command
    def delete_backward_word(self, n=1, word_chars=word_chars):
        mark = self.cursor
        try:
            self.backward_word(n, word_chars)
            del self.buffer[self.cursor:mark]
        except IndexError:
            self.cursor = mark
            raise

    @command
    def kill_word(self, n=1, word_chars=word_chars):
        mark = self.cursor
        self.forward_word(n, word_chars)
        self.kill(mark, self.cursor)

    @command
    def backward_kill_word(self, n=1, word_chars=word_chars):
        mark = self.cursor
        self.backward_word(n, word_chars)
        self.kill(mark, self.cursor)

    @command
    def kill_line(self):
        mark = self.cursor
        self.end_of_buffer()
        self.kill(mark, self.cursor)

    @command
    def kill_whole_line(self):
        self.end_of_buffer()
        self.kill(0, self.cursor)
