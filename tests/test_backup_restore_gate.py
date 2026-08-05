import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.backup_restore_gate import verify


class BackupRestoreGateTests(unittest.TestCase):
    def fixture(self):
        root = Path(tempfile.mkdtemp())
        restored = root / "restored"
        restored.mkdir()
        target = restored / "state.json"
        target.write_text('{"ok":true}\n', encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        evidence = {
            "backup_id": "backup-20260806-001",
            "independent_storage": True,
            "encryption_verified": True,
            "key_owner": "external-security-owner",
            "retention_days": 30,
            "backup_created_at": "2026-08-06T00:00:00Z",
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
            "restored_files": [{"path": "state.json", "sha256": digest, "size": target.stat().st_size}],
        }
        evidence_path = root / "evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        return evidence_path, restored, evidence

    def rewrite(self, path, evidence):
        path.write_text(json.dumps(evidence), encoding="utf-8")

    def test_complete_offline_drill_evidence_passes(self):
        evidence_path, restored, _ = self.fixture()
        self.assertIn("restore-integrity", verify(evidence_path, restored))

    def test_digest_mismatch_fails_closed(self):
        evidence_path, restored, _ = self.fixture()
        (restored / "state.json").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify(evidence_path, restored)

    def test_non_hex_digest_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["restored_files"][0]["sha256"] = "g" * 64
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "invalid restored digest"):
            verify(evidence_path, restored)

    def test_missing_scope_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["scope"].remove("operational_state")
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "scope"):
            verify(evidence_path, restored)

    def test_duplicate_scope_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["scope"].append("artifacts")
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "scope"):
            verify(evidence_path, restored)

    def test_rto_breach_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["rto_target_seconds"] = 60
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "RTO"):
            verify(evidence_path, restored)

    def test_rpo_breach_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["rpo_target_seconds"] = 60
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "RPO"):
            verify(evidence_path, restored)

    def test_boolean_numeric_target_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["rto_target_seconds"] = True
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "RTO"):
            verify(evidence_path, restored)

    def test_missing_negative_drill_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["corruption_test_passed"] = False
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "corruption"):
            verify(evidence_path, restored)

    def test_repository_preauthorization_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["production_authorized"] = True
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "preauthorize"):
            verify(evidence_path, restored)

    def test_path_traversal_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        evidence["restored_files"][0]["path"] = "../state.json"
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "safe relative"):
            verify(evidence_path, restored)

    def test_symlinked_root_fails_closed(self):
        evidence_path, restored, _ = self.fixture()
        link = restored.parent / "restored-link"
        try:
            link.symlink_to(restored, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(ValueError, "real directory"):
            verify(evidence_path, link)

    def test_parent_symlink_escape_fails_closed(self):
        evidence_path, restored, evidence = self.fixture()
        outside = restored.parent / "outside"
        outside.mkdir()
        (outside / "state.json").write_text('{"ok":true}\n', encoding="utf-8")
        link = restored / "nested"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        target = outside / "state.json"
        evidence["restored_files"][0] = {
            "path": "nested/state.json",
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "size": target.stat().st_size,
        }
        self.rewrite(evidence_path, evidence)
        with self.assertRaisesRegex(ValueError, "escapes root"):
            verify(evidence_path, restored)


if __name__ == "__main__":
    unittest.main()
