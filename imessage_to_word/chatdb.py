"""Read-only access to the local iMessage database (~/Library/Messages/chat.db)."""
from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

from . import phones
from .attributed_body import clean_text, decode_attributed_body
from .models import Attachment, Conversation, Message, apple_time_to_datetime

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


@contextmanager
def open_chat_db(path: Optional[Path] = None, copy: bool = True) -> Iterator[sqlite3.Connection]:
    """Open chat.db for reading.

    By default the database is copied to a temporary directory first: Messages
    keeps a write-ahead log open, and copying (with its -wal/-shm sidecars)
    gives a consistent snapshot that includes the newest messages without
    touching the live file.
    """
    path = Path(path) if path else DEFAULT_DB_PATH
    check_access(path)

    temp_dir = None
    connection = None
    try:
        if copy:
            temp_dir = tempfile.mkdtemp(prefix="imessage-export-")
            working = Path(temp_dir) / "chat.db"
            shutil.copyfile(path, working)
            for suffix in ("-wal", "-shm"):
                sidecar = Path(str(path) + suffix)
                if sidecar.exists():
                    try:
                        shutil.copyfile(sidecar, Path(str(working) + suffix))
                    except OSError:
                        pass  # A missing sidecar just means slightly older data.
            connection = sqlite3.connect(str(working))
        else:
            uri = "file:{}?mode=ro&immutable=1".format(path)
            connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
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
    keys = phones.match_keys(targets)
    if not keys:
        return []
    matches = []
    for row in conn.execute("SELECT ROWID, id, service FROM handle"):
        if phones.match_key(row["id"]) in keys:
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
    keys = phones.match_keys(targets)
    chats: Dict[int, sqlite3.Row] = {}
    selected: List[int] = []

    for row in conn.execute(
        "SELECT ROWID, chat_identifier, display_name, style, service_name FROM chat"
    ):
        chat_id = row["ROWID"]
        members = participants.get(chat_id, set())
        identifier_matches = phones.match_key(row["chat_identifier"] or "") in keys
        is_direct = (
            (members and members <= handle_ids)
            or (not members and identifier_matches and row["style"] == STYLE_DIRECT)
        )
        involves_person = bool(members & handle_ids) or identifier_matches
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
    if not message_ids or "attachment" not in _table_names(conn):
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


def fetch_messages(
    conn: sqlite3.Connection,
    chat_ids: Sequence[int],
    chats: Dict[int, sqlite3.Row],
    handle_names: Dict[int, str],
    include_reactions: bool = False,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> List[Message]:
    if not chat_ids:
        return []

    select = _message_select(conn)
    rows: Dict[int, Tuple[sqlite3.Row, int]] = {}
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

    attachments = _load_attachments(conn, list(rows))
    messages: List[Message] = []
    for rowid, (row, chat_id) in rows.items():
        associated = row["associated_message_type"] or 0
        is_reaction = associated != 0
        if is_reaction and not include_reactions:
            continue

        text = clean_text(row["text"] or decode_attributed_body(row["attributedBody"]))
        message_attachments = attachments.get(rowid, [])
        if not text and not message_attachments:
            continue

        when = apple_time_to_datetime(row["date"])
        if when and start and when < start:
            continue
        if when and end and when > end:
            continue

        chat_row = chats.get(chat_id)
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
                is_reaction=is_reaction,
                is_edited=bool(row["date_edited"]),
                attachments=message_attachments,
            )
        )

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
    messages = fetch_messages(
        conn,
        chat_ids,
        chats,
        handle_names,
        include_reactions=include_reactions,
        start=start,
        end=end,
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
