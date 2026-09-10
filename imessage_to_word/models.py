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
