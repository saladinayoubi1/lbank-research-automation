import json
import tempfile
import unittest
from pathlib import Path

from scripts.sync_zotero import load_items, to_zotero


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
        self.assertEqual(to_zotero(items[0], "ABC")["collections"], ["ABC"])

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


if __name__ == "__main__":
    unittest.main()
