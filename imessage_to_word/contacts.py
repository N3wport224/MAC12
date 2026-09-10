"""Best-effort contact lookup from the local AddressBook database.

Two uses: heading the document with a real name instead of a bare phone
number, and finding the person's *other* handles (a second number, an Apple ID
email) so a conversation split across them still exports as one thread.

Every failure mode -- no database, locked file, unexpected schema -- degrades
silently to "no match"; this is a nicety, never a hard dependency.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from . import phones

ADDRESS_BOOK_DIR = Path.home() / "Library" / "Application Support" / "AddressBook"

_QUERIES = (
    "SELECT r.Z_PK AS pk, r.ZFIRSTNAME AS first, r.ZLASTNAME AS last, "
    "r.ZORGANIZATION AS org, p.ZFULLNUMBER AS value "
    "FROM ZABCDPHONENUMBER p JOIN ZABCDRECORD r ON r.Z_PK = p.ZOWNER",
    "SELECT r.Z_PK AS pk, r.ZFIRSTNAME AS first, r.ZLASTNAME AS last, "
    "r.ZORGANIZATION AS org, e.ZADDRESS AS value "
    "FROM ZABCDEMAILADDRESS e JOIN ZABCDRECORD r ON r.Z_PK = e.ZOWNER",
)


@dataclass
class ContactMatch:
    name: str = ""
    identifiers: List[str] = field(default_factory=list)


def candidate_databases() -> List[Path]:
    candidates = [ADDRESS_BOOK_DIR / "AddressBook-v22.abcddb"]
    sources = ADDRESS_BOOK_DIR / "Sources"
    if sources.is_dir():
        try:
            candidates.extend(sorted(sources.glob("*/AddressBook-v22.abcddb")))
        except OSError:
            pass
    return [path for path in candidates if path.exists()]


def _full_name(row) -> str:
    parts = [(row["first"] or "").strip(), (row["last"] or "").strip()]
    return " ".join(part for part in parts if part) or (row["org"] or "").strip()


def _search_database(path: Path, key: str) -> Optional[ContactMatch]:
    temp_dir = tempfile.mkdtemp(prefix="imessage-contacts-")
    try:
        working = Path(temp_dir) / path.name
        shutil.copyfile(path, working)
        conn = sqlite3.connect(str(working))
        conn.row_factory = sqlite3.Row
        try:
            rows = []
            for sql in _QUERIES:
                try:
                    rows.extend(conn.execute(sql).fetchall())
                except sqlite3.Error:
                    continue
            owner = None
            match = ContactMatch()
            for row in rows:
                if phones.match_key(row["value"] or "") == key:
                    owner = row["pk"]
                    match.name = match.name or _full_name(row)
                    break
            if owner is None:
                return None
            # Collect every identifier on the same contact card.
            for row in rows:
                if row["pk"] == owner and row["value"]:
                    value = row["value"].strip()
                    if value and value not in match.identifiers:
                        match.identifiers.append(value)
            return match
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        return None
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def find_contact(handle: str) -> Optional[ContactMatch]:
    """Look up the Contacts card for a phone number or email address."""
    key = phones.match_key(handle)
    if not key:
        return None
    for database in candidate_databases():
        match = _search_database(database, key)
        if match:
            return match
    return None


def lookup_name(handle: str) -> Optional[str]:
    match = find_contact(handle)
    return match.name if match and match.name else None


def related_handles(handle: str) -> List[str]:
    """Other numbers / emails belonging to the same person, if Contacts knows."""
    match = find_contact(handle)
    return list(match.identifiers) if match else []
