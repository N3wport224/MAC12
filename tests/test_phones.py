import unittest

from imessage_to_word import phones


class MatchingTests(unittest.TestCase):
    def test_formatting_is_ignored(self):
        variants = ["5551234567", "555-123-4567", "(555) 123-4567",
                    "+1 555 123 4567", "+15551234567", "1 (555) 123.4567"]
        for value in variants:
            self.assertTrue(phones.same_handle(value, "+1 (555) 123-4567"), value)

    def test_a_local_seven_digit_number_finds_the_full_one(self):
        self.assertTrue(phones.same_handle("123-4567", "+15551234567"))

    def test_too_few_digits_never_stands_in_for_a_whole_number(self):
        self.assertFalse(phones.same_handle("34567", "+15551234567"))

    def test_different_numbers_do_not_match(self):
        self.assertFalse(phones.same_handle("+447700900123", "+15551234567"))
        self.assertFalse(phones.same_handle("5551234567", "5551234568"))

    def test_emails_compare_case_insensitively(self):
        self.assertTrue(phones.same_handle("Alex@Example.com", "alex@example.com"))

    def test_an_email_never_matches_a_number(self):
        self.assertFalse(phones.same_handle("alex@example.com", "5551234567"))

    def test_short_codes_compare_exactly(self):
        self.assertTrue(phones.same_handle("262966", "262966"))
        self.assertFalse(phones.same_handle("262966", "12345"))

    def test_blank_input_never_matches(self):
        self.assertFalse(phones.same_handle("", ""))
        self.assertFalse(phones.same_handle("", "5551234567"))

    def test_matches_any_accepts_one_or_many(self):
        self.assertTrue(phones.matches_any("+15551234567", "555-123-4567"))
        self.assertTrue(phones.matches_any("a@b.com", ["555-123-4567", "A@B.com"]))
        self.assertFalse(phones.matches_any("+15551234567", []))
        self.assertFalse(phones.matches_any("+15551234567", ["", None]))

    def test_group_chat_identifiers_are_not_treated_as_numbers(self):
        self.assertTrue(phones.is_group_identifier("chat618033988749895"))
        self.assertFalse(phones.is_group_identifier("+15551234567"))
        self.assertFalse(phones.is_group_identifier("chat@example.com"))


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
