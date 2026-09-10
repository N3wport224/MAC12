"""Helpers for looking at a conversation before it is written out.

Kept apart from the document code, and free of any Tk import, so the logic
behind the preview window and ``--preview`` can be tested on its own.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from .models import Message

# Characters above the Basic Multilingual Plane -- most emoji. The Tcl/Tk that
# ships with older macOS refuses them outright, so the preview may have to
# stand something else in their place. The document keeps the real characters.
ASTRAL = re.compile("[\U00010000-\U0010FFFF]")
ASTRAL_PLACEHOLDER = "□"   # □


def preview_selection(
    messages: Sequence[Message], limit: Optional[int] = None
) -> Tuple[List[Message], List[Message], int]:
    """Split messages into (beginning, end, number left out) for a preview.

    A long history previews as its start and its finish, which is what tells
    you whether you have the right conversation; the export still gets all of
    them.
    """
    messages = list(messages)
    if not limit or limit <= 0 or len(messages) <= limit:
        return messages, [], 0
    head = limit // 2
    tail = limit - head
    return messages[:head], messages[-tail:], len(messages) - limit


def gap_note(omitted: int) -> str:
    return "... {:,} messages not shown here -- all of them are in the export ...".format(
        omitted)


def searchable_text(message: Message) -> str:
    """Everything in a message that a search should look at."""
    parts = [message.text or ""]
    parts.extend(attachment.describe() for attachment in message.attachments)
    return "\n".join(part for part in parts if part)


def matches(message: Message, term: str) -> bool:
    term = (term or "").strip().lower()
    if not term:
        return False
    return term in searchable_text(message).lower()


def find_messages(
    messages: Sequence[Message], term: str, limit: Optional[int] = None
) -> Tuple[List[Message], int]:
    """Messages containing ``term``, and how many there are in total.

    ``limit`` caps how many are returned, not how many are counted.
    """
    term = (term or "").strip()
    if not term:
        return [], 0
    found = [message for message in messages if matches(message, term)]
    total = len(found)
    if limit and limit > 0:
        found = found[:limit]
    return found, total


def find_ranges(haystack: str, needle: str) -> List[Tuple[int, int]]:
    """Case-insensitive, non-overlapping (start, end) offsets of every match.

    Used instead of Tk's own text search, which segfaults on a widget holding
    characters outside the Basic Multilingual Plane.
    """
    if not haystack or not needle:
        return []
    hay, need = haystack.lower(), needle.lower()
    ranges = []
    start = 0
    while True:
        found = hay.find(need, start)
        if found < 0:
            return ranges
        ranges.append((found, found + len(need)))
        start = found + len(need)


def has_astral(text: str) -> bool:
    return bool(ASTRAL.search(text or ""))


def strip_astral(text: str, placeholder: str = ASTRAL_PLACEHOLDER) -> str:
    """Replace each astral character with one stand-in, keeping the length.

    One-for-one matters: the preview highlights matches by position, so the
    substitution must not shift anything.
    """
    return ASTRAL.sub(placeholder, text or "")
