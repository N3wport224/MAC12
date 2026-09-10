"""Data types shared across the exporter."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional

# Apple's Core Data epoch: 2001-01-01 00:00:00 UTC.
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


def apple_time_to_datetime(value) -> Optional[datetime]:
    """Convert a chat.db timestamp to a local-time datetime.

    Old databases store seconds since the Apple epoch; macOS 10.13+ stores
    nanoseconds.  The magnitude tells the two apart.
    """
    if value is None:
        return None
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw == 0:
        return None
    seconds = raw / 1_000_000_000 if abs(raw) > 10 ** 11 else float(raw)
    try:
        return (APPLE_EPOCH + timedelta(seconds=seconds)).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


@dataclass
class Attachment:
    name: str
    mime_type: Optional[str] = None
    total_bytes: int = 0

    def describe(self) -> str:
        kind = (self.mime_type or "").split("/")[0]
        label = {
            "image": "Photo",
            "video": "Video",
            "audio": "Audio message",
        }.get(kind, "Attachment")
        return "{}: {}".format(label, self.name) if self.name else label


@dataclass
class FetchStats:
    """A tally of what happened to every message row we looked at.

    The point is to be able to say "1,203 of 1,203 messages exported" rather
    than hoping nothing fell through a filter.
    """
    rows_seen: int = 0
    exported: int = 0
    reactions_skipped: int = 0
    outside_date_range: int = 0
    placeholders: int = 0
    unreadable_bodies: int = 0

    @property
    def accounted_for(self) -> int:
        return self.exported + self.reactions_skipped + self.outside_date_range

    def summary(self) -> str:
        parts = ["{:,} of {:,} messages exported".format(self.exported, self.rows_seen)]
        if self.reactions_skipped:
            parts.append("{:,} {} left out".format(
                self.reactions_skipped,
                "tapback" if self.reactions_skipped == 1 else "tapbacks",
            ))
        if self.outside_date_range:
            parts.append("{:,} outside the date range".format(self.outside_date_range))
        if self.placeholders:
            parts.append("{:,} had no readable text".format(self.placeholders))
        return "; ".join(parts)


@dataclass
class Message:
    rowid: int
    date: Optional[datetime]
    is_from_me: bool
    sender_handle: Optional[str]
    # Set for group chats, where the "them" side can be more than one person.
    sender_handle_name: Optional[str] = None
    text: str = ""
    service: Optional[str] = None
    chat_id: Optional[int] = None
    chat_name: Optional[str] = None
    is_group: bool = False
    is_reaction: bool = False
    is_edited: bool = False
    # True when the row carried no readable text and we substituted a note
    # such as "[Link preview]" rather than dropping the message.
    is_placeholder: bool = False
    attachments: List[Attachment] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.text or self.attachments)


@dataclass
class Conversation:
    """Everything the document needs about one person's chat history."""
    query: str
    display_name: str
    handles: List[str] = field(default_factory=list)
    messages: List[Message] = field(default_factory=list)
    chat_names: List[str] = field(default_factory=list)
    included_group_chats: bool = False
    stats: "FetchStats" = field(default_factory=lambda: FetchStats())

    @property
    def first_date(self) -> Optional[datetime]:
        for message in self.messages:
            if message.date:
                return message.date
        return None

    @property
    def last_date(self) -> Optional[datetime]:
        for message in reversed(self.messages):
            if message.date:
                return message.date
        return None

    def count_from_me(self) -> int:
        return sum(1 for m in self.messages if m.is_from_me)

    def count_from_them(self) -> int:
        return sum(1 for m in self.messages if not m.is_from_me)
