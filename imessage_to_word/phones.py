"""Phone-number / iMessage-handle matching.

iMessage stores handles in a few shapes: "+15551234567", "5551234567",
"(555) 123-4567" and email addresses for Apple ID conversations.  This module
decides when two of those mean the same person, so a number typed into the app
finds the right conversation regardless of how either side is written.
"""
from __future__ import annotations

import re
from typing import Optional

_NON_DIGITS = re.compile(r"[^0-9]")

def is_email(value: str) -> bool:
    return "@" in (value or "")


def digits_only(value: str) -> str:
    return _NON_DIGITS.sub("", value or "")


# The fewest trailing digits that may stand in for a whole number, so that a
# local seven-digit number still finds a contact stored in full.
MIN_SUFFIX_DIGITS = 7

# Apple's own identifier for a group conversation; never a person's number.
GROUP_CHAT_PREFIX = "chat"


def same_handle(a: str, b: str) -> bool:
    """Do two handles refer to the same person?

    Emails must match exactly (ignoring case).  Phone numbers match when their
    digits are equal, or when one is a trailing part of the other -- which is
    what makes "+1 (555) 123-4567", "5551234567" and "123-4567" the same line.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return False
    if is_email(a) or is_email(b):
        return is_email(a) and is_email(b) and a.lower() == b.lower()

    digits_a, digits_b = digits_only(a), digits_only(b)
    if not digits_a or not digits_b:
        return False
    if digits_a == digits_b:
        return True
    shorter, longer = sorted((digits_a, digits_b), key=len)
    if len(shorter) < MIN_SUFFIX_DIGITS:
        return False
    return longer.endswith(shorter)


def matches_any(candidate: str, targets) -> bool:
    """Does ``candidate`` refer to any of ``targets``?"""
    if isinstance(targets, str):
        targets = [targets]
    return any(same_handle(candidate, target) for target in targets or [])


def is_group_identifier(value: str) -> bool:
    """True for Apple's synthetic group-chat ids, e.g. "chat618033988749"."""
    value = (value or "").strip().lower()
    return value.startswith(GROUP_CHAT_PREFIX) and not is_email(value)


def format_pretty(value: str) -> str:
    """Human-friendly rendering of a handle for the document header."""
    value = (value or "").strip()
    if not value or is_email(value):
        return value
    digits = digits_only(value)
    if len(digits) == 10:
        return "({}) {}-{}".format(digits[0:3], digits[3:6], digits[6:10])
    if len(digits) == 11 and digits.startswith("1"):
        return "+1 ({}) {}-{}".format(digits[1:4], digits[4:7], digits[7:11])
    if value.startswith("+"):
        return value
    if len(digits) > 11:
        return "+" + digits
    return value


# macOS allows 255 bytes; leave room for the date and extension we add.
MAX_FILENAME_CHARS = 80


def safe_filename(value: str) -> str:
    """Turn a name or number into something usable as a file name."""
    cleaned = re.sub(r"[^\w\s.@()+-]", "", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if len(cleaned) > MAX_FILENAME_CHARS:
        cleaned = cleaned[:MAX_FILENAME_CHARS].rstrip(" .")
    return cleaned or "conversation"


def looks_like_handle(value: str) -> Optional[str]:
    """Validate user input; returns an error message, or None when it's fine."""
    value = (value or "").strip()
    if not value:
        return "Enter a phone number (or an Apple ID email address)."
    if is_email(value):
        return None
    if len(digits_only(value)) < 3:
        return "That doesn't look like a phone number."
    return None
