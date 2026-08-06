import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from tools.zotero_metadata_audit import audit, load_items, main, normalize_doi


class ZoteroMetadataAuditTests(unittest.TestCase):
    def test_valid_input_reports_creator_quality_and_stable_shape(self):
        report = audit(
            [
                {
                    "itemType": "journalArticle",
                    "title": "Example Study",
                    "date": "2024-05-01",
                    "DOI": "10.1000/example",
                    "creators": [{"firstName": "Ada", "lastName": "Lovelace"}],
                }
            ]
        )
        self.assertEqual(report["schema_version"], "2.0")
        self.assertEqual(report["mode"], "read-only-offline")
        self.assertEqual(report["finding_count"], 0)
        self.assertEqual(report["items"], [])
        self.assertEqual(report["duplicates"], {"doi": [], "title_year": []})

    def test_malformed_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text("{not-json", encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = main([str(path), "--json"])
        self.assertEqual(result, 2)
        self.assertIn("audit failed", stderr.getvalue())

    def test_missing_fields_and_creator_quality(self):
        report = audit([{"itemType": "conferencePaper", "creators": []}])
        self.assertEqual(report["finding_count"], 4)
        self.assertEqual(
            report["items"][0],
            {
                "creator_findings": ["missing_creators"],
                "index": 0,
                "missing_fields": ["title", "year", "DOI"],
                "title": "",
            },
        )

    def test_duplicate_doi_and_title_year_are_conservative(self):
        report = audit(
            [
                {
                    "itemType": "journalArticle",
                    "title": "  Example   Study ",
                    "date": "2024-05-01",
                    "DOI": "https://doi.org/10.1000/ABC",
                    "creators": [{"name": "Research Group"}],
                },
                {
                    "itemType": "journalArticle",
                    "title": "example study",
                    "date": "2024",
                    "DOI": "doi: 10.1000/abc",
                    "creators": [{"name": "Research Group"}],
                },
            ]
        )
        self.assertEqual(report["duplicates"]["doi"][0]["indexes"], [0, 1])
        self.assertEqual(report["duplicates"]["title_year"][0]["indexes"], [0, 1])
        self.assertEqual(normalize_doi("https://doi.org/10.1000/ABC"), "10.1000/abc")

    def test_no_findings_cli_returns_zero_and_deterministic_json(self):
        payload = [
            {
                "itemType": "journalArticle",
                "title": "Complete Item",
                "date": "2025",
                "DOI": "10.1000/complete",
                "creators": [{"firstName": "Grace", "lastName": "Hopper"}],
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            first = StringIO()
            second = StringIO()
            with redirect_stdout(first):
                first_result = main([str(path), "--json"])
            with redirect_stdout(second):
                second_result = main([str(path), "--json"])
        self.assertEqual(first_result, 0)
        self.assertEqual(second_result, 0)
        self.assertEqual(first.getvalue(), second.getvalue())

    def test_load_items_rejects_non_object_items(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "items.json"
            path.write_text('[{"title": "ok"}, 3]', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be a JSON object"):
                load_items(path)


if __name__ == "__main__":
    unittest.main()
