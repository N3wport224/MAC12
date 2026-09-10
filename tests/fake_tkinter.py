"""Stand-in Tkinter modules so the app's window logic can be tested headlessly.

The build machine (and any Linux box) has no Tk, but the interesting parts of
app.py -- validation, threading, status updates, error routing -- are worth
testing anyway.  These stubs record calls instead of drawing anything.
"""
from __future__ import annotations

import sys
import types


class TclError(Exception):
    """Stands in for tkinter.TclError."""


class Variable:
    def __init__(self, master=None, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class IntVar(Variable):
    def __init__(self, master=None, value=0):
        super().__init__(master, value)


class StringVar(Variable):
    def __init__(self, master=None, value=""):
        super().__init__(master, value)


class BooleanVar(Variable):
    def __init__(self, master=None, value=False):
        super().__init__(master, value)


class Widget:
    def __init__(self, master=None, **options):
        self.master = master
        self.options = dict(options)
        self.states = []
        self.tags = {}
        self.inserted = []
        self.destroyed = False

    def grid(self, **kwargs):
        self.states.append("gridded")

    def grid_remove(self):
        self.states.append("hidden")

    def pack(self, **kwargs):
        pass

    def bind(self, *args, **kwargs):
        pass

    def focus_set(self):
        pass

    def columnconfigure(self, *args, **kwargs):
        pass

    def rowconfigure(self, *args, **kwargs):
        pass

    def configure(self, **kwargs):
        self.options.update(kwargs)

    config = configure

    def state(self, spec=None):
        if spec is not None:
            self.states.append(spec)
        return []

    def destroy(self):
        self.destroyed = True

    def title(self, value=None):
        self.options["title"] = value

    def geometry(self, value=None):
        self.options["geometry"] = value

    def transient(self, other=None):
        pass

    def start(self, interval=None):
        self.states.append("started")

    def stop(self):
        self.states.append("stopped")

    # Text-widget surface, enough for the preview window.
    def tag_configure(self, name, **kwargs):
        self.tags[name] = kwargs

    def insert(self, index, text, tags=()):
        self.inserted.append((text, tuple(tags)))

    def see(self, index):
        self.states.append(("see", index))

    def set(self, *args):
        pass

    def index(self, spec):
        return "1.0"

    def cget(self, option):
        return self.options.get(option, "")

    def get(self, start=None, end=None):
        return self.content()

    def search(self, pattern, start, stopindex=None, nocase=False, count=None):
        return ""            # highlighting itself is checked against real Tk

    def tag_add(self, tag, start, end=None):
        self.states.append(("tag_add", tag))

    def tag_remove(self, tag, start, end=None):
        pass

    def tag_raise(self, tag, above=None):
        pass

    def delete(self, start, end=None):
        self.inserted = []

    def select_range(self, start, end):
        self.states.append("selected")

    def yview(self, *args):
        pass

    def content(self):
        """Everything inserted, as one string."""
        return "".join(text for text, _ in self.inserted)

    def tags_used(self):
        return {tag for _, tags in self.inserted for tag in tags}


class Toplevel(Widget):
    """A second window; the preview lives in one of these."""

    instances = []

    def __init__(self, master=None, **options):
        super().__init__(master, **options)
        Toplevel.instances.append(self)


class Tk(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scheduled = []

    def minsize(self, *args):
        pass

    def after(self, delay, callback=None, *args):
        # Record instead of running, so tests drive the pump themselves.
        self.scheduled.append((delay, callback))
        return "timer"

    def mainloop(self):
        pass


class Recorder:
    """Collects the dialogs the app tried to show."""

    def __init__(self):
        self.calls = []
        self.answers = {}

    def _record(self, name, default=None):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.answers.get(name, default)
        return call

    def last(self, name=None):
        for entry in reversed(self.calls):
            if name is None or entry[0] == name:
                return entry
        return None

    def names(self):
        return [entry[0] for entry in self.calls]


def install():
    """Register the stub modules and return the dialog recorder."""
    recorder = Recorder()

    tkinter = types.ModuleType("tkinter")
    Toplevel.instances = []
    for name, value in [("Tk", Tk), ("Toplevel", Toplevel), ("Text", Widget),
                        ("StringVar", StringVar), ("BooleanVar", BooleanVar),
                        ("IntVar", IntVar), ("TclError", TclError),
                        ("Variable", Variable), ("Frame", Widget), ("Label", Widget),
                        ("Entry", Widget), ("Button", Widget)]:
        setattr(tkinter, name, value)

    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Entry", "Button", "Checkbutton", "Progressbar",
                 "Scrollbar", "Separator", "Style"):
        setattr(ttk, name, Widget)

    messagebox = types.ModuleType("tkinter.messagebox")
    for name, default in [("showinfo", None), ("showwarning", None),
                          ("showerror", None), ("askyesno", False)]:
        setattr(messagebox, name, recorder._record(name, default))

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.asksaveasfilename = recorder._record("asksaveasfilename", "")

    tkinter.ttk = ttk
    tkinter.messagebox = messagebox
    tkinter.filedialog = filedialog
    sys.modules.update({
        "tkinter": tkinter,
        "tkinter.ttk": ttk,
        "tkinter.messagebox": messagebox,
        "tkinter.filedialog": filedialog,
    })
    return recorder


def uninstall():
    for name in ("tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog", "tkinter"):
        sys.modules.pop(name, None)
