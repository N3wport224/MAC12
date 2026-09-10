"""The logic behind the preview: what to show, what matches, what Tk can draw."""
import unittest

from imessage_to_word.models import Attachment, Message
from imessage_to_word.preview import (
    ASTRAL_PLACEHOLDER,
    find_messages,
    gap_note,
    has_astral,
    matches,
    preview_selection,
    searchable_text,
    strip_astral,
)


def message(text="", attachments=(), rowid=1):
    return Message(rowid=rowid, date=None, is_from_me=False, sender_handle=None,
                   text=text, attachments=list(attachments))


class MatchingTests(unittest.TestCase):
    def test_plain_substring(self):
        self.assertTrue(matches(message("dinner at seven"), "dinner"))
        self.assertFalse(matches(message("dinner at seven"), "lunch"))

    def test_case_is_ignored(self):
        self.assertTrue(matches(message("Dinner At Seven"), "dinner at"))
        self.assertTrue(matches(message("dinner"), "DINNER"))

    def test_attachment_names_are_searchable(self):
        with_file = message("", [Attachment("quote-revised.pdf", "application/pdf")])
        self.assertTrue(matches(with_file, "quote"))
        self.assertTrue(matches(with_file, "pdf"))
        self.assertIn("quote-revised.pdf", searchable_text(with_file))

    def test_an_empty_term_matches_nothing(self):
        self.assertFalse(matches(message("anything"), ""))
        self.assertFalse(matches(message("anything"), "   "))

    def test_finding_across_a_conversation(self):
        conversation = [message("about the quote", rowid=1),
                        message("no", rowid=2),
                        message("quote again", rowid=3)]
        found, total = find_messages(conversation, "quote")
        self.assertEqual(total, 2)
        self.assertEqual([m.rowid for m in found], [1, 3])

    def test_a_limit_caps_what_is_returned_not_what_is_counted(self):
        conversation = [message("quote", rowid=i) for i in range(10)]
        found, total = find_messages(conversation, "quote", limit=3)
        self.assertEqual(len(found), 3)
        self.assertEqual(total, 10)

    def test_no_term_finds_nothing(self):
        self.assertEqual(find_messages([message("x")], ""), ([], 0))


class SelectionTests(unittest.TestCase):
    def test_a_short_conversation_is_shown_whole(self):
        head, tail, omitted = preview_selection(list(range(10)), 40)
        self.assertEqual(head, list(range(10)))
        self.assertEqual((tail, omitted), ([], 0))

    def test_a_long_conversation_keeps_both_ends(self):
        head, tail, omitted = preview_selection(list(range(1000)), 40)
        self.assertEqual(len(head) + len(tail), 40)
        self.assertEqual(head[0], 0)
        self.assertEqual(tail[-1], 999)
        self.assertEqual(omitted, 960)

    def test_no_limit_means_everything(self):
        for limit in (None, 0):
            head, tail, omitted = preview_selection(list(range(500)), limit)
            self.assertEqual(len(head), 500)
            self.assertEqual(omitted, 0)

    def test_the_gap_note_says_the_export_is_complete(self):
        note = gap_note(1234)
        self.assertIn("1,234", note)
        self.assertIn("in the export", note)


class AstralTests(unittest.TestCase):
    """Older macOS Tk refuses characters above U+FFFF."""

    def test_detection(self):
        self.assertTrue(has_astral("nice \U0001F604"))
        self.assertFalse(has_astral("plain text"))
        self.assertFalse(has_astral("accents café and ❤ are fine"))

    def test_each_character_is_replaced_one_for_one(self):
        # Positions must not shift, or highlights would land in the wrong place.
        original = "a \U0001F604 b \U0001F697 c"
        replaced = strip_astral(original)
        self.assertEqual(len(replaced), len(original))
        self.assertNotIn("\U0001F604", replaced)
        self.assertEqual(replaced.count(ASTRAL_PLACEHOLDER), 2)

    def test_ordinary_text_is_untouched(self):
        for value in ("hello", "café ❤", ""):
            self.assertEqual(strip_astral(value), value)


if __name__ == "__main__":
    unittest.main()
