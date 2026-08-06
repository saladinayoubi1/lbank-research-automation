from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_research_evidence_matrix.py"
MATRIX_PATH = ROOT / "research" / "evidence" / "execution_nonstationarity_model_validation_matrix.json"

spec = importlib.util.spec_from_file_location("research_validator", VALIDATOR_PATH)
validator = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(validator)


class ResearchEvidenceValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        cls.today = date(2026, 8, 6)

    def validate(self, document):
        return validator.validate_document(document, today=self.today)

    def test_valid_second_batch(self):
        self.assertEqual([], self.validate(copy.deepcopy(self.document)))

    def test_duplicate_id_fails_closed(self):
        document = copy.deepcopy(self.document)
        document["evidence"][1]["id"] = document["evidence"][0]["id"]
        self.assertTrue(any("duplicate evidence id" in e for e in self.validate(document)))

    def test_malformed_url_fails_closed(self):
        document = copy.deepcopy(self.document)
        document["evidence"][0]["url_or_doi"] = "https:// bad host"
        self.assertTrue(any("valid HTTPS URL" in e for e in self.validate(document)))

    def test_missing_source_coverage_fails_closed(self):
        document = copy.deepcopy(self.document)
        document["evidence"] = [r for r in document["evidence"] if not (r["domain"] == "execution_costs" and r["source_type"] == "limitation")]
        self.assertTrue(any("execution_costs lacks required source_type 'limitation'" in e for e in self.validate(document)))

    def test_stale_review_field_fails_closed(self):
        document = copy.deepcopy(self.document)
        document["evidence"][0]["review_date"] = "2024-01-01"
        self.assertTrue(any("review_date is invalid or stale" in e for e in self.validate(document)))

    def test_invalid_status_and_confidence_fail_closed(self):
        document = copy.deepcopy(self.document)
        document["status"] = "production-ready"
        document["evidence"][0]["confidence"] = "certain"
        errors = self.validate(document)
        self.assertTrue(any("status must be 'research-only'" in e for e in errors))
        self.assertTrue(any("confidence unsupported" in e for e in errors))

    def test_invalid_verification_status_fails_closed(self):
        document = copy.deepcopy(self.document)
        document["evidence"][0]["verification_status"] = "trusted"
        self.assertTrue(any("verification_status unsupported" in e for e in self.validate(document)))

    def test_claim_traceability_mismatch_fails_closed(self):
        document = copy.deepcopy(self.document)
        document["claims"][0]["source_ids"].append("UNKNOWN-SOURCE")
        self.assertTrue(any("references unknown source_id" in e for e in self.validate(document)))

    def test_missing_claim_context_fails_closed(self):
        for field in ("applicability", "limitations", "obsolescence_triggers"):
            with self.subTest(field=field):
                document = copy.deepcopy(self.document)
                document["evidence"][0][field] = [] if field == "obsolescence_triggers" else ""
                self.assertTrue(self.validate(document))


if __name__ == "__main__":
    unittest.main()
