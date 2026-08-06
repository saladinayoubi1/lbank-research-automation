import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.disaster_recovery_gate import validate

NOW = datetime(2026, 8, 5, 22, 0, tzinfo=timezone.utc)
SCENARIOS = ("primary-region-loss", "backup-corruption", "credential-loss", "dependency-outage")


class DisasterRecoveryGateTests(unittest.TestCase):
    def write_bundle(self, mutate_record=None) -> tuple[Path, dict]:
        root = Path(tempfile.mkdtemp())
        records = root / "records"
        records.mkdir()
        scenarios = []
        for name in SCENARIOS:
            record = {"exercise_id": "dr-2026-08-05", "scenario": name, "observed": True, "recovery_verified": True}
            if mutate_record is not None:
                mutate_record(name, record)
            path = records / f"{name}.json"
            path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
            scenarios.append({
                "name": name,
                "executed": True,
                "expected_failure_observed": True,
                "recovery_verified": True,
                "evidence_ref": f"records/{name}.json",
                "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        evidence = {
            "schema_version": 2,
            "policy_version": "ADR-0013-v1",
            "source_commit": "a" * 40,
            "workflow_run_id": 123456,
            "exercise_id": "dr-2026-08-05",
            "started_at": "2026-08-05T18:00:00Z",
            "completed_at": "2026-08-05T20:00:00Z",
            "production_authorized": False,
            "objectives": {"target_rpo_minutes": 60, "target_rto_minutes": 180, "measured_rpo_minutes": 30, "measured_rto_minutes": 120},
            "clean_environment": True,
            "independent_backup_source": True,
            "target_side_verification": True,
            "rollback_tested": True,
            "restore_tested": True,
            "corruption_rejected": True,
            "missing_backup_rejected": True,
            "runbook_followed": True,
            "audit_log_preserved": True,
            "owners": {"incident_commander": "oidc:incident", "recovery_operator": "oidc:recovery", "security_approver": "oidc:security"},
            "scenarios": scenarios,
            "open_critical_findings": 0,
        }
        evidence_path = root / "dr-evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        return evidence_path, evidence

    def rewrite(self, path: Path, evidence: dict) -> None:
        path.write_text(json.dumps(evidence), encoding="utf-8")

    def test_bound_evidence_passes(self):
        path, _ = self.write_bundle()
        checks = validate(path, now=NOW)
        self.assertIn("evidence-artifact-binding", checks)
        self.assertIn("source-workflow-binding", checks)

    def test_tampered_record_is_rejected(self):
        path, evidence = self.write_bundle()
        record = path.parent / evidence["scenarios"][0]["evidence_ref"]
        record.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            validate(path, now=NOW)

    def test_wrong_exercise_record_is_rejected(self):
        path, _ = self.write_bundle(lambda name, record: record.update(exercise_id="other") if name == SCENARIOS[0] else None)
        with self.assertRaisesRegex(ValueError, "exercise mismatch"):
            validate(path, now=NOW)

    def test_wrong_scenario_record_is_rejected(self):
        path, _ = self.write_bundle(lambda name, record: record.update(scenario="other") if name == SCENARIOS[0] else None)
        with self.assertRaisesRegex(ValueError, "name mismatch"):
            validate(path, now=NOW)

    def test_missing_record_is_rejected(self):
        path, evidence = self.write_bundle()
        (path.parent / evidence["scenarios"][0]["evidence_ref"]).unlink()
        with self.assertRaisesRegex(ValueError, "missing or unsafe"):
            validate(path, now=NOW)

    def test_symlink_record_is_rejected(self):
        path, evidence = self.write_bundle()
        record = path.parent / evidence["scenarios"][0]["evidence_ref"]
        target = path.parent / "target.json"
        target.write_bytes(record.read_bytes())
        record.unlink()
        try:
            record.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        with self.assertRaisesRegex(ValueError, "missing or unsafe"):
            validate(path, now=NOW)

    def test_wrong_digest_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["scenarios"][0]["evidence_sha256"] = "0" * 64
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            validate(path, now=NOW)

    def test_missing_source_binding_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["source_commit"] = "main"
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "source_commit"):
            validate(path, now=NOW)

    def test_wrong_policy_version_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["policy_version"] = "mutable-latest"
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "policy_version"):
            validate(path, now=NOW)

    def test_production_authorization_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["production_authorized"] = True
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "production_authorized"):
            validate(path, now=NOW)

    def test_stale_evidence_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["started_at"] = "2026-06-01T00:00:00Z"
        evidence["completed_at"] = "2026-06-01T02:00:00Z"
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "stale"):
            validate(path, now=NOW)

    def test_owner_reuse_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["owners"]["security_approver"] = evidence["owners"]["recovery_operator"]
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "separation of duties"):
            validate(path, now=NOW)

    def test_path_traversal_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["scenarios"][0]["evidence_ref"] = "../escape.json"
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "safe canonical"):
            validate(path, now=NOW)

    def test_duplicate_scenario_is_rejected(self):
        path, evidence = self.write_bundle()
        evidence["scenarios"].append(copy.deepcopy(evidence["scenarios"][0]))
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(path, now=NOW)


if __name__ == "__main__":
    unittest.main()
