import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.disaster_recovery_gate import validate


NOW = datetime(2026, 8, 5, 22, 0, tzinfo=timezone.utc)


class DisasterRecoveryGateTests(unittest.TestCase):
    def evidence(self) -> dict:
        scenarios = []
        for name in (
            "primary-region-loss",
            "backup-corruption",
            "credential-loss",
            "dependency-outage",
        ):
            scenarios.append(
                {
                    "name": name,
                    "executed": True,
                    "expected_failure_observed": True,
                    "recovery_verified": True,
                    "evidence_ref": f"records/{name}.json",
                }
            )
        return {
            "schema_version": 1,
            "exercise_id": "dr-2026-08-05",
            "started_at": "2026-08-05T18:00:00Z",
            "completed_at": "2026-08-05T20:00:00Z",
            "max_evidence_age_days": 30,
            "production_authorized": False,
            "objectives": {
                "target_rpo_minutes": 60,
                "target_rto_minutes": 180,
                "measured_rpo_minutes": 30,
                "measured_rto_minutes": 120,
            },
            "clean_environment": True,
            "independent_backup_source": True,
            "target_side_verification": True,
            "rollback_tested": True,
            "restore_tested": True,
            "corruption_rejected": True,
            "missing_backup_rejected": True,
            "runbook_followed": True,
            "audit_log_preserved": True,
            "owners": {
                "incident_commander": "role:incident-commander",
                "recovery_operator": "role:recovery-operator",
                "security_approver": "role:security-approver",
            },
            "scenarios": scenarios,
            "open_critical_findings": 0,
        }

    def write(self, evidence: dict) -> Path:
        path = Path(tempfile.mkdtemp()) / "dr-evidence.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        return path

    def test_complete_evidence_passes(self):
        checks = validate(self.write(self.evidence()), now=NOW)
        self.assertIn("scenario-coverage", checks)
        self.assertIn("production-deny", checks)

    def test_production_authorization_is_rejected(self):
        evidence = self.evidence()
        evidence["production_authorized"] = True
        with self.assertRaisesRegex(ValueError, "production_authorized"):
            validate(self.write(evidence), now=NOW)

    def test_stale_evidence_fails_closed(self):
        evidence = self.evidence()
        evidence["completed_at"] = "2026-01-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "stale"):
            validate(self.write(evidence), now=NOW)

    def test_rto_regression_fails_closed(self):
        evidence = self.evidence()
        evidence["objectives"]["measured_rto_minutes"] = 181
        with self.assertRaisesRegex(ValueError, "RTO"):
            validate(self.write(evidence), now=NOW)

    def test_missing_scenario_fails_closed(self):
        evidence = self.evidence()
        evidence["scenarios"] = evidence["scenarios"][:-1]
        with self.assertRaisesRegex(ValueError, "missing required"):
            validate(self.write(evidence), now=NOW)

    def test_duplicate_scenario_fails_closed(self):
        evidence = self.evidence()
        evidence["scenarios"].append(copy.deepcopy(evidence["scenarios"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(self.write(evidence), now=NOW)

    def test_failed_negative_drill_is_rejected(self):
        evidence = self.evidence()
        evidence["corruption_rejected"] = False
        with self.assertRaisesRegex(ValueError, "corruption_rejected"):
            validate(self.write(evidence), now=NOW)

    def test_owner_role_reuse_breaks_separation_of_duties(self):
        evidence = self.evidence()
        evidence["owners"]["security_approver"] = evidence["owners"]["recovery_operator"]
        with self.assertRaisesRegex(ValueError, "separation of duties"):
            validate(self.write(evidence), now=NOW)

    def test_future_completion_is_rejected(self):
        evidence = self.evidence()
        evidence["completed_at"] = "2026-08-06T20:00:00Z"
        with self.assertRaisesRegex(ValueError, "future"):
            validate(self.write(evidence), now=NOW)


if __name__ == "__main__":
    unittest.main()
