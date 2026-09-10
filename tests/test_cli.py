import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
