import unittest

from scripts.validate_bibtex import validate


class ValidateBibtexTests(unittest.TestCase):
    def test_accepts_empty_export_target(self):
        self.assertEqual(validate("% empty Zotero export target\n"), [])

    def test_accepts_valid_entry(self):
        text = """@misc{nist-ssdf,
  title = {Secure Software Development Framework},
  author = {{National Institute of Standards and Technology}},
  year = {2022},
  url = {https://example.invalid}
}
"""
        self.assertEqual(validate(text), [])

    def test_rejects_duplicate_keys(self):
        text = "@misc{same, title={A}}\n@article{same, title={B}}\n"
        self.assertIn("duplicate citation key", validate(text))

    def test_rejects_unbalanced_braces(self):
        self.assertIn("unbalanced braces", validate("@misc{x, title={A}\n"))

    def test_rejects_entry_without_identifying_metadata(self):
        self.assertIn("entry x has no identifying metadata", validate("@misc{x, note={only note}}\n"))


if __name__ == "__main__":
    unittest.main()
