import unittest

from imessage_to_word import phones


class MatchKeyTests(unittest.TestCase):
    def test_formatting_is_ignored(self):
        variants = ["5551234567", "555-123-4567", "(555) 123-4567",
                    "+1 555 123 4567", "+15551234567", "1 (555) 123.4567"]
        keys = {phones.match_key(value) for value in variants}
        self.assertEqual(keys, {"5551234567"})

    def test_international_numbers_keep_their_identity(self):
        self.assertNotEqual(
            phones.match_key("+447700900123"), phones.match_key("+15551234567")
        )

    def test_emails_compare_case_insensitively(self):
        self.assertTrue(phones.same_handle("Alex@Example.com", "alex@example.com"))

    def test_short_codes_keep_every_digit(self):
        self.assertEqual(phones.match_key("262966"), "262966")
        self.assertFalse(phones.same_handle("262966", "12345"))

    def test_blank_input_never_matches(self):
        self.assertEqual(phones.match_key(""), "")
        self.assertFalse(phones.same_handle("", ""))

    def test_match_keys_accepts_one_or_many(self):
        self.assertEqual(phones.match_keys("555-123-4567"), {"5551234567"})
        self.assertEqual(
            phones.match_keys(["555-123-4567", "a@b.com", ""]),
            {"5551234567", "a@b.com"},
        )


class DisplayTests(unittest.TestCase):
    def test_pretty_formatting(self):
        self.assertEqual(phones.format_pretty("5551234567"), "(555) 123-4567")
        self.assertEqual(phones.format_pretty("+15551234567"), "+1 (555) 123-4567")
        self.assertEqual(phones.format_pretty("alex@example.com"), "alex@example.com")

    def test_safe_filename_strips_path_characters(self):
        self.assertEqual(phones.safe_filename("Alex / Kim: notes"), "Alex Kim notes")
        self.assertEqual(phones.safe_filename("///"), "conversation")

    def test_validation_messages(self):
        self.assertIsNotNone(phones.looks_like_handle(""))
        self.assertIsNotNone(phones.looks_like_handle("ab"))
        self.assertIsNone(phones.looks_like_handle("555-123-4567"))
        self.assertIsNone(phones.looks_like_handle("alex@example.com"))


if __name__ == "__main__":
    unittest.main()
