import unittest

from imessage_to_word.attributed_body import clean_text, decode_attributed_body
from tests.fixtures import attributed_body


class DecodeTests(unittest.TestCase):
    def test_plain_message(self):
        self.assertEqual(
            decode_attributed_body(attributed_body("Dinner at 7?")), "Dinner at 7?"
        )

    def test_unicode_survives(self):
        text = "café 🎉 — naïve"
        self.assertEqual(decode_attributed_body(attributed_body(text)), text)

    def test_long_message_uses_the_wide_length_prefix(self):
        text = "word " * 400
        self.assertEqual(decode_attributed_body(attributed_body(text)), text)

    def test_junk_and_empty_input(self):
        for value in (None, b"", b"not an archive", 12345):
            self.assertIsNone(decode_attributed_body(value))

    def test_memoryview_is_accepted(self):
        blob = memoryview(attributed_body("hello"))
        self.assertEqual(decode_attributed_body(blob), "hello")


class CleanTextTests(unittest.TestCase):
    def test_attachment_placeholder_is_removed(self):
        self.assertEqual(clean_text("￼"), "")

    def test_control_characters_are_stripped(self):
        self.assertEqual(clean_text("hi\x07 there\x00"), "hi there")

    def test_newlines_are_normalised_and_trimmed(self):
        self.assertEqual(clean_text("  a\r\nb   \r\n  "), "a\nb")

    def test_tabs_are_kept(self):
        self.assertEqual(clean_text("a\tb"), "a\tb")


if __name__ == "__main__":
    unittest.main()
