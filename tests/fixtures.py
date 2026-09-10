"""Build a miniature chat.db that mirrors the real Messages schema."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)

SCHEMA = """
CREATE TABLE handle (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL,
    country TEXT,
    service TEXT NOT NULL,
    uncanonicalized_id TEXT
);
CREATE TABLE chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    style INTEGER,
    chat_identifier TEXT,
    service_name TEXT,
    display_name TEXT
);
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    text TEXT,
    handle_id INTEGER DEFAULT 0,
    service TEXT,
    date INTEGER,
    is_from_me INTEGER DEFAULT 0,
    associated_message_type INTEGER DEFAULT 0,
    attributedBody BLOB,
    date_edited INTEGER DEFAULT 0,
    item_type INTEGER DEFAULT 0,
    cache_has_attachments INTEGER DEFAULT 0,
    balloon_bundle_id TEXT,
    group_title TEXT,
    group_action_type INTEGER DEFAULT 0,
    is_audio_message INTEGER DEFAULT 0
);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, message_date INTEGER);
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
CREATE TABLE attachment (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
    guid TEXT NOT NULL,
    filename TEXT,
    mime_type TEXT,
    transfer_name TEXT,
    total_bytes INTEGER DEFAULT 0
);
CREATE TABLE message_attachment_join (message_id INTEGER, attachment_id INTEGER);
"""


def apple_ns(moment: datetime) -> int:
    """Convert a datetime to the nanosecond form macOS 10.13+ stores."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int((moment - APPLE_EPOCH).total_seconds() * 1_000_000_000)


def attributed_body(text: str) -> bytes:
    """A streamtyped NSAttributedString blob, as Ventura+ writes them."""
    payload = text.encode("utf-8")
    if len(payload) < 0x81:
        length = bytes([len(payload)])
    else:
        length = b"\x81" + len(payload).to_bytes(2, "little")
    return (
        b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84"
        b"\x12NSAttributedString\x00\x84\x84\x08NSObject\x00\x85\x92\x84\x84"
        b"\x84\x08NSString\x01\x94\x84\x01+" + length + payload +
        b"\x86\x84\x02iI\x01\x92\x84\x84\x84\x0cNSDictionary"
    )


def build_sample_db(path: Path) -> Path:
    """Create a database with a direct chat, a group chat and an unrelated chat."""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    base = datetime(2026, 3, 3, 9, 41, tzinfo=timezone.utc)

    def add_handle(identifier: str, service: str = "iMessage") -> int:
        cursor = conn.execute(
            "INSERT INTO handle (id, country, service) VALUES (?, 'us', ?)",
            (identifier, service),
        )
        return cursor.lastrowid

    def add_chat(identifier: str, style: int, display_name: str = "") -> int:
        cursor = conn.execute(
            "INSERT INTO chat (guid, style, chat_identifier, service_name, display_name)"
            " VALUES (?, ?, ?, 'iMessage', ?)",
            ("iMessage;-;" + identifier, style, identifier, display_name),
        )
        return cursor.lastrowid

    def add_message(chat_id, minutes, is_from_me, handle_id, text=None, **kwargs):
        moment = base + timedelta(minutes=minutes)
        cursor = conn.execute(
            "INSERT INTO message (guid, text, handle_id, service, date, is_from_me,"
            " associated_message_type, attributedBody, date_edited)"
            " VALUES (?, ?, ?, 'iMessage', ?, ?, ?, ?, ?)",
            (
                "guid-{}-{}".format(chat_id, minutes),
                text,
                handle_id,
                apple_ns(moment),
                1 if is_from_me else 0,
                kwargs.get("associated_message_type", 0),
                kwargs.get("attributedBody"),
                kwargs.get("date_edited", 0),
            ),
        )
        message_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO chat_message_join (chat_id, message_id, message_date)"
            " VALUES (?, ?, ?)",
            (chat_id, message_id, apple_ns(moment)),
        )
        return message_id

    alex = add_handle("+15551234567")
    alex_email = add_handle("alex@example.com")
    jordan = add_handle("+15559876543")
    stranger = add_handle("+15550000000")

    direct = add_chat("+15551234567", 45)
    conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)", (direct, alex))
    sms_direct = add_chat("alex@example.com", 45)
    conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)", (sms_direct, alex_email))
    group = add_chat("chat123456", 43, "Weekend Trip")
    for member in (alex, jordan):
        conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)", (group, member))
    other = add_chat("+15550000000", 45)
    conn.execute("INSERT INTO chat_handle_join VALUES (?, ?)", (other, stranger))

    add_message(direct, 0, False, alex, "Hey! Are we still on for dinner at 7?")
    add_message(direct, 2, True, alex, "Yes — booked a table for two.")
    add_message(direct, 5, False, alex, None,
                attributedBody=attributed_body("Perfect. I'll drive 🚗"))
    add_message(direct, 7, True, alex, "See you then <3 & thanks!", date_edited=apple_ns(base))
    add_message(direct, 9, False, alex, 'Loved "See you then <3 & thanks!"',
                associated_message_type=2000)
    photo = add_message(direct, 12, False, alex, None)
    attachment = conn.execute(
        "INSERT INTO attachment (guid, filename, mime_type, transfer_name, total_bytes)"
        " VALUES ('att-1', '~/Library/Messages/Attachments/ab/IMG_0042.HEIC',"
        " 'image/heic', 'IMG_0042.HEIC', 2411724)"
    ).lastrowid
    conn.execute("INSERT INTO message_attachment_join VALUES (?, ?)", (photo, attachment))
    # Next day, and on the email handle rather than the phone number.
    add_message(sms_direct, 1500, False, alex_email, "Morning! Great night.")
    add_message(sms_direct, 1502, True, alex_email, "Agreed. Same time next week?")

    add_message(group, 30, False, jordan, "Anyone up for hiking Saturday?")
    add_message(group, 32, False, alex, "I'm in.")
    add_message(group, 34, True, jordan, "Count me in too.")

    add_message(other, 40, False, stranger, "Wrong number, sorry.")

    conn.commit()
    conn.close()
    return path


# The columns a 2013-era chat.db had, to prove the reader tolerates old schemas.
LEGACY_SCHEMA = """
CREATE TABLE handle (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, service TEXT
);
CREATE TABLE chat (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT, style INTEGER,
    chat_identifier TEXT, service_name TEXT, display_name TEXT
);
CREATE TABLE message (
    ROWID INTEGER PRIMARY KEY AUTOINCREMENT, guid TEXT, text TEXT,
    handle_id INTEGER DEFAULT 0, date INTEGER, is_from_me INTEGER DEFAULT 0
);
CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER);
CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
"""


def build_legacy_db(path: Path) -> Path:
    """A database missing every column added after macOS 10.9."""
    conn = sqlite3.connect(str(path))
    conn.executescript(LEGACY_SCHEMA)
    conn.execute("INSERT INTO handle (id, service) VALUES ('+15551234567','iMessage')")
    conn.execute("INSERT INTO chat (guid, style, chat_identifier, service_name, display_name)"
                 " VALUES ('g', 45, '+15551234567', 'iMessage', '')")
    conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
    base = datetime(2013, 6, 1, 12, 0, tzinfo=timezone.utc)
    for index, (from_me, text) in enumerate([(0, "Old message in"), (1, "Old message out")]):
        # Seconds since the Apple epoch, as this vintage stored them.
        seconds = int((base - APPLE_EPOCH).total_seconds()) + index * 60
        conn.execute("INSERT INTO message (guid, text, handle_id, date, is_from_me)"
                     " VALUES (?,?,1,?,?)", ("old%d" % index, text, seconds, from_me))
        conn.execute("INSERT INTO chat_message_join VALUES (1, ?)", (index + 1,))
    conn.commit()
    conn.close()
    return path


def build_edge_case_db(path: Path) -> Path:
    """Rows that a naive exporter silently loses."""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO handle (id, country, service) VALUES ('+15551234567','us','iMessage')")
    conn.execute("INSERT INTO handle (id, country, service) VALUES ('+15559999999','us','SMS')")
    # A one-to-one chat that also lists a stale second participant.
    conn.execute("INSERT INTO chat (guid, style, chat_identifier, service_name, display_name)"
                 " VALUES ('g1', 45, '+15551234567', 'iMessage', '')")
    conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
    conn.execute("INSERT INTO chat_handle_join VALUES (1, 2)")
    base = datetime(2026, 5, 4, 14, 0, tzinfo=timezone.utc)

    rows = [
        # text, is_from_me, extra column values
        ("A normal message", 0, {}),
        (None, 1, {"balloon_bundle_id": "com.apple.messages.URLBalloonProvider"}),
        (None, 0, {"balloon_bundle_id":
                   "com.apple.messages.MSMessageExtensionBalloonPlugin:0000:com.apple.PassKit.Payment"}),
        (None, 1, {"is_audio_message": 1}),
        (None, 0, {"item_type": 2, "group_title": "Trip planning"}),
        (None, 0, {"attributedBody": b"\x04\x0bstreamtyped garbage that will not decode"}),
        (None, 1, {}),
        ("Last one", 0, {}),
    ]
    for index, (text, from_me, extra) in enumerate(rows):
        moment = base + timedelta(minutes=index)
        conn.execute(
            "INSERT INTO message (guid, text, handle_id, service, date, is_from_me,"
            " attributedBody, balloon_bundle_id, group_title, item_type, is_audio_message)"
            " VALUES (?,?,1,'iMessage',?,?,?,?,?,?,?)",
            ("e%d" % index, text, apple_ns(moment), from_me,
             extra.get("attributedBody"), extra.get("balloon_bundle_id"),
             extra.get("group_title"), extra.get("item_type", 0),
             extra.get("is_audio_message", 0)))
        conn.execute("INSERT INTO chat_message_join (chat_id, message_id, message_date)"
                     " VALUES (1, ?, ?)", (index + 1, apple_ns(moment)))

    # An orphan: a real message that was never joined to a chat.
    conn.execute(
        "INSERT INTO message (guid, text, handle_id, service, date, is_from_me)"
        " VALUES ('orphan', 'Message with no chat row', 1, 'iMessage', ?, 0)",
        (apple_ns(base + timedelta(minutes=30)),))
    conn.commit()
    conn.close()
    return path


def build_large_db(path: Path, count: int = 4000) -> Path:
    """A single long-running thread, for checking the export scales."""
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO handle (id, country, service) VALUES ('+15551234567','us','iMessage')")
    conn.execute("INSERT INTO chat (guid, style, chat_identifier, service_name, display_name)"
                 " VALUES ('g', 45, '+15551234567', 'iMessage', '')")
    conn.execute("INSERT INTO chat_handle_join VALUES (1, 1)")
    base = datetime(2019, 1, 1, 9, 0, tzinfo=timezone.utc)
    messages, joins = [], []
    for index in range(count):
        moment = base + timedelta(minutes=index * 37)
        text = "message number {}".format(index)
        body = None
        if index % 5 == 0:
            body, text = attributed_body(text), None
        messages.append(("m%d" % index, text, apple_ns(moment), index % 2, body))
        joins.append((1, index + 1, apple_ns(moment)))
    conn.executemany(
        "INSERT INTO message (guid, text, handle_id, service, date, is_from_me,"
        " attributedBody) VALUES (?,?,1,'iMessage',?,?,?)", messages)
    conn.executemany(
        "INSERT INTO chat_message_join (chat_id, message_id, message_date) VALUES (?,?,?)",
        joins)
    conn.commit()
    conn.close()
    return path
