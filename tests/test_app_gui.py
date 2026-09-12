import importlib
import sys
import tempfile
import unittest
from pathlib import Path

from tests import fake_tkinter
from tests.fixtures import build_sample_db


class AppTestCase(unittest.TestCase):
    """Drive the window logic in app.py without a display."""

    def setUp(self):
        self.had_real_tkinter = "tkinter" in sys.modules
        self.recorder = fake_tkinter.install()
        sys.modules.pop("app", None)
        self.app_module = importlib.import_module("app")
        self.root = self.app_module.tk.Tk()
        self.window = self.app_module.ExporterApp(self.root)
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")
        # Tests below swap this out; put it back so nothing leaks between them.
        self.real_run_checks = self.app_module.preflight.run_checks

    def tearDown(self):
        self.app_module.preflight.run_checks = self.real_run_checks
        sys.modules.pop("app", None)
        if not self.had_real_tkinter:
            fake_tkinter.uninstall()

    def run_export(self):
        """Press Export and pump the event queue until the worker is done."""
        self.window.start_export()
        if self.window.worker:
            self.window.worker.join(timeout=30)
        self.window._drain_events()

    def use_fixture_database(self):
        original = self.app_module.export_to_word

        def patched(options, output_path=None, progress=None):
            options.db_path = self.db
            options.lookup_contact_name = False
            options.link_contact_handles = False
            return original(options, output_path=output_path or self.temp / "gui.docx",
                            progress=progress)

        self.app_module.export_to_word = patched


class ValidationTests(AppTestCase):
    def test_blank_number_warns_and_does_not_start_work(self):
        self.window.start_export()
        self.assertEqual(self.recorder.last()[0], "showwarning")
        self.assertIsNone(self.window.worker)

    def test_a_bad_date_is_caught_before_reading_the_database(self):
        self.window.number_var.set("555-123-4567")
        self.window.start_var.set("last week")
        self.window.start_export()
        name, args, _ = self.recorder.last()
        self.assertEqual(name, "showwarning")
        self.assertIn("Check the dates", args[0])
        self.assertIsNone(self.window.worker)


class ExportFlowTests(AppTestCase):
    def test_successful_export_reports_the_totals(self):
        self.use_fixture_database()
        self.window.number_var.set("555-123-4567")
        self.window.their_name_var.set("Alex")
        self.window.my_name_var.set("Andrew")
        self.run_export()

        status = self.window.status_var.get()
        self.assertIn("Saved 5 messages", status)
        self.assertIn("3 from Alex", status)
        self.assertIn("2 from Andrew", status)
        self.assertTrue((self.temp / "gui.docx").exists())
        self.assertIn("askyesno", self.recorder.names())
        self.assertIn("stopped", self.window.progress.states)

    def test_checkbox_options_reach_the_exporter(self):
        captured = {}
        self.app_module.export_to_word = lambda options, output_path=None, progress=None: (
            captured.update(groups=options.include_groups,
                            reactions=options.include_reactions)
            or (_ for _ in ()).throw(RuntimeError("stop here"))
        )
        self.window.number_var.set("555-123-4567")
        self.window.groups_var.set(True)
        self.window.reactions_var.set(True)
        self.run_export()
        self.assertEqual(captured, {"groups": True, "reactions": True})

    def test_missing_full_disk_access_offers_the_settings_pane(self):
        from imessage_to_word.chatdb import ChatDBPermissionError

        def refuse(options, output_path=None, progress=None):
            raise ChatDBPermissionError("needs Full Disk Access")

        self.app_module.export_to_word = refuse
        self.window.number_var.set("555-123-4567")
        self.run_export()
        name, args, _ = self.recorder.last()
        self.assertEqual(name, "askyesno")
        self.assertIn("Full Disk Access", args[0])
        self.assertIn("stopped", self.window.progress.states)

    def test_no_messages_shows_an_explanation(self):
        self.use_fixture_database()
        self.window.number_var.set("555-000-9999")
        self.run_export()
        name, args, _ = self.recorder.last()
        self.assertEqual(name, "showinfo")
        self.assertIn("No messages found", args[1])

    def test_the_plain_text_option_reaches_the_exporter(self):
        captured = {}

        def capture(options, output_path=None, progress=None):
            captured["also_text"] = options.also_text
            raise RuntimeError("stop here")

        self.app_module.export_to_word = capture
        self.window.number_var.set("555-123-4567")
        self.window.text_var.set(True)
        self.run_export()
        self.assertTrue(captured["also_text"])

    def test_the_success_message_includes_the_text_file_and_completeness(self):
        self.use_fixture_database()
        self.window.number_var.set("555-123-4567")
        self.window.their_name_var.set("Alex")
        self.window.text_var.set(True)
        self.run_export()
        status = self.window.status_var.get()
        self.assertIn(".txt", status)
        self.assertIn("messages exported", status)

    def test_unexpected_errors_are_surfaced_not_swallowed(self):
        def explode(options, output_path=None, progress=None):
            raise ValueError("boom")

        self.app_module.export_to_word = explode
        self.window.number_var.set("555-123-4567")
        self.run_export()
        name, args, _ = self.recorder.last()
        self.assertEqual(name, "showerror")
        self.assertIn("boom", args[1])


class PreviewTests(AppTestCase):
    """The preview has to show the real conversation and write nothing."""

    def run_preview(self):
        self.window.start_preview()
        if self.window.worker:
            self.window.worker.join(timeout=30)
        self.window._drain_events()
        return fake_tkinter.Toplevel.instances[-1] if fake_tkinter.Toplevel.instances else None

    def preview_text(self):
        window = self.window.preview
        return window.text.content()

    def setUp(self):
        super().setUp()
        self.use_fixture_database()
        # The preview reads the database itself, so point that at the fixture too.
        real_load = self.app_module.load_conversation

        def patched(options, progress=None):
            options.db_path = self.db
            options.lookup_contact_name = False
            options.link_contact_handles = False
            return real_load(options, progress=progress)

        self.app_module.load_conversation = patched
        self.window.number_var.set("555-123-4567")
        self.window.their_name_var.set("Alex")
        self.window.my_name_var.set("Andrew")

    def test_a_preview_window_opens_with_both_speakers(self):
        self.run_preview()
        content = self.preview_text()
        self.assertIn("Alex", content)
        self.assertIn("Andrew", content)
        self.assertIn("Hey! Are we still on for dinner at 7?", content)
        self.assertIn("Tuesday, March 3, 2026", content)

    def test_each_side_is_tagged_differently(self):
        self.run_preview()
        tags = self.window.preview.text.tags_used()
        self.assertIn("name_them", tags)
        self.assertIn("name_me", tags)
        self.assertIn("day", tags)

    def test_attachments_and_placeholders_are_shown_as_notes(self):
        self.run_preview()
        self.assertIn("Photo: IMG_0042.HEIC", self.preview_text())

    def test_previewing_writes_nothing(self):
        before = sorted(path.name for path in self.temp.iterdir())
        self.run_preview()
        self.assertEqual(sorted(path.name for path in self.temp.iterdir()), before)
        self.assertIn("Nothing has been written", self.window.status_var.get())

    def test_the_preview_is_read_only(self):
        self.run_preview()
        self.assertEqual(self.window.preview.text.options.get("state"), "disabled")

    def test_exporting_from_the_preview_writes_what_was_shown(self):
        # Export straight from the preview, through the real export path.
        self.window.chosen_path = self.temp / "gui.docx"
        self.run_preview()
        shown = self.preview_text()
        self.window.preview.export()
        if self.window.worker:
            self.window.worker.join(timeout=30)
        self.window._drain_events()
        self.assertTrue((self.temp / "gui.docx").exists())
        self.assertIn("Saved 5 messages", self.window.status_var.get())
        self.assertTrue(self.window.preview.top.destroyed)
        # What was previewed is what was written.
        import zipfile
        with zipfile.ZipFile(self.temp / "gui.docx") as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("dinner at 7", shown)
        self.assertIn("dinner at 7", body)

    def test_a_long_history_shows_the_start_and_the_end(self):
        from imessage_to_word.preview import preview_selection
        messages = list(range(1000))
        head, tail, omitted = preview_selection(messages, 40)
        self.assertEqual(len(head) + len(tail), 40)
        self.assertEqual(omitted, 960)
        self.assertEqual(head[0], 0)
        self.assertEqual(tail[-1], 999)

    def test_a_bad_number_never_reaches_the_database(self):
        self.window.number_var.set("x")
        self.window.start_preview()
        self.assertIsNone(self.window.worker)
        self.assertEqual(self.recorder.last()[0], "showwarning")


class PreviewSearchTests(PreviewTests):
    """The search box narrows what you look at, never what gets exported."""

    def search(self, term):
        self.window.preview.search_var.set(term)
        self.window.preview._on_search_typed()
        return self.window.preview

    def test_typing_reports_how_many_messages_match(self):
        self.run_preview()
        preview = self.search("dinner")
        self.assertIn("dinner", preview.search_var.get())
        status = preview.search_status_var.get()
        self.assertTrue(status, "the search box should say what it found")

    def test_a_term_that_is_not_there_says_so(self):
        self.run_preview()
        preview = self.search("zebra")
        self.assertIn("no matches", preview.search_status_var.get())

    def test_showing_only_matches_hides_everything_else(self):
        self.run_preview()
        preview = self.search("dinner")
        preview.toggle_filter()
        shown = preview.text.content()
        self.assertIn("dinner at 7", shown)
        self.assertNotIn("booked a table", shown)
        self.assertEqual(preview.filter_button.options.get("text"),
                         "Show whole conversation")

    def test_the_filtered_view_says_the_export_is_still_complete(self):
        self.run_preview()
        preview = self.search("dinner")
        preview.toggle_filter()
        self.assertIn("still exported", preview.text.content())

    def test_toggling_back_restores_the_whole_conversation(self):
        self.run_preview()
        preview = self.search("dinner")
        preview.toggle_filter()
        preview.toggle_filter()
        shown = preview.text.content()
        self.assertIn("booked a table", shown)
        self.assertIsNone(preview.filtered_term)

    def test_escape_clears_the_search(self):
        self.run_preview()
        preview = self.search("dinner")
        preview.toggle_filter()
        preview._on_escape()
        self.assertEqual(preview.search_var.get(), "")
        self.assertIn("booked a table", preview.text.content())
        self.assertFalse(preview.top.destroyed)

    def test_escape_with_no_search_closes_the_window(self):
        self.run_preview()
        self.window.preview._on_escape()
        self.assertTrue(self.window.preview.top.destroyed)

    def test_exporting_from_a_filtered_view_still_writes_everything(self):
        self.window.chosen_path = self.temp / "gui.docx"
        self.run_preview()
        preview = self.search("dinner")
        preview.toggle_filter()
        self.assertNotIn("booked a table", preview.text.content())

        preview.export()
        if self.window.worker:
            self.window.worker.join(timeout=30)
        self.window._drain_events()

        import zipfile
        with zipfile.ZipFile(self.temp / "gui.docx") as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        # The filtered-out message is in the document all the same.
        self.assertIn("booked a table", body)
        self.assertIn("Saved 5 messages", self.window.status_var.get())

    def test_the_search_only_looks_at_what_was_said(self):
        # "Alex" labels every message, but nobody typed it; searching names
        # would just match everything and tell you nothing.
        self.run_preview()
        preview = self.search("Alex")
        self.assertIn("no matches", preview.search_status_var.get())
        preview.toggle_filter()
        self.assertIsNone(preview.filtered_term)
        self.assertIn("booked a table", preview.text.content())


class AstralTests(PreviewTests):
    """Emoji cannot go into a Tk text widget that will be searched.

    Old macOS Tk refuses them outright, and current Tk segfaults when the
    widget it is searching holds one. Both windows swap them for a placeholder;
    the files that get written keep the real characters.
    """

    def test_emoji_are_replaced_for_display(self):
        from imessage_to_word.preview import ASTRAL_PLACEHOLDER
        self.assertEqual(self.window.display("hi \U0001F604"),
                         "hi " + ASTRAL_PLACEHOLDER)

    def test_ordinary_text_is_untouched(self):
        self.assertEqual(self.window.display("café ❤"), "café ❤")

    def test_the_preview_says_when_it_has_substituted(self):
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        conn.execute("UPDATE message SET text = 'party \U0001F389' WHERE ROWID = 1")
        conn.commit()
        conn.close()
        self.run_preview()
        preview = self.window.preview
        self.assertNotIn("\U0001F389", preview.text.content())
        self.assertIn("Emoji appear as", preview.note_var.get())

    def test_nothing_is_said_when_there_is_no_substitution(self):
        import sqlite3
        conn = sqlite3.connect(str(self.db))
        # The fixture's only emoji is inside an archived attributedBody blob.
        conn.execute("DELETE FROM chat_message_join WHERE message_id IN"
                     " (SELECT ROWID FROM message WHERE attributedBody IS NOT NULL)")
        conn.execute("DELETE FROM message WHERE attributedBody IS NOT NULL")
        conn.commit()
        conn.close()
        self.run_preview()
        self.assertEqual(self.window.preview.note_var.get(), "")

    def test_the_written_files_keep_the_real_emoji(self):
        self.window.chosen_path = self.temp / "gui.docx"
        self.run_preview()
        self.window.preview.export()
        if self.window.worker:
            self.window.worker.join(timeout=30)
        self.window._drain_events()
        import zipfile
        with zipfile.ZipFile(self.temp / "gui.docx") as archive:
            body = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("\U0001F697", body)   # the car emoji in the fixture


class TkProbeTests(AppTestCase):
    """A Tk built for a newer macOS aborts the process instead of raising."""

    def test_a_python_that_does_not_exist_is_not_usable(self):
        usable, complaint = self.app_module.tk_works("/nowhere/python3")
        self.assertFalse(usable)
        self.assertEqual(complaint, "")

    def test_a_python_whose_tk_aborts_is_not_usable(self):
        # Imitates the real failure: no exception, just a dead process,
        # which is why the check has to run out of process.
        script = self.temp / "aborting-python"
        script.write_text(
            "#!/bin/sh\n"
            "echo 'macOS 13 (1307) or later required, have instead 13 (1306) !' >&2\n"
            "exit 134\n")
        script.chmod(0o755)
        usable, complaint = self.app_module.tk_works(str(script))
        self.assertFalse(usable)
        self.assertIn("macOS 13", complaint)

    def test_this_python_is_tried_first(self):
        import sys
        candidates = self.app_module.python_candidates()
        self.assertEqual(candidates[0], sys.executable)

    def test_candidates_are_real_paths_without_repeats(self):
        import os
        candidates = self.app_module.python_candidates()
        self.assertEqual(len(candidates), len(set(candidates)))
        self.assertTrue(all(os.path.exists(path) for path in candidates))

    def test_a_working_tk_means_no_relaunch(self):
        from unittest import mock
        with mock.patch.object(self.app_module, "tk_works", return_value=(True, "")):
            with mock.patch.object(self.app_module.os, "execve") as execve:
                self.app_module.ensure_a_usable_tk()
        execve.assert_not_called()

    def test_no_usable_tk_hands_over_to_the_question_and_answer_version(self):
        from unittest import mock
        with mock.patch.object(self.app_module, "tk_works", return_value=(False, "boom")):
            with mock.patch.object(self.app_module, "python_candidates",
                                   return_value=["/only/one"]):
                with mock.patch("imessage_to_word.cli.main", return_value=3) as cli:
                    with self.assertRaises(SystemExit) as caught:
                        self.app_module.ensure_a_usable_tk()
        self.assertEqual(caught.exception.code, 3)
        cli.assert_called_once_with(["--interactive"])


class SetupCheckTests(AppTestCase):
    def run_check(self):
        self.window.start_check()
        if self.window.worker:
            self.window.worker.join(timeout=30)
        self.window._drain_events()

    def test_a_good_setup_is_shown_as_information(self):
        from imessage_to_word import preflight

        self.app_module.preflight.run_checks = lambda *a, **k: [
            preflight.Check("Full Disk Access", preflight.OK, "readable")
        ]
        self.run_check()
        name, args, _ = self.recorder.last()
        self.assertEqual(name, "showinfo")
        self.assertIn("Ready.", args[1])
        self.assertEqual(self.window.status_var.get(), "Setup looks good.")

    def test_a_blocked_setup_is_shown_as_a_warning(self):
        from imessage_to_word import preflight

        self.app_module.preflight.run_checks = lambda *a, **k: [
            preflight.Check("Full Disk Access", preflight.FAIL, "blocked by macOS")
        ]
        self.run_check()
        name, args, _ = self.recorder.last()
        self.assertEqual(name, "showwarning")
        self.assertIn("Not ready yet", args[1])
        self.assertIn("attention", self.window.status_var.get())

    def test_the_progress_bar_is_hidden_when_idle(self):
        self.assertIn("hidden", self.window.progress.states)
        self.run_check()
        self.assertEqual(self.window.progress.states[-1], "hidden")

    def test_the_buttons_come_back_after_a_check(self):
        self.run_check()
        self.assertIn(["!disabled"], self.window.check_button.states)
        self.assertIn("stopped", self.window.progress.states)


if __name__ == "__main__":
    unittest.main()
