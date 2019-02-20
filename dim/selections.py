# -*- mode: Python; coding: utf-8 -*-

"""ICCCM §2 ¶2:

Selections communicate between an owner and a requestor. The owner has the
data representing the value of its selection, and the requestor receives it.
A requestor wishing to obtain the value of a selection provides the following:

  * The name of the selection
  * The name of a property
  * A window
  * The atom representing the data type required
  * Optionally, some parameters for the request

If the selection is currently owned, the owner receives an event and is
expected to do the following:

  * Convert the contents of the selection to the requested data type
  * Place this data in the named property on the named window
  * Send the requestor an event to let it know the property is available

Clients are strongly encouraged to use this mechanism."""

from xcb.xproto import *

from atom import AtomCache
from event import EventHandler, handler
from properties import PropertyManager

__all__ = ["SelectionClient"]

class SelectionCallback(PropertyManager):
    def __init__(self, function=None, **kwargs):
        self.function = function
        super(SelectionCallback, self).__init__(**kwargs)

    def __call__(self, event):
        utf8_types = (self.atoms["UTF8_STRING"], self.atoms["TEXT"])
        if event.property:
            property = self.get_property(event.property, event.target)
            encoding = ("Latin-1" if event.target == Atom.STRING
                        else "UTF-8" if event.target in utf8_types
                        else "ASCII")
            self.delete_property(event.property)
            return self.function(str(property).decode(encoding))
        else:
            return self.function(""
                                 if event.target in (Atom.STRING,) + utf8_types
                                 else None)

class SelectionClient(EventHandler):
    def __init__(self, *args, **kwargs):
        self.selections = {}
        super(SelectionClient, self).__init__(*args, **kwargs)

    def call_with_selection(self, function, # of one argument (the selection)
                            requestor=Window._None,
                            selection=Atom._None,
                            target=Atom.STRING,
                            property=Atom._None,
                            time=Time.CurrentTime):
        self.selections[requestor] = SelectionCallback(function=function,
                                                       conn=self.conn,
                                                       atoms=self.atoms,
                                                       window=requestor)
        self.conn.core.ConvertSelection(requestor,
                                        self.atoms[selection],
                                        self.atoms[target],
                                        self.atoms[property],
                                        time)

    def call_with_primary_selection(self, function,
                                    selection=Atom.PRIMARY,
                                    target="UTF8_STRING",
                                    property=Atom.PRIMARY,
                                    **kwargs):
        self.call_with_selection(function,
                                 selection=selection,
                                 target=target,
                                 property=property,
                                 **kwargs)

    @handler(SelectionNotifyEvent)
    def handle_selection_notify(self, event):
        try:
            requestor = self.selections.pop(event.requestor)
        except IndexError:
            return
        requestor(event)
