"""Client windows may be decorated with a frame, border, title bar, &c."""

class Decorator(object):
    def decorate(self, client):
        pass

    def undecorate(self, client):
        pass
