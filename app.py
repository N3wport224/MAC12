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

from imessage_to_word import chatdb, phones, preflight
from imessage_to_word.export import (
    ExportError,
    ExportOptions,
    NoMessagesFound,
    default_output_path,
    export_loaded,
    export_to_word,
    format_time,
    gap_note,
    large_document_note,
    load_conversation,
    parse_date_input,
    preview_selection,
)
from imessage_to_word.export import ME_COLOR, MUTED, THEM_COLOR, format_day

# How many messages the preview window shows before it starts skipping the
# middle. The export is never limited.
PREVIEW_MESSAGES = 600

# The document's colours, in the form Tk wants them.
MUTED_UI = "#" + MUTED
THEM_UI = "#" + THEM_COLOR
ME_UI = "#" + ME_COLOR

PRIVACY_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"
)


class PreviewWindow:
    """A read-only look at the conversation, before anything is written."""

    def __init__(self, parent, loaded, on_export):
        self.loaded = loaded
        self.on_export = on_export

        self.top = tk.Toplevel(parent)
        self.top.title("Preview - {} and {}".format(loaded.my_name, loaded.their_name))
        self.top.geometry("760x640")
        self.top.transient(parent)
        self.top.columnconfigure(0, weight=1)
        self.top.rowconfigure(1, weight=1)

        heading = ttk.Frame(self.top, padding=(16, 14, 16, 8))
        heading.grid(row=0, column=0, sticky="ew")
        ttk.Label(heading, text="{} and {}".format(loaded.my_name, loaded.their_name),
                  font=("Helvetica", 14, "bold")).pack(anchor="w")
        subtitle = loaded.headline()
        if loaded.date_span():
            subtitle += "\n" + loaded.date_span()
        completeness = loaded.conversation.stats
        if completeness and completeness.rows_seen:
            subtitle += "\n" + completeness.summary()
        ttk.Label(heading, text=subtitle, foreground=MUTED_UI, justify="left",
                  wraplength=700).pack(anchor="w")

        body = ttk.Frame(self.top, padding=(16, 0, 16, 0))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.text = tk.Text(body, wrap="word", borderwidth=1, relief="solid",
                            padx=12, pady=10, font=("Helvetica", 12),
                            highlightthickness=0)
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scrollbar.set)
        self._configure_tags()
        self._fill()

        buttons = ttk.Frame(self.top, padding=16)
        buttons.grid(row=2, column=0, sticky="ew")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        ttk.Button(buttons, text="Export this to Word",
                   command=self.export).pack(side="right", padx=(0, 10))
        ttk.Label(buttons, text="Scroll to check it is the right conversation.",
                  foreground=MUTED_UI).pack(side="left")

        self.top.bind("<Escape>", lambda _event: self.close())

    def _configure_tags(self) -> None:
        self.text.tag_configure("day", justify="center", foreground=MUTED_UI,
                                font=("Helvetica", 10, "bold"),
                                spacing1=16, spacing3=6)
        self.text.tag_configure("gap", justify="center", foreground=MUTED_UI,
                                font=("Helvetica", 10, "italic"),
                                spacing1=14, spacing3=14)
        for side, colour, indent in (("them", THEM_UI, 0), ("me", ME_UI, 90)):
            self.text.tag_configure(
                "name_" + side, foreground=colour,
                font=("Helvetica", 10, "bold"),
                lmargin1=indent, lmargin2=indent, spacing1=10)
            self.text.tag_configure(
                "body_" + side, lmargin1=indent, lmargin2=indent,
                rmargin=0 if side == "me" else 90, spacing3=2)
            self.text.tag_configure(
                "note_" + side, foreground=MUTED_UI, font=("Helvetica", 11, "italic"),
                lmargin1=indent, lmargin2=indent, spacing3=2)

    def _add_message(self, message, day_state) -> None:
        day = message.date.date() if message.date else None
        if day != day_state.get("day"):
            day_state["day"] = day
            heading = format_day(message.date) if message.date else "Undated messages"
            self.text.insert("end", heading + "\n", ("day",))

        side = "me" if message.is_from_me else "them"
        speaker = (self.loaded.my_name if message.is_from_me
                   else (message.sender_handle_name or self.loaded.their_name))
        stamp = format_time(message.date) if message.date else ""
        self.text.insert("end", "{}   {}\n".format(speaker, stamp), ("name_" + side,))

        tag = ("note_" if message.is_placeholder else "body_") + side
        if message.text:
            self.text.insert("end", message.text + "\n", (tag,))
        for attachment in message.attachments:
            self.text.insert("end", attachment.describe() + "\n", ("note_" + side,))

    def _fill(self) -> None:
        head, tail, omitted = preview_selection(self.loaded.messages, PREVIEW_MESSAGES)
        day_state = {}
        for message in head:
            self._add_message(message, day_state)
        if omitted:
            self.text.insert("end", gap_note(omitted) + "\n", ("gap",))
            day_state["day"] = None
            for message in tail:
                self._add_message(message, day_state)
        self.text.configure(state="disabled")

    def export(self) -> None:
        self.close()
        self.on_export(self.loaded)

    def close(self) -> None:
        self.top.destroy()


class ExporterApp:
    def __init__(self, root: "tk.Tk"):
        self.root = root
        self.events: "queue.Queue" = queue.Queue()
        self.worker = None
        self.chosen_path = None
        self.preview = None

        root.title("iMessage to Word")
        root.minsize(560, 470)
        root.columnconfigure(0, weight=1)

        self._build_ui()
        self.root.after(100, self._drain_events)

    # -- interface ---------------------------------------------------------
    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=18)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, minsize=110, pad=12)
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
        self.text_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Also save a plain text (.txt) copy",
                        variable=self.text_var).pack(anchor="w")

        row += 1
        ttk.Label(frame, text="Save to").grid(row=row, column=0, sticky="w", pady=(12, 4))
        self.path_var = tk.StringVar(value="Documents / iMessage Exports (chosen for you)")
        ttk.Entry(frame, textvariable=self.path_var, state="readonly").grid(
            row=row, column=1, sticky="ew", pady=(12, 4))
        ttk.Button(frame, text="Choose...", command=self._choose_path).grid(
            row=row, column=2, sticky="e", padx=(8, 0), pady=(12, 4))

        row += 1
        buttons = ttk.Frame(frame)
        buttons.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(18, 6))
        self.preview_button = ttk.Button(buttons, text="Preview",
                                         command=self.start_preview)
        self.preview_button.pack(side="left", padx=(0, 10))
        self.export_button = ttk.Button(buttons, text="Export to Word",
                                        command=self.start_export)
        self.export_button.pack(side="left", expand=True, fill="x")
        self.check_button = ttk.Button(buttons, text="Check setup",
                                       command=self.start_check)
        self.check_button.pack(side="left", padx=(10, 0))
        self.root.bind("<Return>", lambda _event: self.start_export())

        row += 1
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew")
        self.progress.grid_remove()

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

    def _collect_options(self):
        """Validate what is on screen and turn it into ExportOptions, or None."""
        number = self.number_var.get().strip()
        problem = phones.looks_like_handle(number)
        if problem:
            messagebox.showwarning("Check the number", problem, parent=self.root)
            return None
        try:
            start = parse_date_input(self.start_var.get())
            end = parse_date_input(self.end_var.get(), end_of_day=True)
        except ExportError as error:
            messagebox.showwarning("Check the dates", str(error), parent=self.root)
            return None

        return ExportOptions(
            number=number,
            their_name=self.their_name_var.get().strip() or None,
            my_name=self.my_name_var.get().strip() or "Me",
            include_groups=self.groups_var.get(),
            include_reactions=self.reactions_var.get(),
            also_text=self.text_var.get(),
            start=start,
            end=end,
        )

    def start_export(self, loaded=None) -> None:
        if self.worker and self.worker.is_alive():
            return
        options = self._collect_options()
        if options is None:
            return

        self._busy("Working...")
        self.worker = threading.Thread(
            target=self._run_export, args=(options, self.chosen_path, loaded),
            daemon=True,
        )
        self.worker.start()

    def start_preview(self) -> None:
        """Read the conversation and show it, without writing anything."""
        if self.worker and self.worker.is_alive():
            return
        options = self._collect_options()
        if options is None:
            return

        self._busy("Reading the conversation...")
        self.worker = threading.Thread(
            target=self._run_preview, args=(options,), daemon=True
        )
        self.worker.start()

    def _busy(self, status: str) -> None:
        for button in (self.export_button, self.preview_button, self.check_button):
            button.state(["disabled"])
        self._show_progress(True)
        self.status_var.set(status)

    def _run_preview(self, options: ExportOptions) -> None:
        try:
            loaded = load_conversation(
                options, progress=lambda message: self.events.put(("status", message))
            )
            self.events.put(("preview", loaded))
        except Exception as error:  # surfaced to the user in the main thread
            self.events.put(("error", error))

    def start_check(self) -> None:
        """Confirm this Mac is set up (Full Disk Access, history, save folder)."""
        if self.worker and self.worker.is_alive():
            return
        self._busy("Checking your setup...")
        self.worker = threading.Thread(target=self._run_checks, daemon=True)
        self.worker.start()

    def _run_checks(self) -> None:
        try:
            self.events.put(("checks", preflight.report(preflight.run_checks())))
        except Exception as error:  # pragma: no cover - defensive
            self.events.put(("error", error))

    def _run_export(self, options: ExportOptions, output_path, loaded=None) -> None:
        try:
            report = lambda message: self.events.put(("status", message))  # noqa: E731
            if loaded is None:
                result = export_to_word(options, output_path=output_path, progress=report)
            else:
                # Came from the preview: write exactly what was on screen.
                result = export_loaded(loaded, options, output_path=output_path,
                                       progress=report)
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
                elif kind == "preview":
                    self._finish_preview(payload)
                elif kind == "checks":
                    self._finish_checks(payload)
                elif kind == "error":
                    self._finish_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _show_progress(self, running: bool) -> None:
        if running:
            self.progress.grid()
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.grid_remove()

    def _reset(self) -> None:
        self._show_progress(False)
        for button in (self.export_button, self.preview_button, self.check_button):
            button.state(["!disabled"])

    def _finish_preview(self, loaded) -> None:
        self._reset()
        self.status_var.set(
            "Previewing {}. Nothing has been written yet.".format(loaded.headline()))
        self.preview = PreviewWindow(self.root, loaded, on_export=self.start_export)

    def _finish_checks(self, text: str) -> None:
        self._reset()
        ready = "Not ready yet" not in text
        self.status_var.set("Setup looks good." if ready else "Setup needs attention.")
        show = messagebox.showinfo if ready else messagebox.showwarning
        show("Setup check", text, parent=self.root)

    def _finish_success(self, result) -> None:
        self._reset()
        summary = "Saved {} messages ({} from {}, {} from {}) to:\n{}".format(
            result.message_count, result.from_them, result.their_name,
            result.from_me, result.my_name, result.path,
        )
        if result.text_path:
            summary += "\n{}".format(result.text_path)
        if result.completeness():
            summary += "\n\n{}".format(result.completeness())
        for warning in result.warnings:
            summary += "\n\nWarning: {}".format(warning)
        note = large_document_note(result.message_count)
        if note:
            summary += "\n\n{}".format(note)
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
