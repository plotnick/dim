# -*- mode: Python; coding: utf-8 -*-

from collections import deque, Sequence
from functools import wraps
import re

__all__ = ["CommandError", "StringBuffer"]

class CommandError(Exception):
    pass

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

    def __init__(self, initial_value="", kill_ring=None, kill_ring_max=10):
        self.buffer = list(unicode(initial_value))
        self.point = len(self.buffer)
        self.kill_ring = (kill_ring
                          if kill_ring is not None
                          else deque([], kill_ring_max))
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

    def __getitem__(self, key):
        return unicode(self)[key]

    def __setitem__(self, key, value):
        if isinstance(key, int):
            self.buffer[key] = value
        elif isinstance(key, slice):
            end = (self.point == len(self.buffer))
            self.buffer[key] = list(value)
            self.point = (len(self.buffer)
                          if end
                          else min(self.point, len(self.buffer)))
        else:
            raise TypeError("unsupported key type")

    @property
    def point(self):
        return self._point

    @point.setter
    def point(self, n):
        if n < 0:
            self._point = 0
            raise IndexError("beginning of buffer")
        elif n > len(self):
            self._point = len(self)
            raise IndexError("end of buffer")
        else:
            self._point = n

    @command
    def insert(self, chars):
        self.buffer[self.point:self.point] = list(chars)
        self.point += len(chars)

    @command
    def insert_char(self, char, n=1):
        self.insert(char * n)

    @command
    def yank(self):
        self.insert(self.kill_ring[-1])

    @command
    def yank_pop(self):
        if not self.last_command.startswith("yank"):
            raise CommandError("previous command was not a yank")
        mark = self.point
        self.point -= len(self.kill_ring[-1])
        del self.buffer[self.point:mark]
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
        self.point = start

    @command
    def beginning_of_buffer(self):
        self.point = 0

    @command
    def end_of_buffer(self):
        self.point = len(self.buffer)

    @command
    def forward_char(self, n=1):
        self.point += n

    @command
    def backward_char(self, n=1):
        self.point -= n

    @command
    def forward_word(self, n=1, word_chars=word_chars):
        try:
            for i in range(n):
                while not re.match(word_chars, self.buffer[self.point]):
                    self.point += 1
                while re.match(word_chars, self.buffer[self.point]):
                    self.point += 1
        except IndexError:
            return

    @command
    def backward_word(self, n=1, word_chars=word_chars):
        try:
            self.point -= 1
            for i in range(n):
                while not re.match(word_chars, self.buffer[self.point]):
                    self.point -= 1
                while re.match(word_chars, self.buffer[self.point]):
                    self.point -= 1
            self.point += 1
        except IndexError:
            return

    @command
    def delete_forward_char(self, n=1):
        if self.point > len(self.buffer) - n:
            raise IndexError("end of buffer")
        del self.buffer[self.point:self.point + n]

    @command
    def delete_backward_char(self, n=1):
        if self.point < n:
            raise IndexError("beginning of buffer")
        del self.buffer[self.point - n:self.point]
        self.point -= n

    @command
    def delete_forward_word(self, n=1, word_chars=word_chars):
        mark = self.point
        try:
            self.forward_word(n, word_chars)
            del self.buffer[mark:self.point]
        except IndexError:
            raise
        finally:
            self.point = mark

    @command
    def delete_backward_word(self, n=1, word_chars=word_chars):
        mark = self.point
        try:
            self.backward_word(n, word_chars)
            del self.buffer[self.point:mark]
        except IndexError:
            self.point = mark
            raise

    @command
    def kill_word(self, n=1, word_chars=word_chars):
        mark = self.point
        self.forward_word(n, word_chars)
        self.kill(mark, self.point)

    @command
    def backward_kill_word(self, n=1, word_chars=word_chars):
        mark = self.point
        self.backward_word(n, word_chars)
        self.kill(mark, self.point)

    @command
    def kill_line(self):
        mark = self.point
        self.end_of_buffer()
        self.kill(mark, self.point)

    @command
    def kill_whole_line(self):
        self.end_of_buffer()
        self.kill(0, self.point)
