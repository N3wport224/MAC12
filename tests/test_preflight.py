"""The setup check has to be right about whether tonight's export will work."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from imessage_to_word import chatdb, preflight
from tests.fixtures import build_sample_db


def statuses(checks):
    return {check.name: check.status for check in checks}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def test_a_working_setup_reports_no_failures(self):
        checks = preflight.run_checks(self.db)
        self.assertFalse([c for c in checks if c.status == preflight.FAIL],
                         preflight.report(checks))
        self.assertEqual(statuses(checks)["Full Disk Access"], preflight.OK)
        self.assertEqual(statuses(checks)["End-to-end self test"], preflight.OK)

    def test_the_message_count_is_reported(self):
        history = [c for c in preflight.run_checks(self.db) if c.name == "Message history"]
        self.assertEqual(history[0].status, preflight.OK)
        self.assertIn("12 messages", history[0].detail)

    def test_a_missing_database_fails_with_an_explanation(self):
        checks = preflight.run_checks(self.temp / "not-here.db")
        failure = [c for c in checks if c.status == preflight.FAIL][0]
        self.assertIn("Messages", failure.name + failure.detail)

    def test_blocked_access_names_full_disk_access_and_the_restart(self):
        with mock.patch.object(chatdb, "check_access",
                               side_effect=chatdb.ChatDBPermissionError("blocked")):
            checks = preflight.run_checks(self.db)
        failure = [c for c in checks if c.status == preflight.FAIL][0]
        self.assertEqual(failure.name, "Full Disk Access")
        self.assertIn("QUIT AND REOPEN", failure.detail)

    def test_an_empty_database_is_reported_as_nothing_to_export(self):
        import sqlite3
        empty = self.temp / "empty.db"
        build_sample_db(empty)
        conn = sqlite3.connect(str(empty))
        conn.execute("DELETE FROM message")
        conn.commit()
        conn.close()
        checks = preflight.run_checks(empty)
        failure = [c for c in checks if c.status == preflight.FAIL][0]
        self.assertEqual(failure.name, "Message history")
        self.assertIn("iCloud", failure.detail)

    def test_report_tells_you_what_to_do_next(self):
        good = preflight.report(preflight.run_checks(self.db))
        self.assertIn("Ready.", good)
        self.assertIn("--list", good)

        bad = preflight.report([preflight.Check("Full Disk Access", preflight.FAIL, "no")])
        self.assertIn("Not ready yet", bad)
        self.assertIn("Full Disk Access", bad)

    def test_missing_tkinter_is_a_note_not_a_failure(self):
        # The window needs Tk; the command line does not, so this must not block.
        with mock.patch.object(preflight.importlib, "import_module",
                               side_effect=ImportError("no tkinter")):
            check = preflight._check_tkinter()
        self.assertEqual(check.status, preflight.WARN)
        self.assertIn("imessage_to_word", check.detail)

    def test_the_self_test_runs_a_whole_export(self):
        check = preflight._check_end_to_end()
        self.assertEqual(check.status, preflight.OK, check.detail)
        self.assertIn("Word and text", check.detail)

    def test_the_self_test_decodes_an_archived_message(self):
        # The second message has no text column, only an attributedBody blob,
        # which is how recent macOS stores things.
        from imessage_to_word.attributed_body import decode_attributed_body
        blob = preflight._self_test_body(preflight.SELF_TEST_LINES[1])
        self.assertEqual(decode_attributed_body(blob), preflight.SELF_TEST_LINES[1])

    def test_the_self_test_fails_loudly_if_the_export_breaks(self):
        from imessage_to_word import export as export_module
        with mock.patch.object(export_module, "export_to_word",
                               side_effect=RuntimeError("writer is broken")):
            check = preflight._check_end_to_end()
        self.assertEqual(check.status, preflight.FAIL)
        self.assertIn("writer is broken", check.detail)

    def test_the_self_test_tidies_up_after_itself(self):
        import glob
        before = set(glob.glob(tempfile.gettempdir() + "/imessage-selftest-*"))
        preflight._check_end_to_end()
        after = set(glob.glob(tempfile.gettempdir() + "/imessage-selftest-*"))
        self.assertEqual(after - before, set())

    def test_the_self_test_appears_in_the_report(self):
        checks = preflight.run_checks(self.db)
        self.assertIn("End-to-end self test", statuses(checks))


if __name__ == "__main__":
    unittest.main()
