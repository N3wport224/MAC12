"""Decode the ``message.attributedBody`` column of chat.db.

Since macOS Ventura many messages arrive with a NULL ``text`` column and the
body living only in ``attributedBody`` -- an NSAttributedString serialised with
NSArchiver's legacy "streamtyped" format.  A full typedstream parser is
overkill here: the message body is the first NSString in the stream, so we find
that class marker and read the length-prefixed UTF-8 payload behind it.
"""
from __future__ import annotations

from typing import Optional, Tuple

_CLASS_MARKERS = (b"NSMutableString", b"NSString")
# The value marker that precedes the string length in a streamtyped archive.
_VALUE_MARKER = b"\x01+"
# Object-replacement character; iMessage uses it as an attachment placeholder.
OBJECT_REPLACEMENT = "￼"


def _read_length(data: bytes, index: int) -> Optional[Tuple[int, int]]:
    """Read a typedstream length prefix. Returns (length, next_index)."""
    if index >= len(data):
        return None
    first = data[index]
    if first < 0x81:
        return first, index + 1
    width = {0x81: 2, 0x82: 4, 0x83: 8}.get(first)
    if width is None:
        return None
    end = index + 1 + width
    if end > len(data):
        return None
    return int.from_bytes(data[index + 1:end], "little"), end


def _decode_at(data: bytes, marker_end: int) -> Optional[str]:
    """Decode the string that follows a class marker ending at ``marker_end``."""
    # The value marker sits within a few bytes of the class name.
    window = data[marker_end:marker_end + 16]
    offset = window.find(_VALUE_MARKER)
    if offset < 0:
        return None
    read = _read_length(data, marker_end + offset + len(_VALUE_MARKER))
    if read is None:
        return None
    length, start = read
    if length <= 0 or start + length > len(data):
        return None
    try:
        return data[start:start + length].decode("utf-8")
    except UnicodeDecodeError:
        return data[start:start + length].decode("utf-8", errors="replace")


def decode_attributed_body(blob) -> Optional[str]:
    """Best-effort extraction of the message text from an attributedBody blob."""
    if not blob:
        return None
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    if isinstance(blob, str):
        return blob
    if not isinstance(blob, (bytes, bytearray)):
        return None
    data = bytes(blob)

    best = None
    for marker in _CLASS_MARKERS:
        index = data.find(marker)
        if index < 0:
            continue
        text = _decode_at(data, index + len(marker))
        if text and (best is None or index < best[0]):
            best = (index, text)
    if best is None:
        return None
    return best[1]


def clean_text(text: Optional[str]) -> str:
    """Normalise message text for display in a document."""
    if not text:
        return ""
    # iMessage marks inline attachments with U+FFFC; the attachment itself is
    # listed separately, so drop the placeholder rather than show a tofu box.
    text = text.replace(OBJECT_REPLACEMENT, " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Strip control characters that are illegal in XML (and so in .docx).
    text = "".join(
        ch for ch in text
        if ch in "\n\t" or (ord(ch) >= 0x20 and ord(ch) != 0x7F)
    )
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()
