"""Read-only access to the local iMessage database (~/Library/Messages/chat.db)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from . import phones
from .attributed_body import clean_text, decode_attributed_body
from .models import (
    Attachment,
    Conversation,
    FetchStats,
    Message,
    apple_time_to_datetime,
)

DEFAULT_DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

# chat.style: 45 is a one-to-one conversation, 43 is a group chat.
STYLE_DIRECT = 45

# Used only to keep sorting total when a row has no usable timestamp.
_FALLBACK_DATE = datetime.max.replace(tzinfo=timezone.utc)

FULL_DISK_ACCESS_HELP = (
    "macOS blocks access to your Messages database until the app running this "
    "script has Full Disk Access.\n\n"
    "Open System Settings > Privacy & Security > Full Disk Access, switch on "
    "the app you are running this from (Terminal, iTerm, or the app itself), "
    "then quit and reopen it and try again."
)


class ChatDBError(Exception):
    """Base class for problems reading chat.db."""


class ChatDBNotFound(ChatDBError):
    pass


class ChatDBPermissionError(ChatDBError):
    pass


def _chunks(values: Sequence, size: int = 800) -> Iterator[Sequence]:
    for start in range(0, len(values), size):
        yield values[start:start + size]


def check_access(path: Path) -> None:
    """Raise a helpful error if chat.db is missing or unreadable."""
    if not path.exists():
        raise ChatDBNotFound(
            "No Messages database found at {}.\n\n"
            "This app reads the iMessage history stored on this Mac, so it "
            "needs Messages to be signed in and synced here.".format(path)
        )
    try:
        with open(path, "rb") as handle:
            handle.read(16)
    except PermissionError:
        raise ChatDBPermissionError(FULL_DISK_ACCESS_HELP)
    except OSError as exc:
        raise ChatDBError("Could not read {}: {}".format(path, exc))


WAL_WARNING = (
    "Could not read the write-ahead log, so messages Messages has not yet "
    "written into chat.db may be missing from this export. Quit Messages and "
    "run it again, or drop --no-copy so the database is snapshotted instead."
)


def _uri(path: Path, query: str) -> str:
    """A SQLite file: URI that survives spaces and other characters in a path."""
    return "{}?{}".format(path.as_uri(), query)


class SnapshotStalled(Exception):
    """The backup made no progress for a while -- something else holds a lock."""


def _snapshot(path: Path, working: Path, stall_seconds: float = 10.0) -> None:
    """Copy the live database into ``working`` using SQLite's backup API.

    This takes a proper read lock, so the copy is consistent and -- unlike
    copying the file by hand -- it always includes whatever is still sitting in
    the write-ahead log, which is where the newest messages live while Messages
    is running.

    SQLite retries a locked source forever, so a watchdog gives up if the copy
    stops making progress; the caller then falls back to copying the file.
    """
    state = {"remaining": None, "changed": time.monotonic()}

    def watchdog(status, remaining, total):
        now = time.monotonic()
        if remaining != state["remaining"]:
            state["remaining"] = remaining
            state["changed"] = now
        elif now - state["changed"] > stall_seconds:
            raise SnapshotStalled(
                "the Messages database stayed locked for {:.0f} seconds".format(
                    stall_seconds))

    source = sqlite3.connect(_uri(path, "mode=ro"), uri=True)
    try:
        # Fail fast if something already holds the database, rather than
        # spending the whole watchdog budget discovering it.
        source.execute("PRAGMA busy_timeout = 2000")
        source.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        destination = sqlite3.connect(str(working))
        try:
            source.backup(destination, pages=2048, progress=watchdog, sleep=0.1)
        finally:
            destination.close()
    finally:
        source.close()


def _copy_files(path: Path, working: Path) -> None:
    """Fallback snapshot: copy chat.db and its -wal/-shm sidecars."""
    shutil.copyfile(path, working)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(path) + suffix)
        if sidecar.exists():
            try:
                shutil.copyfile(sidecar, Path(str(working) + suffix))
            except OSError:
                pass  # A missing sidecar just means slightly older data.


def _has_pending_wal(path: Path) -> bool:
    wal = Path(str(path) + "-wal")
    try:
        return wal.exists() and wal.stat().st_size > 0
    except OSError:
        return False


@contextmanager
def open_chat_db(
    path: Optional[Path] = None,
    copy: bool = True,
    on_warning: Optional[Callable[[str], None]] = None,
) -> Iterator[sqlite3.Connection]:
    """Open chat.db for reading, without disturbing Messages.

    By default the database is snapshotted into a temporary folder first, which
    keeps the live file untouched and captures the messages that are still in
    the write-ahead log.  ``copy=False`` reads it in place instead.
    """
    path = Path(path) if path else DEFAULT_DB_PATH
    check_access(path)

    def warn(message: str) -> None:
        if on_warning:
            on_warning(message)

    temp_dir = None
    connection = None
    try:
        if copy:
            temp_dir = tempfile.mkdtemp(prefix="imessage-export-")
            working = Path(temp_dir) / "chat.db"
            try:
                _snapshot(path, working)
            except (sqlite3.Error, OSError, AttributeError, SnapshotStalled):
                # Older Python, or a database SQLite will not open read-only:
                # fall back to copying the files themselves.
                for leftover in Path(temp_dir).glob("chat.db*"):
                    leftover.unlink()
                try:
                    _copy_files(path, working)
                except OSError:
                    # Usually not enough room; read it in place instead.
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    temp_dir = None
            if temp_dir:
                connection = sqlite3.connect(str(working))

        if connection is None:
            # Reading in place: mode=ro can still see the write-ahead log,
            # immutable cannot, so only fall back to it if we have to.
            try:
                connection = sqlite3.connect(_uri(path, "mode=ro"), uri=True)
                connection.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            except sqlite3.Error:
                if connection is not None:
                    connection.close()
                connection = sqlite3.connect(_uri(path, "mode=ro&immutable=1"), uri=True)
                if _has_pending_wal(path):
                    warn(WAL_WARNING)
        connection.row_factory = sqlite3.Row
        # One row of invalid UTF-8 would otherwise abort the whole export.
        connection.text_factory = lambda raw: raw.decode("utf-8", "replace")
    except sqlite3.OperationalError as exc:
        if "unable to open database" in str(exc).lower():
            raise ChatDBPermissionError(FULL_DISK_ACCESS_HELP)
        raise ChatDBError("Could not open the Messages database: {}".format(exc))
    except PermissionError:
        raise ChatDBPermissionError(FULL_DISK_ACCESS_HELP)
    except OSError as exc:
        raise ChatDBError("Could not open the Messages database: {}".format(exc))
    finally:
        # Only clean up here if opening failed; otherwise the copy is needed
        # for as long as the connection is.
        if temp_dir and connection is None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    try:
        yield connection
    except sqlite3.DatabaseError as exc:
        message = str(exc).lower()
        if "malformed" in message or "not a database" in message:
            raise ChatDBError(
                "The copy of the Messages database came out unreadable, which "
                "usually means Messages was writing to it at the time.\n\n"
                "Quit Messages and run this again."
            )
        raise ChatDBError("Error reading the Messages database: {}".format(exc))
    finally:
        connection.close()
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _columns(conn: sqlite3.Connection, table: str) -> Set[str]:
    try:
        return {row["name"] for row in conn.execute("PRAGMA table_info({})".format(table))}
    except sqlite3.Error:
        return set()


def find_handles(conn: sqlite3.Connection, targets) -> List[sqlite3.Row]:
    """All handle rows that refer to the person identified by ``targets``.

    ``targets`` may be a single number/email or several of them -- one person
    often texts from both a phone number and an Apple ID address.
    """
    if not any((target or "").strip() for target in
               ([targets] if isinstance(targets, str) else targets or [])):
        return []
    matches = []
    for row in conn.execute("SELECT ROWID, id, service FROM handle"):
        if phones.matches_any(row["id"], targets):
            matches.append(row)
    return matches


def _chat_participants(conn: sqlite3.Connection) -> Dict[int, Set[int]]:
    participants: Dict[int, Set[int]] = {}
    for row in conn.execute("SELECT chat_id, handle_id FROM chat_handle_join"):
        participants.setdefault(row["chat_id"], set()).add(row["handle_id"])
    return participants


def find_chats(
    conn: sqlite3.Connection,
    handle_ids: Set[int],
    targets,
    include_groups: bool = False,
) -> Tuple[List[int], Dict[int, sqlite3.Row]]:
    """Chats belonging to this person.

    A chat counts as one-to-one when every participant is one of this person's
    handles.  Group chats are only included when asked for.
    """
    participants = _chat_participants(conn)
    chats: Dict[int, sqlite3.Row] = {}
    selected: List[int] = []

    for row in conn.execute(
        "SELECT ROWID, chat_identifier, display_name, style, service_name FROM chat"
    ):
        chat_id = row["ROWID"]
        members = participants.get(chat_id, set())
        identifier = row["chat_identifier"] or ""
        identifier_matches = (
            not phones.is_group_identifier(identifier)
            and phones.matches_any(identifier, targets)
        )
        involves_person = bool(members & handle_ids) or identifier_matches
        # Messages marks one-to-one threads with style 45; trust that when it
        # is there, and fall back to "every participant is this person".
        is_direct = (
            (row["style"] == STYLE_DIRECT and involves_person)
            or (bool(members) and members <= handle_ids)
        )
        if is_direct or (include_groups and involves_person):
            selected.append(chat_id)
            chats[chat_id] = row
    return selected, chats


def _chat_label(row: Optional[sqlite3.Row], fallback: str) -> str:
    if row is None:
        return fallback
    name = (row["display_name"] or "").strip()
    if name:
        return name
    return row["chat_identifier"] or fallback


def _load_attachments(
    conn: sqlite3.Connection, message_ids: Sequence[int]
) -> Dict[int, List[Attachment]]:
    tables = _table_names(conn)
    if not message_ids or not {"attachment", "message_attachment_join"} <= tables:
        return {}
    columns = _columns(conn, "attachment")
    name_column = "transfer_name" if "transfer_name" in columns else "filename"
    size_column = "total_bytes" if "total_bytes" in columns else "0"
    result: Dict[int, List[Attachment]] = {}
    for chunk in _chunks(message_ids):
        placeholders = ",".join("?" * len(chunk))
        sql = (
            "SELECT j.message_id AS message_id, a.{name} AS name, "
            "a.mime_type AS mime_type, a.{size} AS total_bytes "
            "FROM message_attachment_join j "
            "JOIN attachment a ON a.ROWID = j.attachment_id "
            "WHERE j.message_id IN ({ph})".format(
                name=name_column, size=size_column, ph=placeholders
            )
        )
        for row in conn.execute(sql, tuple(chunk)):
            name = row["name"] or ""
            if name:
                name = os.path.basename(name)
            result.setdefault(row["message_id"], []).append(
                Attachment(
                    name=name,
                    mime_type=row["mime_type"],
                    total_bytes=row["total_bytes"] or 0,
                )
            )
    return result


def _table_names(conn: sqlite3.Connection) -> Set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _message_select(conn: sqlite3.Connection) -> str:
    """Build the SELECT list, tolerating schema differences between macOS versions."""
    columns = _columns(conn, "message")
    optional = {
        "attributedBody": "m.attributedBody",
        "associated_message_type": "m.associated_message_type",
        "date_edited": "m.date_edited",
        "service": "m.service",
        "item_type": "m.item_type",
        "balloon_bundle_id": "m.balloon_bundle_id",
        "group_action_type": "m.group_action_type",
        "group_title": "m.group_title",
        "is_audio_message": "m.is_audio_message",
    }
    fields = [
        "m.ROWID AS rowid",
        "m.text AS text",
        "m.is_from_me AS is_from_me",
        "m.date AS date",
        "m.handle_id AS handle_id",
    ]
    for name, expression in optional.items():
        fields.append(
            "{} AS {}".format(expression if name in columns else "NULL", name)
        )
    return ", ".join(fields)


BALLOON_LABELS = (
    ("URLBalloonProvider", "[Link]"),
    ("Handwriting", "[Handwritten message]"),
    ("DigitalTouch", "[Digital Touch]"),
    ("PassKit", "[Apple Cash]"),
    ("Payment", "[Apple Cash]"),
    ("com.apple.messages.MSMessageExtensionBalloonPlugin", "[App message]"),
)


def describe_untexted_message(row) -> str:
    """Explain a message row that carries no readable text.

    Stickers, link previews, Apple Cash, group events and the occasional body
    we cannot decode all land here.  They are kept in the transcript with a
    note rather than dropped, so the history stays complete.
    """
    item_type = row["item_type"] or 0
    if item_type:
        if item_type == 2 and row["group_title"]:
            return '[Named the conversation "{}"]'.format(row["group_title"])
        if item_type == 1:
            return "[Someone joined or left the conversation]"
        if item_type == 3:
            return "[Left the conversation]"
        return "[System message]"

    bundle = row["balloon_bundle_id"] or ""
    for needle, label in BALLOON_LABELS:
        if needle in bundle:
            return label
    if row["is_audio_message"]:
        return "[Audio message]"
    if row["attributedBody"]:
        return "[Message text could not be read]"
    return "[No text]"


def fetch_messages(
    conn: sqlite3.Connection,
    chat_ids: Sequence[int],
    chats: Dict[int, sqlite3.Row],
    handle_names: Dict[int, str],
    handle_ids: Optional[Set[int]] = None,
    include_reactions: bool = False,
    include_untexted: bool = True,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    stats: Optional[FetchStats] = None,
) -> List[Message]:
    stats = stats if stats is not None else FetchStats()
    # Message timestamps are local-time aware; make sure the bounds are too.
    start = start.astimezone() if start and start.tzinfo is None else start
    end = end.astimezone() if end and end.tzinfo is None else end
    select = _message_select(conn)
    rows: Dict[int, Tuple[sqlite3.Row, Optional[int]]] = {}

    for chunk in _chunks(list(chat_ids)):
        placeholders = ",".join("?" * len(chunk))
        sql = (
            "SELECT {select}, j.chat_id AS chat_id "
            "FROM message m "
            "JOIN chat_message_join j ON j.message_id = m.ROWID "
            "WHERE j.chat_id IN ({ph})".format(select=select, ph=placeholders)
        )
        for row in conn.execute(sql, tuple(chunk)):
            # The same message can be joined to more than one chat; keep one copy.
            rows.setdefault(row["rowid"], (row, row["chat_id"]))

    # Messages that were never joined to a chat still belong in the history.
    # Ask for their ids first and diff in Python: a NOT EXISTS subquery against
    # chat_message_join costs minutes on a large history.
    candidates = []
    for chunk in _chunks(sorted(handle_ids or ())):
        placeholders = ",".join("?" * len(chunk))
        sql = "SELECT ROWID FROM message WHERE handle_id IN ({})".format(placeholders)
        candidates.extend(
            row[0] for row in conn.execute(sql, tuple(chunk)) if row[0] not in rows
        )

    # Of those, keep only the ones that belong to no chat at all -- a message in
    # a chat we deliberately left out (a group chat, say) is not an orphan.
    orphans = []
    for chunk in _chunks(candidates):
        placeholders = ",".join("?" * len(chunk))
        sql = "SELECT message_id FROM chat_message_join WHERE message_id IN ({})".format(
            placeholders
        )
        joined = {row[0] for row in conn.execute(sql, tuple(chunk))}
        orphans.extend(rowid for rowid in chunk if rowid not in joined)

    for chunk in _chunks(orphans):
        placeholders = ",".join("?" * len(chunk))
        sql = "SELECT {select}, NULL AS chat_id FROM message m WHERE m.ROWID IN ({ph})".format(
            select=select, ph=placeholders
        )
        for row in conn.execute(sql, tuple(chunk)):
            rows.setdefault(row["rowid"], (row, None))

    stats.rows_seen = len(rows)
    attachments = _load_attachments(conn, list(rows))
    messages: List[Message] = []

    for rowid, (row, chat_id) in rows.items():
        associated = row["associated_message_type"] or 0
        if associated:
            stats.reactions_skipped += 1
            if not include_reactions:
                continue

        when = apple_time_to_datetime(row["date"])
        if when and ((start and when < start) or (end and when > end)):
            stats.outside_date_range += 1
            continue

        text = clean_text(row["text"] or decode_attributed_body(row["attributedBody"]))
        message_attachments = attachments.get(rowid, [])
        is_placeholder = False
        if not text and not message_attachments:
            if not include_untexted:
                continue
            text = describe_untexted_message(row)
            is_placeholder = True
            stats.placeholders += 1
            if row["attributedBody"] and not (row["item_type"] or 0):
                stats.unreadable_bodies += 1

        chat_row = chats.get(chat_id) if chat_id is not None else None
        messages.append(
            Message(
                rowid=rowid,
                date=when,
                is_from_me=bool(row["is_from_me"]),
                sender_handle=handle_names.get(row["handle_id"]),
                text=text,
                service=row["service"],
                chat_id=chat_id,
                chat_name=_chat_label(chat_row, ""),
                is_group=bool(chat_row is not None and chat_row["style"] != STYLE_DIRECT),
                is_reaction=bool(associated),
                is_edited=bool(row["date_edited"]),
                is_placeholder=is_placeholder,
                attachments=message_attachments,
            )
        )

    if include_reactions:
        stats.reactions_skipped = 0
    stats.exported = len(messages)
    # Messages with an unreadable timestamp sort to the end, in insertion order.
    messages.sort(key=lambda m: (m.date is None, m.date or _FALLBACK_DATE, m.rowid))
    return messages


def fetch_conversation(
    conn: sqlite3.Connection,
    target: str,
    extra_handles: Optional[Sequence[str]] = None,
    display_name: Optional[str] = None,
    include_groups: bool = False,
    include_reactions: bool = False,
    include_untexted: bool = True,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> Conversation:
    """Collect every message exchanged with ``target``.

    ``extra_handles`` are additional identifiers known to belong to the same
    person (typically pulled from Contacts).
    """
    targets = [target] + list(extra_handles or [])
    handles = find_handles(conn, targets)
    handle_ids = {row["ROWID"] for row in handles}
    # Every handle in the database, so senders in a group chat who are not the
    # person being exported are still named correctly.
    handle_names = {
        row["ROWID"]: row["id"]
        for row in conn.execute("SELECT ROWID, id FROM handle")
    }

    chat_ids, chats = find_chats(conn, handle_ids, targets, include_groups=include_groups)
    stats = FetchStats()
    messages = fetch_messages(
        conn,
        chat_ids,
        chats,
        handle_names,
        handle_ids=handle_ids,
        include_reactions=include_reactions,
        include_untexted=include_untexted,
        start=start,
        end=end,
        stats=stats,
    )

    chat_names = []
    for chat_id in chat_ids:
        label = _chat_label(chats.get(chat_id), "")
        if label and label not in chat_names:
            chat_names.append(label)

    return Conversation(
        query=target,
        display_name=display_name or phones.format_pretty(target),
        handles=sorted({row["id"] for row in handles}),
        messages=messages,
        chat_names=chat_names,
        included_group_chats=include_groups,
        stats=stats,
    )


def list_conversations(conn: sqlite3.Connection, limit: int = 40) -> List[dict]:
    """Handles you have exchanged the most messages with, newest activity first.

    Used by ``--list`` so you can find the exact number Messages has on file.
    """
    sql = (
        "SELECT h.id AS handle, COUNT(*) AS message_count, MAX(m.date) AS last_date "
        "FROM message m JOIN handle h ON h.ROWID = m.handle_id "
        "GROUP BY h.id ORDER BY last_date DESC LIMIT ?"
    )
    results = []
    for row in conn.execute(sql, (int(limit),)):
        results.append({
            "handle": row["handle"],
            "message_count": row["message_count"],
            "last_date": apple_time_to_datetime(row["last_date"]),
        })
    return results
