"""Phone-number / iMessage-handle matching.

iMessage stores handles in a few shapes: "+15551234567", "5551234567",
"(555) 123-4567" and email addresses for Apple ID conversations.  This module
reduces any of those to a comparable key so a number typed into the app finds
the right conversation regardless of formatting.
"""
from __future__ import annotations

import re
from typing import Optional

_NON_DIGITS = re.compile(r"[^0-9]")

# How many trailing digits must agree for two phone numbers to be "the same
# person".  10 covers a US number without its country code, which is the usual
# reason the typed number and the stored handle disagree.
SIGNIFICANT_DIGITS = 10


def is_email(value: str) -> bool:
    return "@" in (value or "")


def digits_only(value: str) -> str:
    return _NON_DIGITS.sub("", value or "")


def match_key(value: str) -> str:
    """Return a comparable key for a handle or a typed phone number.

    Emails compare case-insensitively.  Phone numbers compare on their last
    ``SIGNIFICANT_DIGITS`` digits, so "+1 (555) 123-4567" and "5551234567"
    both key to "5551234567".  Short codes keep all of their digits.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if is_email(value):
        return value.lower()
    digits = digits_only(value)
    if not digits:
        return value.lower()
    if len(digits) > SIGNIFICANT_DIGITS:
        return digits[-SIGNIFICANT_DIGITS:]
    return digits


def same_handle(a: str, b: str) -> bool:
    key_a, key_b = match_key(a), match_key(b)
    return bool(key_a) and key_a == key_b


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


def safe_filename(value: str) -> str:
    """Turn a name or number into something usable as a file name."""
    cleaned = re.sub(r"[^\w\s.@()+-]", "", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
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


def match_keys(values) -> "set":
    """Match keys for one handle or a collection of them, blanks dropped."""
    if isinstance(values, str):
        values = [values]
    return {key for key in (match_key(value) for value in values or []) if key}
