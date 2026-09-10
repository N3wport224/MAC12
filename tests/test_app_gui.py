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
        from imessage_to_word.export import preview_selection
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
