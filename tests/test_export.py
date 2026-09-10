import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from imessage_to_word import chatdb
from imessage_to_word.export import (
    ExportError,
    ExportOptions,
    NoMessagesFound,
    default_output_path,
    export_to_word,
    format_size,
    parse_date_input,
)
from tests.fixtures import build_sample_db

ALEX = "555-123-4567"


def document_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        return archive.read("word/document.xml").decode("utf-8")


class ExportTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = Path(tempfile.mkdtemp())
        self.db = build_sample_db(self.temp / "chat.db")

    def export(self, number=ALEX, name="Alex", filename="out.docx", **kwargs):
        options = ExportOptions(
            number=number,
            their_name=name,
            db_path=self.db,
            lookup_contact_name=False,
            link_contact_handles=False,
            **kwargs
        )
        return export_to_word(options, output_path=self.temp / filename)


class DirectConversationTests(ExportTestCase):
    def test_direct_messages_are_exported(self):
        result = self.export()
        self.assertTrue(result.path.exists())
        self.assertEqual(result.message_count, 5)
        self.assertEqual((result.from_them, result.from_me), (3, 2))

    def test_both_speakers_are_labelled(self):
        result = self.export(name="Alex", my_name="Andrew")
        body = document_text(result.path)
        self.assertIn("Alex", body)
        self.assertIn("Andrew", body)
        self.assertIn("Who said what", body)

    def test_each_side_gets_its_own_colour_and_indent(self):
        body = document_text(self.export().path)
        self.assertIn('w:fill="E9F1FE"', body)   # my side
        self.assertIn('w:fill="EDF6F0"', body)   # their side
        self.assertIn('<w:ind w:left="2448" w:right="0"/>', body)

    def test_messages_are_in_time_order_under_a_day_heading(self):
        body = document_text(self.export().path)
        self.assertIn("Tuesday, March 3, 2026", body)
        first = body.index("Are we still on for dinner")
        second = body.index("booked a table for two")
        self.assertLess(first, second)

    def test_attributed_body_messages_are_included(self):
        # This message has no `text` column value, only an archived blob.
        self.assertIn("I'll drive", document_text(self.export().path))

    def test_attachments_are_described(self):
        body = document_text(self.export().path)
        self.assertIn("Photo: IMG_0042.HEIC", body)
        self.assertIn("2.3 MB", body)

    def test_edited_messages_are_flagged(self):
        self.assertIn("(edited)", document_text(self.export().path))

    def test_special_characters_are_escaped_not_dropped(self):
        self.assertIn("&lt;3 &amp; thanks!", document_text(self.export().path))

    def test_any_number_format_finds_the_same_conversation(self):
        counts = {
            self.export(number=number, filename="{}.docx".format(index)).message_count
            for index, number in enumerate(
                ["5551234567", "(555) 123-4567", "+1 555 123 4567", "+15551234567"]
            )
        }
        self.assertEqual(counts, {5})


class FilteringTests(ExportTestCase):
    def test_group_chats_are_excluded_by_default(self):
        self.assertNotIn("hiking Saturday", document_text(self.export().path))

    def test_group_chats_can_be_included(self):
        body = document_text(self.export(include_groups=True).path)
        self.assertIn("hiking Saturday", body)
        self.assertIn("Weekend Trip", body)

    def test_a_one_to_one_thread_has_no_redundant_chat_name_row(self):
        body = document_text(self.export().path)
        self.assertNotIn("&gt;Conversation&lt;", body)
        self.assertEqual(body.count("+15551234567"), 1)

    def test_other_participants_in_a_group_keep_their_own_name(self):
        body = document_text(self.export(include_groups=True).path)
        # Jordan is neither me nor the person being exported.
        self.assertIn("(555) 987-6543", body)

    def test_other_peoples_conversations_are_never_included(self):
        self.assertNotIn("Wrong number", document_text(self.export(include_groups=True).path))

    def test_tapbacks_are_excluded_by_default(self):
        self.assertNotIn("Loved", document_text(self.export().path))

    def test_tapbacks_can_be_included(self):
        result = self.export(include_reactions=True)
        self.assertEqual(result.message_count, 6)
        self.assertIn("Loved", document_text(result.path))

    def test_linked_handles_merge_a_split_thread(self):
        result = self.export(extra_handles=["alex@example.com"])
        self.assertEqual(result.message_count, 7)
        self.assertIn("Great night", document_text(result.path))
        self.assertIn("Wednesday, March 4, 2026", document_text(result.path))

    def test_date_range_limits_the_export(self):
        start = datetime(2026, 3, 3, 9, 45, tzinfo=timezone.utc)
        result = self.export(start=start, filename="range.docx")
        self.assertEqual(result.message_count, 3)
        self.assertNotIn("dinner at 7", document_text(result.path))

    def test_end_date_limits_the_export(self):
        end = datetime(2026, 3, 3, 9, 44, tzinfo=timezone.utc)
        result = self.export(end=end, filename="range2.docx")
        self.assertEqual(result.message_count, 2)


class ErrorTests(ExportTestCase):
    def test_unknown_number_explains_what_to_try(self):
        with self.assertRaises(NoMessagesFound) as caught:
            self.export(number="555-000-9999", filename="none.docx")
        self.assertIn("Include group chats", str(caught.exception))

    def test_blank_number_is_rejected(self):
        with self.assertRaises(ExportError):
            self.export(number="   ", filename="blank.docx")

    def test_missing_database_is_reported_clearly(self):
        options = ExportOptions(number=ALEX, db_path=self.temp / "nope.db",
                                lookup_contact_name=False, link_contact_handles=False)
        with self.assertRaises(chatdb.ChatDBNotFound):
            export_to_word(options, output_path=self.temp / "x.docx")


class DatabaseTests(ExportTestCase):
    def test_the_live_database_is_never_modified(self):
        before = self.db.read_bytes()
        self.export()
        self.assertEqual(self.db.read_bytes(), before)

    def test_immutable_mode_also_works(self):
        options = ExportOptions(number=ALEX, their_name="Alex", db_path=self.db,
                                copy_database=False, lookup_contact_name=False,
                                link_contact_handles=False)
        result = export_to_word(options, output_path=self.temp / "ro.docx")
        self.assertEqual(result.message_count, 5)

    def test_listing_conversations(self):
        with chatdb.open_chat_db(self.db) as conn:
            rows = chatdb.list_conversations(conn)
        handles = {row["handle"] for row in rows}
        self.assertIn("+15551234567", handles)
        self.assertTrue(all(row["message_count"] > 0 for row in rows))


class HelperTests(unittest.TestCase):
    def test_default_output_path_is_a_docx_in_documents(self):
        path = default_output_path("Alex Kim")
        self.assertEqual(path.suffix, ".docx")
        self.assertIn("iMessage Exports", str(path))
        self.assertIn("Alex Kim", path.name)

    def test_size_formatting(self):
        self.assertEqual(format_size(0), "")
        self.assertEqual(format_size(900), "900 bytes")
        self.assertEqual(format_size(184320), "180 KB")
        self.assertEqual(format_size(2411724), "2.3 MB")

    def test_date_parsing_accepts_common_formats(self):
        for value in ("2026-03-01", "3/1/2026", "March 1, 2026"):
            self.assertEqual(parse_date_input(value).date().isoformat(), "2026-03-01")
        self.assertIsNone(parse_date_input(""))
        with self.assertRaises(ExportError):
            parse_date_input("last tuesday")


if __name__ == "__main__":
    unittest.main()
