"""Setup checks: everything that has to be true before an export can work.

Run with ``python3 -m imessage_to_word --check``.  The point is to find the
problems (Full Disk Access, most often) before you actually need the export.
"""
from __future__ import annotations

import importlib
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import chatdb, contacts
from .docx_writer import Document, Run
from .export import default_output_path

OK = "ok"
WARN = "warn"
FAIL = "fail"

MARKS = {OK: "[ ok ]", WARN: "[note]", FAIL: "[FAIL]"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""

    def line(self) -> str:
        text = "{} {}".format(MARKS.get(self.status, "[ ?? ]"), self.name)
        return "{}\n       {}".format(text, self.detail) if self.detail else text


def _check_python() -> Check:
    version = "{}.{}.{}".format(*sys.version_info[:3])
    if sys.version_info < (3, 6):
        return Check("Python version", FAIL,
                     "Found {} at {}; this app needs Python 3.6 or newer.".format(
                         version, sys.executable))
    return Check("Python version", OK, "{} at {}".format(version, sys.executable))


def _check_tkinter() -> Check:
    try:
        importlib.import_module("tkinter")
    except ImportError:
        return Check(
            "Window support (Tkinter)", WARN,
            "Not available in this Python, so `python3 app.py` will not open a "
            "window.\n       The command line works either way: "
            'python3 -m imessage_to_word "+15551234567"\n'
            "       To get the window, install Python from python.org and run "
            "app.py with it.",
        )
    return Check("Window support (Tkinter)", OK, "app.py can open its window")


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return "{:.0f} {}".format(value, unit) if unit in ("bytes", "KB") \
                else "{:.1f} {}".format(value, unit)
        value /= 1024
    return str(size)


def _check_database(db_path: Optional[Path]) -> List[Check]:
    path = Path(db_path) if db_path else chatdb.DEFAULT_DB_PATH
    try:
        chatdb.check_access(path)
    except chatdb.ChatDBNotFound:
        return [Check("Messages database", FAIL,
                      "Nothing at {}. Is Messages signed in on this Mac?".format(path))]
    except chatdb.ChatDBPermissionError:
        return [Check(
            "Full Disk Access", FAIL,
            "macOS is blocking {}.\n"
            "       Open System Settings > Privacy & Security > Full Disk Access,\n"
            "       switch on the app you are running this from (Terminal), then\n"
            "       QUIT AND REOPEN it -- the permission only applies after a restart."
            .format(path))]
    except chatdb.ChatDBError as error:
        return [Check("Messages database", FAIL, str(error))]

    checks = [Check("Full Disk Access", OK, "{} is readable ({})".format(
        path, _format_bytes(path.stat().st_size)))]

    free = shutil.disk_usage(tempfile.gettempdir()).free
    needed = path.stat().st_size
    if free < needed * 1.2:
        checks.append(Check(
            "Free disk space", WARN,
            "The database is copied before reading; {} free may be tight for a "
            "{} database.\n       Use --no-copy to read it in place instead.".format(
                _format_bytes(free), _format_bytes(needed))))
    else:
        checks.append(Check("Free disk space", OK,
                            "{} free for the temporary copy".format(_format_bytes(free))))

    try:
        with chatdb.open_chat_db(path) as conn:
            messages = conn.execute("SELECT COUNT(*) FROM message").fetchone()[0]
            handles = conn.execute("SELECT COUNT(*) FROM handle").fetchone()[0]
            chats = conn.execute("SELECT COUNT(*) FROM chat").fetchone()[0]
            recent = chatdb.list_conversations(conn, limit=1)
    except (chatdb.ChatDBError, sqlite3.Error) as error:
        checks.append(Check("Reading the database", FAIL, str(error)))
        return checks

    if not messages:
        checks.append(Check(
            "Message history", FAIL,
            "The database opened but holds no messages. If Messages in iCloud is "
            "on,\n       wait for it to finish downloading to this Mac."))
        return checks

    detail = "{:,} messages, {:,} handles, {:,} conversations".format(
        messages, handles, chats)
    if recent and recent[0]["last_date"]:
        detail += "\n       most recent activity: {}".format(
            recent[0]["last_date"].strftime("%B %d, %Y at %I:%M %p").replace(" 0", " "))
    checks.append(Check("Message history", OK, detail))
    return checks


def _check_contacts() -> Check:
    databases = contacts.candidate_databases()
    if not databases:
        return Check("Contacts lookup", WARN,
                     "No Contacts database found; names come from what you type "
                     "(everything else still works).")
    return Check("Contacts lookup", OK,
                 "{} contact database(s) available for names and linked numbers".format(
                     len(databases)))


def _check_output_folder() -> Check:
    folder = default_output_path("check").parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as error:
        return Check("Save folder", FAIL, "Cannot write to {}: {}".format(folder, error))
    return Check("Save folder", OK, str(folder))


def _check_word_writer() -> Check:
    temp_dir = Path(tempfile.mkdtemp(prefix="imessage-selftest-"))
    try:
        document = Document(title="Self test")
        document.add_paragraph([Run("Self test", bold=True)])
        path = document.save(temp_dir / "selftest.docx")
        import zipfile
        with zipfile.ZipFile(path) as archive:
            broken = archive.testzip()
        if broken:
            return Check("Word document writer", FAIL, "Bad entry: {}".format(broken))
        return Check("Word document writer", OK,
                     "wrote and verified a test .docx ({} bytes)".format(
                         path.stat().st_size))
    except Exception as error:  # pragma: no cover - defensive
        return Check("Word document writer", FAIL, "{}: {}".format(
            type(error).__name__, error))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_checks(db_path: Optional[Path] = None) -> List[Check]:
    checks = [_check_python(), _check_tkinter()]
    checks.extend(_check_database(db_path))
    checks.append(_check_contacts())
    checks.append(_check_output_folder())
    checks.append(_check_word_writer())
    return checks


def report(checks: List[Check]) -> str:
    lines = [check.line() for check in checks]
    failures = [check for check in checks if check.status == FAIL]
    lines.append("")
    if failures:
        lines.append("Not ready yet: {}".format(
            "; ".join(check.name for check in failures)))
        lines.append("Fix the [FAIL] items above, then run this check again.")
    else:
        lines.append("Ready. Try an export:")
        lines.append('  python3 -m imessage_to_word --list')
        lines.append('  python3 -m imessage_to_word "+15551234567" --open')
    return "\n".join(lines)


def main(db_path: Optional[Path] = None) -> int:
    checks = run_checks(db_path)
    print(report(checks))
    return 1 if any(check.status == FAIL for check in checks) else 0
