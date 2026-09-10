"""Stand-in Tkinter modules so the app's window logic can be tested headlessly.

The build machine (and any Linux box) has no Tk, but the interesting parts of
app.py -- validation, threading, status updates, error routing -- are worth
testing anyway.  These stubs record calls instead of drawing anything.
"""
from __future__ import annotations

import sys
import types


class Variable:
    def __init__(self, master=None, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


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

    def start(self, interval=None):
        self.states.append("started")

    def stop(self):
        self.states.append("stopped")


class Tk(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scheduled = []

    def title(self, value=None):
        self.options["title"] = value

    def minsize(self, *args):
        pass

    def after(self, delay, callback=None, *args):
        # Record instead of running, so tests drive the pump themselves.
        self.scheduled.append((delay, callback))
        return "timer"

    def mainloop(self):
        pass

    def destroy(self):
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
    for name, value in [("Tk", Tk), ("StringVar", StringVar), ("BooleanVar", BooleanVar),
                        ("Variable", Variable), ("Frame", Widget), ("Label", Widget),
                        ("Entry", Widget), ("Button", Widget)]:
        setattr(tkinter, name, value)

    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Entry", "Button", "Checkbutton", "Progressbar",
                 "Separator", "Style"):
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
