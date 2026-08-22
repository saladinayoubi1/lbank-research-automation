import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.backup_restore_gate import verify

NOW = datetime(2026, 8, 6, 5, 0, tzinfo=timezone.utc)


class BackupRestoreGateTests(unittest.TestCase):
    def fixture(self):
        root = Path(tempfile.mkdtemp())
        restored = root / "restored"
        restored.mkdir()
        target = restored / "state.json"
        target.write_text('{"ok":true}\n', encoding="utf-8")
        proof = {
            "backup_id": "backup-20260806-001",
            "independent_storage": True,
            "encryption_verified": True,
            "retention_verified": True,
            "storage_object_version": "immutable-version-7",
            "key_owner": "external-security-owner",
            "retention_days": 30,
            "backup_created_at": "2026-08-06T00:00:00Z",
        }
        proof_path = root / "backup-record.json"
        proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
        evidence = {
            "schema_version": 2,
            "policy_version": "ADR-0015-v1",
            "source_commit": "a" * 40,
            "workflow_run_id": 123456,
            "backup_id": proof["backup_id"],
            "backup_evidence_ref": proof_path.name,
            "backup_evidence_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
            "restore_started_at": "2026-08-06T00:02:00Z",
            "restore_completed_at": "2026-08-06T00:04:00Z",
            "rpo_target_seconds": 300,
            "rto_target_seconds": 300,
            "scope": ["artifacts", "release_metadata", "configuration", "operational_state"],
            "clean_environment": True,
            "corruption_test_passed": True,
            "missing_backup_test_passed": True,
            "target_verification_passed": True,
            "production_authorized": False,
            "restored_files": [{"path": "state.json", "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "size": target.stat().st_size}],
        }
        evidence_path = root / "evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        return evidence_path, restored, evidence, proof_path

    def rewrite(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_bound_drill_evidence_passes(self):
        path, restored, _, _ = self.fixture()
        checks = verify(path, restored, now=NOW)
        self.assertIn("backup-artifact-binding", checks)
        self.assertIn("production-deny", checks)

    def test_tampered_backup_record_fails(self):
        path, restored, _, proof = self.fixture()
        proof.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify(path, restored, now=NOW)

    def test_backup_id_substitution_fails(self):
        path, restored, evidence, proof = self.fixture()
        record = json.loads(proof.read_text())
        record["backup_id"] = "other"
        proof.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        evidence["backup_evidence_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "backup_id mismatch"):
            verify(path, restored, now=NOW)

    def test_path_traversal_backup_record_fails(self):
        path, restored, evidence, _ = self.fixture()
        evidence["backup_evidence_ref"] = "../backup-record.json"
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "canonical relative"):
            verify(path, restored, now=NOW)

    def test_wrong_policy_and_source_fail(self):
        path, restored, evidence, _ = self.fixture()
        evidence["policy_version"] = "latest"
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "policy_version"):
            verify(path, restored, now=NOW)
        path, restored, evidence, _ = self.fixture()
        evidence["source_commit"] = "main"
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "source_commit"):
            verify(path, restored, now=NOW)

    def test_stale_evidence_fails(self):
        path, restored, evidence, proof = self.fixture()
        stale_backup = NOW - timedelta(days=31, minutes=4)
        stale_started = NOW - timedelta(days=31, minutes=2)
        stale_completed = NOW - timedelta(days=31)
        record = json.loads(proof.read_text())
        record["backup_created_at"] = stale_backup.isoformat().replace("+00:00", "Z")
        proof.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        evidence["backup_evidence_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
        evidence["restore_started_at"] = stale_started.isoformat().replace("+00:00", "Z")
        evidence["restore_completed_at"] = stale_completed.isoformat().replace("+00:00", "Z")
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "stale"):
            verify(path, restored, now=NOW)

    def test_restore_digest_and_scope_fail_closed(self):
        path, restored, evidence, _ = self.fixture()
        (restored / "state.json").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify(path, restored, now=NOW)
        path, restored, evidence, _ = self.fixture()
        evidence["scope"].remove("operational_state")
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "scope"):
            verify(path, restored, now=NOW)

    def test_rpo_and_preauthorization_fail(self):
        path, restored, evidence, _ = self.fixture()
        evidence["rpo_target_seconds"] = 60
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "RPO"):
            verify(path, restored, now=NOW)
        path, restored, evidence, _ = self.fixture()
        evidence["production_authorized"] = True
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "preauthorize"):
            verify(path, restored, now=NOW)

    def test_symlink_escape_fails(self):
        path, restored, evidence, _ = self.fixture()
        outside = restored.parent / "outside"
        outside.mkdir()
        target = outside / "state.json"
        target.write_text('{"ok":true}\n', encoding="utf-8")
        link = restored / "nested"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        evidence["restored_files"][0] = {"path": "nested/state.json", "sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "size": target.stat().st_size}
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "escapes root"):
            verify(path, restored, now=NOW)

    def test_hardlinked_restored_file_fails(self):
        path, restored, evidence, _ = self.fixture()
        try:
            (restored / "alias.json").hardlink_to(restored / "state.json")
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks unavailable")
        with self.assertRaisesRegex(ValueError, "missing or unsupported"):
            verify(path, restored, now=NOW)

    def test_unknown_root_field_fails_closed(self):
        path, restored, evidence, _ = self.fixture()
        evidence["production_override"] = False
        self.rewrite(path, evidence)
        with self.assertRaisesRegex(ValueError, "schema_version"):
            verify(path, restored, now=NOW)


if __name__ == "__main__":
    unittest.main()
