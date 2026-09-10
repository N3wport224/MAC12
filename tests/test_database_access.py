"""How the app gets at chat.db: safely, completely, and without hanging."""
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from imessage_to_word import chatdb
from imessage_to_word.export import ExportOptions, export_to_word
from tests.fixtures import apple_ns, build_sample_db

ALEX = "555-123-4567"
WAL_TEXT = "THIS MESSAGE IS ONLY IN THE WAL"


def export(db, temp, filename="out.docx", **kwargs):
    options = ExportOptions(number=ALEX, their_name="Alex", db_path=db,
                            lookup_contact_name=False, link_contact_handles=False,
                            also_text=True, **kwargs)
    return export_to_word(options, output_path=temp / filename)


class WalTests(unittest.TestCase):
    """Messages runs in WAL mode, so the newest messages are not in chat.db."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")
        self.live = sqlite3.connect(str(self.db))
        self.live.execute("PRAGMA journal_mode=WAL")
        when = apple_ns(datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc))
        self.live.execute(
            "INSERT INTO message (guid, text, handle_id, service, date, is_from_me)"
            " VALUES ('wal1', ?, 1, 'iMessage', ?, 0)", (WAL_TEXT, when))
        self.live.execute(
            "INSERT INTO chat_message_join (chat_id, message_id, message_date)"
            " VALUES (1, (SELECT MAX(ROWID) FROM message), ?)", (when,))
        self.live.commit()

    def tearDown(self):
        self.live.close()

    def test_the_write_ahead_log_really_does_hold_the_message(self):
        wal = Path(str(self.db) + "-wal")
        self.assertTrue(wal.exists() and wal.stat().st_size > 0)

    def test_snapshot_mode_captures_it(self):
        result = export(self.db, self.temp)
        self.assertIn(WAL_TEXT, result.text_path.read_text(encoding="utf-8"))

    def test_reading_in_place_captures_it_too(self):
        result = export(self.db, self.temp, filename="inplace.docx", copy_database=False)
        self.assertIn(WAL_TEXT, result.text_path.read_text(encoding="utf-8"))

    def test_a_stale_immutable_read_warns_that_messages_may_be_missing(self):
        warnings = []
        # Force the last-resort path, which cannot see the write-ahead log.
        real_connect = sqlite3.connect

        def only_immutable(target, *args, **kwargs):
            if isinstance(target, str) and "mode=ro" in target and "immutable" not in target:
                raise sqlite3.OperationalError("unable to open database file")
            return real_connect(target, *args, **kwargs)

        with mock.patch.object(chatdb.sqlite3, "connect", side_effect=only_immutable):
            with chatdb.open_chat_db(self.db, copy=False,
                                     on_warning=warnings.append) as conn:
                found = conn.execute(
                    "SELECT COUNT(*) FROM message WHERE text = ?", (WAL_TEXT,)
                ).fetchone()[0]
        self.assertEqual(found, 0, "immutable mode should not see the WAL")
        self.assertTrue(warnings, "a silent stale read is the thing to avoid")
        self.assertIn("may be missing", warnings[0])


    def test_the_warning_reaches_the_export_result(self):
        real_connect = sqlite3.connect

        def only_immutable(target, *args, **kwargs):
            if isinstance(target, str) and "mode=ro" in target and "immutable" not in target:
                raise sqlite3.OperationalError("unable to open database file")
            return real_connect(target, *args, **kwargs)

        with mock.patch.object(chatdb.sqlite3, "connect", side_effect=only_immutable):
            result = export(self.db, self.temp, filename="stale.docx",
                            copy_database=False)
        self.assertTrue(result.warnings, "the person has to be told")
        self.assertIn("may be missing", result.warnings[0])


class LockedDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_a_locked_database_still_exports_and_does_not_hang(self):
        locker = sqlite3.connect(str(self.db))
        locker.execute("BEGIN EXCLUSIVE")
        try:
            started = time.time()
            result = export(self.db, self.temp, filename="locked.docx")
            elapsed = time.time() - started
        finally:
            locker.rollback()
            locker.close()
        self.assertEqual(result.message_count, 5)
        # The backup API retries a locked source forever; this must not.
        self.assertLess(elapsed, 30, "took {:.1f}s".format(elapsed))

    def test_the_snapshot_watchdog_gives_up_instead_of_spinning(self):
        locker = sqlite3.connect(str(self.db))
        locker.execute("BEGIN EXCLUSIVE")
        try:
            with self.assertRaises((chatdb.SnapshotStalled, sqlite3.Error)):
                chatdb._snapshot(self.db, self.temp / "snap.db", stall_seconds=1.0)
        finally:
            locker.rollback()
            locker.close()

    def test_export_falls_back_when_the_backup_api_is_unavailable(self):
        with mock.patch.object(chatdb, "_snapshot",
                               side_effect=AttributeError("no backup on this Python")):
            result = export(self.db, self.temp, filename="nobackup.docx")
        self.assertEqual(result.message_count, 5)


class PathTests(unittest.TestCase):
    def test_a_home_folder_with_spaces_is_handled(self):
        # "/Users/John Smith/Library/Messages/chat.db" has to work.
        temp = Path(tempfile.mkdtemp()) / "John Smith's Mac"
        temp.mkdir()
        db = build_sample_db(temp / "chat.db")
        for copy in (True, False):
            result = export(db, temp, filename="spaces{}.docx".format(copy),
                            copy_database=copy)
            self.assertEqual(result.message_count, 5)

    def test_a_path_with_a_hash_or_question_mark_is_handled(self):
        temp = Path(tempfile.mkdtemp()) / "odd #1 (test?)"
        temp.mkdir()
        db = build_sample_db(temp / "chat.db")
        result = export(db, temp, filename="odd.docx", copy_database=False)
        self.assertEqual(result.message_count, 5)


class CorruptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())

    def test_a_file_that_is_not_a_database_is_reported_in_plain_english(self):
        fake = self.temp / "chat.db"
        fake.write_bytes(b"this is not a database" * 100)
        with self.assertRaises(chatdb.ChatDBError) as caught:
            export(fake, self.temp, filename="bad.docx")
        message = str(caught.exception)
        self.assertNotIn("Traceback", message)
        self.assertTrue(len(message) > 20, message)

    def test_a_truncated_database_does_not_produce_a_stack_trace(self):
        db = build_sample_db(self.temp / "chat.db")
        data = db.read_bytes()
        db.write_bytes(data[: len(data) // 3])
        with self.assertRaises(chatdb.ChatDBError):
            export(db, self.temp, filename="trunc.docx")


class NonInterferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_the_live_database_is_byte_for_byte_unchanged(self):
        before = self.db.read_bytes()
        export(self.db, self.temp)
        self.assertEqual(self.db.read_bytes(), before)

    def test_no_sidecar_files_are_left_behind(self):
        export(self.db, self.temp)
        for suffix in ("-wal", "-shm", "-journal"):
            self.assertFalse(Path(str(self.db) + suffix).exists(), suffix)

    def test_the_temporary_copy_is_cleaned_up(self):
        import glob
        before = set(glob.glob(tempfile.gettempdir() + "/imessage-export-*"))
        export(self.db, self.temp)
        after = set(glob.glob(tempfile.gettempdir() + "/imessage-export-*"))
        self.assertEqual(after - before, set())

    def test_the_copy_is_cleaned_up_even_when_the_export_fails(self):
        import glob
        before = set(glob.glob(tempfile.gettempdir() + "/imessage-export-*"))
        with mock.patch.object(chatdb, "fetch_messages", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                export(self.db, self.temp, filename="fail.docx")
        after = set(glob.glob(tempfile.gettempdir() + "/imessage-export-*"))
        self.assertEqual(after - before, set())


if __name__ == "__main__":
    unittest.main()
