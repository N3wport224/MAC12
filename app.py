#!/usr/bin/env python3
"""iMessage to Word -- a small desktop app for one person: you.

Type a phone number, press Export, and the whole conversation with that person
is written to a Word document with each side clearly labelled.

Run it with:  python3 app.py
"""
from __future__ import annotations

import queue
import subprocess
import sys
import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - depends on the Python install
    sys.stderr.write(
        "This app needs Tkinter, which the Mac's built-in python3 includes.\n"
        "If you are using a Python without it, run the command-line version:\n"
        '  python3 -m imessage_to_word "+15551234567"\n'
    )
    raise SystemExit(1)

from imessage_to_word import chatdb, phones
from imessage_to_word.export import (
    ExportError,
    ExportOptions,
    NoMessagesFound,
    default_output_path,
    export_to_word,
    parse_date_input,
)

PRIVACY_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
)


class ExporterApp:
    def __init__(self, root: "tk.Tk"):
        self.root = root
        self.events: "queue.Queue" = queue.Queue()
        self.worker = None
        self.chosen_path = None

        root.title("iMessage to Word")
        root.minsize(560, 470)
        root.columnconfigure(0, weight=1)

        self._build_ui()
        self.root.after(100, self._drain_events)

    # -- interface ---------------------------------------------------------
    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        row = 0
        ttk.Label(frame, text="Save an iMessage conversation as a Word document",
                  font=("Helvetica", 15, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Label(frame, foreground="#6E6E73", wraplength=520,
                  text="Everything happens on this Mac: the app reads your local "
                       "Messages database and writes a .docx file.").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(4, 16))

        row += 1
        ttk.Label(frame, text="Phone number").grid(row=row, column=0, sticky="w", pady=4)
        self.number_var = tk.StringVar()
        number_entry = ttk.Entry(frame, textvariable=self.number_var, font=("Helvetica", 14))
        number_entry.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)
        number_entry.focus_set()

        row += 1
        ttk.Label(frame, foreground="#8A8A8E", font=("Helvetica", 11),
                  text="Any format works: 5551234567, (555) 123-4567, +1 555 123 4567, "
                       "or an Apple ID email.").grid(
            row=row, column=1, columnspan=2, sticky="w", pady=(0, 10))

        row += 1
        ttk.Label(frame, text="Their name").grid(row=row, column=0, sticky="w", pady=4)
        self.their_name_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.their_name_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=4)

        row += 1
        ttk.Label(frame, foreground="#8A8A8E", font=("Helvetica", 11),
                  text="Optional -- left blank, your Contacts are checked.").grid(
            row=row, column=1, columnspan=2, sticky="w", pady=(0, 10))

        row += 1
        ttk.Label(frame, text="Your name").grid(row=row, column=0, sticky="w", pady=4)
        self.my_name_var = tk.StringVar(value="Me")
        ttk.Entry(frame, textvariable=self.my_name_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=4)

        row += 1
        dates = ttk.Frame(frame)
        dates.grid(row=row, column=1, columnspan=2, sticky="ew", pady=(10, 4))
        ttk.Label(frame, text="Date range").grid(row=row, column=0, sticky="w", pady=(10, 4))
        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        ttk.Label(dates, text="from").pack(side="left")
        ttk.Entry(dates, textvariable=self.start_var, width=12).pack(side="left", padx=6)
        ttk.Label(dates, text="to").pack(side="left")
        ttk.Entry(dates, textvariable=self.end_var, width=12).pack(side="left", padx=6)
        ttk.Label(dates, text="YYYY-MM-DD, optional", foreground="#8A8A8E",
                  font=("Helvetica", 11)).pack(side="left")

        row += 1
        self.groups_var = tk.BooleanVar(value=False)
        self.reactions_var = tk.BooleanVar(value=False)
        options = ttk.Frame(frame)
        options.grid(row=row, column=1, columnspan=2, sticky="w", pady=(8, 4))
        ttk.Checkbutton(options, text="Include group chats they are in",
                        variable=self.groups_var).pack(anchor="w")
        ttk.Checkbutton(options, text="Include tapbacks (Loved, Liked, ...)",
                        variable=self.reactions_var).pack(anchor="w")

        row += 1
        ttk.Label(frame, text="Save to").grid(row=row, column=0, sticky="w", pady=(12, 4))
        self.path_var = tk.StringVar(value="Documents / iMessage Exports (chosen for you)")
        ttk.Entry(frame, textvariable=self.path_var, state="readonly").grid(
            row=row, column=1, sticky="ew", pady=(12, 4))
        ttk.Button(frame, text="Choose...", command=self._choose_path).grid(
            row=row, column=2, sticky="e", padx=(8, 0), pady=(12, 4))

        row += 1
        self.export_button = ttk.Button(frame, text="Export to Word", command=self.start_export)
        self.export_button.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(18, 6))
        self.root.bind("<Return>", lambda _event: self.start_export())

        row += 1
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew")

        row += 1
        self.status_var = tk.StringVar(value="Ready.")
        ttk.Label(frame, textvariable=self.status_var, foreground="#6E6E73",
                  wraplength=520, justify="left").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))

    # -- actions -----------------------------------------------------------
    def _choose_path(self) -> None:
        suggestion = default_output_path(
            self.their_name_var.get() or self.number_var.get() or "conversation"
        )
        try:
            suggestion.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save conversation as",
            defaultextension=".docx",
            initialdir=str(suggestion.parent),
            initialfile=suggestion.name,
            filetypes=[("Word document", "*.docx")],
        )
        if selected:
            self.chosen_path = Path(selected)
            self.path_var.set(selected)

    def start_export(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        number = self.number_var.get().strip()
        problem = phones.looks_like_handle(number)
        if problem:
            messagebox.showwarning("Check the number", problem, parent=self.root)
            return
        try:
            start = parse_date_input(self.start_var.get())
            end = parse_date_input(self.end_var.get(), end_of_day=True)
        except ExportError as error:
            messagebox.showwarning("Check the dates", str(error), parent=self.root)
            return

        options = ExportOptions(
            number=number,
            their_name=self.their_name_var.get().strip() or None,
            my_name=self.my_name_var.get().strip() or "Me",
            include_groups=self.groups_var.get(),
            include_reactions=self.reactions_var.get(),
            start=start,
            end=end,
        )

        self.export_button.state(["disabled"])
        self.progress.start(12)
        self.status_var.set("Working...")
        self.worker = threading.Thread(
            target=self._run_export, args=(options, self.chosen_path), daemon=True
        )
        self.worker.start()

    def _run_export(self, options: ExportOptions, output_path) -> None:
        try:
            result = export_to_word(
                options,
                output_path=output_path,
                progress=lambda message: self.events.put(("status", message)),
            )
            self.events.put(("done", result))
        except Exception as error:  # surfaced to the user in the main thread
            self.events.put(("error", error))

    # -- main-thread event pump -------------------------------------------
    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status_var.set(payload)
                elif kind == "done":
                    self._finish_success(payload)
                elif kind == "error":
                    self._finish_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _reset(self) -> None:
        self.progress.stop()
        self.export_button.state(["!disabled"])

    def _finish_success(self, result) -> None:
        self._reset()
        summary = "Saved {} messages ({} from {}, {} from {}) to:\n{}".format(
            result.message_count, result.from_them, result.their_name,
            result.from_me, result.my_name, result.path,
        )
        self.status_var.set(summary)
        if messagebox.askyesno("Export finished", summary + "\n\nOpen it now?",
                               parent=self.root):
            self._open(result.path)

    def _finish_error(self, error: Exception) -> None:
        self._reset()
        self.status_var.set("Ready.")
        if isinstance(error, chatdb.ChatDBPermissionError):
            if messagebox.askyesno(
                "Full Disk Access needed",
                "{}\n\nOpen Privacy & Security settings now?".format(error),
                parent=self.root,
            ):
                self._open(PRIVACY_SETTINGS_URL)
            return
        if isinstance(error, NoMessagesFound):
            messagebox.showinfo("Nothing found", str(error), parent=self.root)
            return
        if isinstance(error, (ExportError, chatdb.ChatDBError)):
            messagebox.showerror("Could not export", str(error), parent=self.root)
            return
        messagebox.showerror(
            "Something went wrong", "{}: {}".format(type(error).__name__, error),
            parent=self.root,
        )

    @staticmethod
    def _open(target) -> None:
        try:
            subprocess.run(["open", str(target)], check=False)
        except OSError:
            pass


def main() -> int:
    root = tk.Tk()
    ExporterApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
