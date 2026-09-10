import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from imessage_to_word.cli import main
from tests.fixtures import build_sample_db


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_export_writes_a_document_and_reports_the_counts(self):
        target = self.temp / "cli.docx"
        code, out, _ = self.run_cli(
            "555-123-4567", "--db", str(self.db), "--name", "Alex",
            "--me", "Andrew", "--no-contacts", "-o", str(target),
        )
        self.assertEqual(code, 0)
        self.assertTrue(target.exists())
        self.assertIn("5 messages", out)
        self.assertIn("3 from Alex", out)
        self.assertIn("2 from Andrew", out)

    def test_list_shows_known_handles(self):
        code, out, _ = self.run_cli("--db", str(self.db), "--list", "--no-contacts")
        self.assertEqual(code, 0)
        self.assertIn("+15551234567", out)
        self.assertIn("Messages", out)

    def test_unknown_number_exits_non_zero(self):
        code, _, err = self.run_cli(
            "555-000-9999", "--db", str(self.db), "--no-contacts",
            "-o", str(self.temp / "none.docx"),
        )
        self.assertEqual(code, 1)
        self.assertIn("No messages found", err)

    def test_bad_date_is_reported(self):
        code, _, err = self.run_cli(
            "555-123-4567", "--db", str(self.db), "--from", "yesterday",
            "--no-contacts", "-o", str(self.temp / "x.docx"),
        )
        self.assertEqual(code, 1)
        self.assertIn("Could not read the date", err)

    def test_no_arguments_prints_help(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("usage", out.lower())

    def test_date_range_flags_are_applied(self):
        target = self.temp / "range.docx"
        code, out, _ = self.run_cli(
            "555-123-4567", "--db", str(self.db), "--no-contacts",
            "--from", "2026-03-04", "-o", str(target),
        )
        # Only the email-handle thread falls after that date, and it is not
        # linked without a Contacts lookup, so nothing should be found.
        self.assertEqual(code, 1)


class NewFlagTests(CliTests):
    def test_check_passes_on_a_readable_database(self):
        code, out, _ = self.run_cli("--check", "--db", str(self.db))
        self.assertEqual(code, 0)
        self.assertIn("Ready.", out)

    def test_check_fails_when_the_database_is_missing(self):
        code, out, _ = self.run_cli("--check", "--db", str(self.temp / "gone.db"))
        self.assertEqual(code, 1)
        self.assertIn("Not ready yet", out)

    def test_text_flag_writes_a_plain_text_copy(self):
        target = self.temp / "both.docx"
        code, out, _ = self.run_cli("555-123-4567", "--db", str(self.db),
                                    "--no-contacts", "--text", "-o", str(target))
        self.assertEqual(code, 0)
        self.assertTrue(target.with_suffix(".txt").exists())
        self.assertIn(".txt", out)

    def test_completeness_is_reported(self):
        code, out, _ = self.run_cli("555-123-4567", "--db", str(self.db),
                                    "--no-contacts", "-o", str(self.temp / "c.docx"))
        self.assertEqual(code, 0)
        self.assertIn("of 6 messages exported", out)

    def test_no_copy_reads_the_database_in_place(self):
        code, _, _ = self.run_cli("555-123-4567", "--db", str(self.db), "--no-contacts",
                                  "--no-copy", "-o", str(self.temp / "nc.docx"))
        self.assertEqual(code, 0)

    def test_interactive_mode_asks_for_the_details(self):
        # number, their name, my name, groups?, preview?, save?, open?
        answers = iter(["555-123-4567", "Alex", "Andrew", "n", "y", "y", "n"])
        target = self.temp / "ask.docx"
        with mock.patch("builtins.input", lambda *args: next(answers)):
            code, out, _ = self.run_cli("--interactive", "--db", str(self.db),
                                        "--no-contacts", "-o", str(target))
        self.assertEqual(code, 0)
        self.assertTrue(target.exists())
        self.assertTrue(target.with_suffix(".txt").exists())
        self.assertIn("3 from Alex", out)
        self.assertIn("dinner at 7", out)   # the preview it was shown

    def test_interactive_mode_re_asks_after_a_bad_number(self):
        answers = iter(["", "y", "555-123-4567", "", "", "n", "n", "y", "n"])
        with mock.patch("builtins.input", lambda *args: next(answers)):
            code, out, _ = self.run_cli("--interactive", "--db", str(self.db),
                                        "--no-contacts", "-o", str(self.temp / "retry.docx"))
        self.assertEqual(code, 0)
        self.assertIn("Enter a phone number", out)


class PreviewFlagTests(CliTests):
    def test_preview_prints_the_conversation_and_writes_nothing(self):
        target = self.temp / "nope.docx"
        code, out, _ = self.run_cli("555-123-4567", "--db", str(self.db), "--name", "Alex",
                                    "--me", "Andrew", "--no-contacts", "--preview",
                                    "-o", str(target))
        self.assertEqual(code, 0)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix(".txt").exists())
        self.assertIn("Hey! Are we still on for dinner at 7?", out)
        self.assertIn("[9:41 AM] Alex:", out)
        self.assertIn("Andrew:", out)
        self.assertIn("Previewed:", out)
        self.assertIn("Nothing was written", out)

    def test_preview_takes_a_message_count(self):
        code, out, _ = self.run_cli("555-123-4567", "--db", str(self.db), "--name", "Alex",
                                    "--no-contacts", "--preview", "2",
                                    "-o", str(self.temp / "x.docx"))
        self.assertEqual(code, 0)
        shown = [line for line in out.splitlines() if line.startswith("[")]
        self.assertEqual(len(shown), 2)
        self.assertIn("not shown here", out)
        self.assertIn("3 messages not shown", out)

    def test_preview_zero_shows_everything(self):
        code, out, _ = self.run_cli("555-123-4567", "--db", str(self.db), "--name", "Alex",
                                    "--no-contacts", "--preview", "0",
                                    "-o", str(self.temp / "x.docx"))
        self.assertEqual(code, 0)
        shown = [line for line in out.splitlines() if line.startswith("[")]
        self.assertEqual(len(shown), 5)
        self.assertNotIn("not shown here", out)

    def test_declining_to_save_in_interactive_mode_writes_nothing(self):
        target = self.temp / "declined.docx"
        answers = iter(["555-123-4567", "Alex", "Andrew", "n", "y", "n"])
        with mock.patch("builtins.input", lambda *args: next(answers)):
            code, out, _ = self.run_cli("--interactive", "--db", str(self.db),
                                        "--no-contacts", "-o", str(target))
        self.assertEqual(code, 0)
        self.assertFalse(target.exists())
        self.assertIn("Nothing was written", out)


if __name__ == "__main__":
    unittest.main()
