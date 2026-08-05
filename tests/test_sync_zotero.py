import json
import tempfile
import unittest
from pathlib import Path

from scripts.sync_zotero import load_items, to_zotero, validate_collection_key, validate_input_path


class ZoteroSyncTests(unittest.TestCase):
    def write(self, payload):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "items.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(directory.cleanup)
        return path

    def test_accepts_valid_csl_json(self):
        items = load_items(self.write([{"type": "article-journal", "title": "Market Microstructure", "DOI": "10.1/example"}]))
        self.assertEqual(len(items), 1)
        self.assertEqual(to_zotero(items[0], "ABC123")["collections"], ["ABC123"])

    def test_rejects_duplicate_identity(self):
        path = self.write([
            {"type": "report", "title": "A", "URL": "https://example.test/a"},
            {"type": "report", "title": "B", "URL": "https://example.test/a"},
        ])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_items(path)

    def test_rejects_unsupported_type(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            load_items(self.write([{"type": "post", "title": "Weak source"}]))

    def test_rejects_empty_input(self):
        with self.assertRaisesRegex(ValueError, "non-empty"):
            load_items(self.write([]))

    def test_accepts_reference_json_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "references" / "items.json"
            path.parent.mkdir()
            path.write_text("[]", encoding="utf-8")
            self.assertEqual(validate_input_path(path, root), path.resolve())

    def test_rejects_path_traversal_and_non_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "secrets.json"
            outside.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "under references"):
                validate_input_path(root / "references" / ".." / "secrets.json", root)
            text = root / "references" / "items.txt"
            text.parent.mkdir()
            text.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "under references"):
                validate_input_path(text, root)

    def test_collection_key_allowlist_blocks_shell_payloads(self):
        self.assertEqual(validate_collection_key("ABC123"), "ABC123")
        for value in ("abc", "ABC;id", "$(id)", "ABC DEF", "A/B"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "collection key"):
                    validate_collection_key(value)


if __name__ == "__main__":
    unittest.main()
