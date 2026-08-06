import unittest

from tools.zotero_metadata_audit import audit, normalize_doi


class ZoteroMetadataAuditTests(unittest.TestCase):
    def test_normalizes_doi_urls_and_prefixes(self):
        self.assertEqual(normalize_doi("https://doi.org/10.1000/ABC"), "10.1000/abc")
        self.assertEqual(normalize_doi("doi: 10.1000/ABC"), "10.1000/abc")

    def test_reports_missing_metadata_and_duplicates(self):
        report = audit(
            [
                {
                    "itemType": "journalArticle",
                    "title": "  Example   Study ",
                    "date": "2024-05-01",
                    "DOI": "https://doi.org/10.1000/ABC",
                },
                {
                    "itemType": "journalArticle",
                    "title": "example study",
                    "date": "2024",
                    "DOI": "doi: 10.1000/abc",
                },
                {"itemType": "conferencePaper", "title": "", "date": "unknown"},
            ]
        )

        self.assertTrue(report["read_only"])
        self.assertEqual(report["item_count"], 3)
        self.assertEqual(report["duplicate_doi_candidates"][0]["indexes"], [0, 1])
        self.assertEqual(
            report["duplicate_title_year_candidates"][0]["indexes"], [0, 1]
        )
        self.assertEqual(
            report["missing_metadata"][0]["missing"], ["title", "year", "DOI"]
        )


if __name__ == "__main__":
    unittest.main()
