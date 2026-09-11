"""Awkward inputs: bad bytes, odd names, hostile characters, no one at the keyboard."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import docx as python_docx      # optional: a second opinion on our output
except ImportError:
    python_docx = None

from imessage_to_word import phones
from imessage_to_word.attributed_body import clean_text
from imessage_to_word.export import (
    ExportOptions,
    as_docx_path,
    default_output_path,
    export_to_word,
    unique_path,
)
from tests.fixtures import SCHEMA, apple_ns, build_sample_db

ALEX = "555-123-4567"
REPO_ROOT = Path(__file__).resolve().parent.parent


def export(db, temp, filename="out.docx", **kwargs):
    options = ExportOptions(number=ALEX, their_name="Alex", db_path=db,
                            lookup_contact_name=False, link_contact_handles=False,
                            **kwargs)
    return export_to_word(options, output_path=temp / filename if filename else None)


class BadDataTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_a_row_of_invalid_utf8_does_not_abort_the_export(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute(
            "UPDATE message SET text = CAST(X'48690FFEFF20776F726C64' AS TEXT)"
            " WHERE ROWID = 1")
        conn.commit()
        conn.close()
        result = export(self.db, self.temp, also_text=True)
        self.assertEqual(result.message_count, 5)
        self.assertTrue(result.path.exists())

    def test_characters_word_rejects_are_stripped(self):
        # Unpaired surrogate, a non-character, and a control code.
        hostile = "before \ud800 ￾ \x0b after"
        cleaned = clean_text(hostile)
        self.assertTrue(cleaned.startswith("before"))
        self.assertTrue(cleaned.endswith("after"))
        for bad in ("\ud800", "￾", "\x0b"):
            self.assertNotIn(bad, cleaned)

    def test_a_message_full_of_markup_stays_text(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE message SET text = ? WHERE ROWID = 1",
                     ('</w:t></w:r><w:r><w:t>injected</w:t>',))
        conn.commit()
        conn.close()
        result = export(self.db, self.temp, filename="markup.docx")
        with zipfile.ZipFile(result.path) as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("&lt;/w:t&gt;", body)
        if python_docx:
            text = "\n".join(
                paragraph.text
                for paragraph in python_docx.Document(str(result.path)).paragraphs)
            self.assertIn("</w:t></w:r>", text)

    def test_a_database_with_no_attachment_tables_still_exports(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute("DROP TABLE message_attachment_join")
        conn.execute("DROP TABLE attachment")
        conn.commit()
        conn.close()
        result = export(self.db, self.temp, filename="noatt.docx")
        self.assertEqual(result.message_count, 5)

    def test_date_bounds_without_a_timezone_are_accepted(self):
        result = export(self.db, self.temp, filename="naive.docx",
                        start=datetime(2026, 3, 3, 0, 0))
        self.assertGreater(result.message_count, 0)


class OutputPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_a_destination_without_an_extension_becomes_a_docx(self):
        result = export(self.db, self.temp, filename="no-extension", also_text=True)
        self.assertEqual(result.path.name, "no-extension.docx")
        self.assertEqual(result.text_path.name, "no-extension.txt")
        self.assertTrue(result.text_path.exists())

    def test_a_name_with_dots_keeps_the_text_copy_alongside(self):
        result = export(self.db, self.temp, filename="Alex v1.2.docx", also_text=True)
        self.assertEqual(result.text_path.name, "Alex v1.2.txt")

    def test_as_docx_path_leaves_a_real_docx_alone(self):
        self.assertEqual(as_docx_path("/tmp/a.docx").name, "a.docx")
        self.assertEqual(as_docx_path("/tmp/a.DOCX").name, "a.DOCX")
        self.assertEqual(as_docx_path("/tmp/a").name, "a.docx")

    def test_the_automatic_name_never_overwrites_an_earlier_export(self):
        first = self.temp / "same.docx"
        first.write_text("previous export")
        second = unique_path(first)
        self.assertEqual(second.name, "same (2).docx")
        second.write_text("second export")
        self.assertEqual(unique_path(first).name, "same (3).docx")
        self.assertEqual(first.read_text(), "previous export")

    def test_unicode_names_produce_a_usable_file(self):
        options = ExportOptions(number=ALEX, their_name="José Álvarez-Núñez",
                                db_path=self.db, lookup_contact_name=False,
                                link_contact_handles=False)
        result = export_to_word(options, output_path=self.temp / "josé.docx")
        self.assertTrue(result.path.exists())

    def test_a_very_long_name_is_trimmed_to_a_legal_filename(self):
        name = "Alexandra " * 40
        path = default_output_path(name)
        self.assertLess(len(path.name.encode("utf-8")), 200)
        self.assertTrue(path.name.endswith(".docx"))

    def test_a_name_of_only_punctuation_still_produces_a_file(self):
        self.assertIn("conversation", default_output_path("///???").name)


class NoOneAtTheKeyboardTests(unittest.TestCase):
    """The launcher can end up running this with nothing on stdin."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_interactive_mode_exits_instead_of_looping_forever(self):
        completed = subprocess.run(
            [sys.executable, "-m", "imessage_to_word", "--interactive",
             "--db", str(self.db), "--no-contacts"],
            cwd=str(REPO_ROOT), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("Cancelled", completed.stdout + completed.stderr)


class TimeZoneTests(unittest.TestCase):
    """Timestamps are stored in UTC; the transcript has to read as local time."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.previous_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()

    def tearDown(self):
        if self.previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.previous_tz
        time.tzset()

    def build(self, moments):
        db = self.temp / "chat.db"
        conn = sqlite3.connect(str(db))
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO handle (id, country, service)"
                     " VALUES ('+15551234567','us','iMessage')")
        conn.execute("INSERT INTO chat (guid, style, chat_identifier, service_name,"
                     " display_name) VALUES ('g',45,'+15551234567','iMessage','')")
        conn.execute("INSERT INTO chat_handle_join VALUES (1,1)")
        for index, moment in enumerate(moments):
            conn.execute(
                "INSERT INTO message (guid, text, handle_id, service, date, is_from_me)"
                " VALUES (?,?,1,'iMessage',?,0)",
                ("g%d" % index, "message %d" % index, apple_ns(moment)))
            conn.execute("INSERT INTO chat_message_join (chat_id, message_id,"
                         " message_date) VALUES (1,?,?)", (index + 1, apple_ns(moment)))
        conn.commit()
        conn.close()
        return db

    def test_messages_are_shown_in_local_time_on_both_sides_of_daylight_saving(self):
        db = self.build([
            datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc),   # 10 PM Jan 1, EST
            datetime(2026, 7, 2, 3, 0, tzinfo=timezone.utc),   # 11 PM Jul 1, EDT
        ])
        result = export(db, self.temp, filename="tz.docx", also_text=True)
        content = result.text_path.read_text(encoding="utf-8")
        self.assertIn("--- Thursday, January 1, 2026 ---", content)
        self.assertIn("[10:00 PM]", content)
        self.assertIn("--- Wednesday, July 1, 2026 ---", content)
        self.assertIn("[11:00 PM]", content)

    def test_a_date_filter_uses_local_days_too(self):
        db = self.build([
            datetime(2026, 1, 2, 3, 0, tzinfo=timezone.utc),   # 10 PM Jan 1 locally
            datetime(2026, 1, 3, 3, 0, tzinfo=timezone.utc),   # 10 PM Jan 2 locally
        ])
        from imessage_to_word.export import parse_date_input
        result = export(db, self.temp, filename="tzfilter.docx", also_text=True,
                        start=parse_date_input("2026-01-02"))
        self.assertEqual(result.message_count, 1)
        self.assertIn("message 1", result.text_path.read_text(encoding="utf-8"))


class FilenameTests(unittest.TestCase):
    def test_path_separators_are_removed(self):
        self.assertNotIn("/", phones.safe_filename("Alex / Kim"))
        self.assertNotIn(":", phones.safe_filename("Alex: Kim"))

    def test_accented_names_survive(self):
        self.assertEqual(phones.safe_filename("José Núñez"), "José Núñez")

    def test_length_is_capped(self):
        self.assertLessEqual(len(phones.safe_filename("x" * 500)),
                             phones.MAX_FILENAME_CHARS)


if __name__ == "__main__":
    unittest.main()
