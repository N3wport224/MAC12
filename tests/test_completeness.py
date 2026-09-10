"""Nothing should vanish silently: every row is exported, counted, or explained."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from imessage_to_word.export import ExportOptions, export_to_word
from tests.fixtures import (
    build_edge_case_db,
    build_large_db,
    build_legacy_db,
    build_sample_db,
)

ALEX = "555-123-4567"


def export(db, temp, filename="out.docx", **kwargs):
    options = ExportOptions(number=ALEX, their_name="Alex", db_path=db,
                            lookup_contact_name=False, link_contact_handles=False,
                            **kwargs)
    return export_to_word(options, output_path=temp / filename)


class StatsTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_every_row_is_accounted_for(self):
        result = export(self.db, self.temp)
        stats = result.stats
        self.assertEqual(stats.rows_seen, stats.accounted_for)
        self.assertEqual(stats.exported, result.message_count)

    def test_skipped_tapbacks_are_counted_not_hidden(self):
        result = export(self.db, self.temp)
        self.assertEqual(result.stats.reactions_skipped, 1)
        self.assertIn("1 tapback left out", result.completeness())

    def test_including_tapbacks_clears_the_skipped_count(self):
        result = export(self.db, self.temp, filename="r.docx", include_reactions=True)
        self.assertEqual(result.stats.reactions_skipped, 0)
        self.assertEqual(result.stats.exported, result.stats.rows_seen)

    def test_date_filtered_messages_are_counted(self):
        from datetime import datetime, timezone
        result = export(self.db, self.temp, filename="d.docx",
                        start=datetime(2026, 3, 3, 9, 45, tzinfo=timezone.utc))
        # Two messages predate the cutoff; the tapback is counted as a tapback.
        self.assertEqual(result.stats.outside_date_range, 2)
        self.assertEqual(result.stats.exported, 3)
        self.assertEqual(result.stats.rows_seen, result.stats.accounted_for)

    def test_the_document_states_how_complete_it_is(self):
        import zipfile
        result = export(self.db, self.temp)
        with zipfile.ZipFile(result.path) as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("Completeness", body)
        self.assertIn("of 6 messages exported", body)


class UntextedMessageTests(unittest.TestCase):
    """Messages with no text still belong in a complete history."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_edge_case_db(self.temp / "chat.db")

    def document_text(self, result):
        import zipfile
        with zipfile.ZipFile(result.path) as archive:
            return archive.read("word/document.xml").decode("utf-8")

    def test_nothing_is_dropped_by_default(self):
        result = export(self.db, self.temp)
        # 8 chat messages plus the orphan.
        self.assertEqual(result.stats.rows_seen, 9)
        self.assertEqual(result.message_count, 9)

    def test_each_kind_of_untexted_message_is_labelled(self):
        body = self.document_text(export(self.db, self.temp))
        for label in ("[Link]", "[Apple Cash]", "[Audio message]",
                      "[Message text could not be read]", "[No text]"):
            self.assertIn(label, body)
        self.assertIn("Named the conversation", body)

    def test_placeholders_are_counted(self):
        result = export(self.db, self.temp)
        self.assertEqual(result.stats.placeholders, 6)
        self.assertEqual(result.stats.unreadable_bodies, 1)
        self.assertIn("6 had no readable text", result.completeness())

    def test_placeholders_can_be_turned_off(self):
        result = export(self.db, self.temp, filename="clean.docx", include_untexted=False)
        self.assertEqual(result.message_count, 3)
        self.assertNotIn("[Link]", self.document_text(result))

    def test_messages_never_joined_to_a_chat_are_still_exported(self):
        body = self.document_text(export(self.db, self.temp))
        self.assertIn("Message with no chat row", body)

    def test_a_one_to_one_chat_with_a_stale_participant_is_still_found(self):
        # chat 1 lists a second, unrelated handle; Messages still calls it style 45.
        result = export(self.db, self.temp)
        self.assertGreater(result.message_count, 0)


class LegacySchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_legacy_db(self.temp / "chat.db")

    def test_an_old_database_without_modern_columns_still_exports(self):
        result = export(self.db, self.temp)
        self.assertEqual(result.message_count, 2)
        self.assertEqual(result.first_date.year, 2013)


class TextTranscriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_a_text_copy_is_written_next_to_the_document(self):
        result = export(self.db, self.temp, also_text=True)
        self.assertEqual(result.text_path, self.temp / "out.txt")
        content = result.text_path.read_text(encoding="utf-8")
        self.assertIn("[9:41 AM] Alex: Hey! Are we still on for dinner at 7?", content)
        self.assertIn("Tuesday, March 3, 2026", content)
        self.assertIn("Completeness:", content)

    def test_both_speakers_are_named_on_every_line(self):
        result = export(self.db, self.temp, also_text=True)
        lines = [line for line in result.text_path.read_text(encoding="utf-8").splitlines()
                 if line.startswith("[")]
        self.assertEqual(len(lines), result.message_count)
        self.assertTrue(all("Alex:" in line or "Me:" in line for line in lines))

    def test_multi_line_messages_stay_readable(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE message SET text = 'line one\nline two' WHERE ROWID = 1")
        conn.commit()
        conn.close()
        result = export(self.db, self.temp, filename="multi.docx", also_text=True)
        content = result.text_path.read_text(encoding="utf-8")
        self.assertIn("[9:41 AM] Alex: line one", content)
        self.assertIn("\n                line two", content)

    def test_continuation_lines_line_up_under_the_message(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE message SET text = 'first line\nsecond line' WHERE ROWID = 1")
        conn.commit()
        conn.close()
        result = export(self.db, self.temp, filename="align.docx", also_text=True)
        lines = result.text_path.read_text(encoding="utf-8").splitlines()
        start = next(i for i, line in enumerate(lines) if "first line" in line)
        prefix_width = lines[start].index("first line")
        self.assertEqual(lines[start + 1].index("second line"), prefix_width)

    def test_attachment_only_messages_read_inline(self):
        result = export(self.db, self.temp, also_text=True)
        content = result.text_path.read_text(encoding="utf-8")
        self.assertIn("Alex: <Photo: IMG_0042.HEIC (2.3 MB)>", content)


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_export_falls_back_when_the_database_cannot_be_copied(self):
        import shutil
        original = shutil.copyfile

        def no_space(*args, **kwargs):
            raise OSError(28, "No space left on device")

        shutil.copyfile = no_space
        try:
            result = export(self.db, self.temp, filename="fallback.docx")
        finally:
            shutil.copyfile = original
        self.assertEqual(result.message_count, 5)

    def test_a_locked_database_is_still_readable(self):
        # Hold a write transaction open, as Messages does while it is running.
        keeper = sqlite3.connect(str(self.db))
        keeper.execute("BEGIN EXCLUSIVE")
        try:
            result = export(self.db, self.temp, filename="locked.docx")
            self.assertEqual(result.message_count, 5)
        finally:
            keeper.rollback()
            keeper.close()

    def test_reading_never_writes_to_the_database(self):
        before = (self.db.read_bytes(), self.db.stat().st_mtime)
        export(self.db, self.temp, filename="ro.docx")
        self.assertEqual(self.db.read_bytes(), before[0])
        self.assertEqual(self.db.stat().st_mtime, before[1])


class ScaleTests(unittest.TestCase):
    """A years-long thread has to come out whole, and quickly."""

    MESSAGES = 4000

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_large_db(self.temp / "chat.db", self.MESSAGES)

    def test_a_long_history_exports_completely(self):
        import time
        started = time.time()
        result = export(self.db, self.temp, also_text=True)
        elapsed = time.time() - started

        self.assertEqual(result.message_count, self.MESSAGES)
        self.assertEqual(result.stats.exported, result.stats.rows_seen)
        self.assertEqual(result.from_me + result.from_them, self.MESSAGES)
        # Comfortably slow enough not to be flaky, fast enough to catch a
        # query that scales quadratically (which this once did).
        self.assertLess(elapsed, 30, "export took {:.1f}s".format(elapsed))

    def test_the_first_and_last_message_both_survive(self):
        result = export(self.db, self.temp, also_text=True)
        content = result.text_path.read_text(encoding="utf-8")
        self.assertIn("message number 0", content)
        self.assertIn("message number {}".format(self.MESSAGES - 1), content)

    def test_progress_is_reported_while_formatting(self):
        from imessage_to_word.export import ExportOptions, export_to_word
        seen = []
        export_to_word(
            ExportOptions(number=ALEX, their_name="Alex", db_path=self.db,
                          lookup_contact_name=False, link_contact_handles=False),
            output_path=self.temp / "progress.docx", progress=seen.append)
        self.assertTrue(any("Formatting message" in line for line in seen), seen)

    def test_a_big_transcript_warns_that_word_will_be_slow(self):
        from imessage_to_word.export import large_document_note
        self.assertIsNone(large_document_note(500))
        self.assertIn("plain-text copy", large_document_note(40000))


if __name__ == "__main__":
    unittest.main()
