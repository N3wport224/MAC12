"""Export an iMessage conversation to a Word document.

Public entry points:
    export_to_word(ExportOptions(...))  -> ExportResult
"""
from __future__ import annotations

from .chatdb import (
    ChatDBError,
    ChatDBNotFound,
    ChatDBPermissionError,
    DEFAULT_DB_PATH,
    FULL_DISK_ACCESS_HELP,
)
from .export import (
    ExportError,
    ExportOptions,
    ExportResult,
    NoMessagesFound,
    default_output_path,
    export_to_word,
)

__version__ = "1.0.0"

__all__ = [
    "ChatDBError",
    "ChatDBNotFound",
    "ChatDBPermissionError",
    "DEFAULT_DB_PATH",
    "FULL_DISK_ACCESS_HELP",
    "ExportError",
    "ExportOptions",
    "ExportResult",
    "NoMessagesFound",
    "default_output_path",
    "export_to_word",
    "__version__",
]
