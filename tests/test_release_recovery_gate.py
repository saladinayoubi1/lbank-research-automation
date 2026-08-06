import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.release_recovery_gate import compare_outputs, verify_rollback_record


class ReleaseRecoveryGateTests(unittest.TestCase):
    def output(self, payload: bytes = b"stable\n") -> Path:
        root = Path(tempfile.mkdtemp())
        (root / "artifact.bin").write_bytes(payload)
        (root / "meta").mkdir()
        (root / "meta" / "version.txt").write_text("1.0.0\n", encoding="utf-8")
        return root

    def rollback(self) -> Path:
        root = Path(tempfile.mkdtemp())
        proof = {
            "policy_version": "ADR-0014-v1",
            "current_manifest_sha256": "1" * 64,
            "previous_manifest_sha256": "2" * 64,
            "schema_test_passed": True,
            "rollback_test_passed": True,
        }
        proof_path = root / "rollback-evidence.json"
        proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
        record = {
            "schema_version": 2,
            "policy_version": "ADR-0014-v1",
            "current": {"version": "1.1.0", "manifest_sha256": "1" * 64, "source_commit": "a" * 40, "workflow_run_id": 101},
            "previous_valid": {"version": "1.0.0", "manifest_sha256": "2" * 64, "source_commit": "b" * 40, "workflow_run_id": 99},
            "authorized": False,
            "evidence_ref": "rollback-evidence.json",
            "evidence_sha256": hashlib.sha256(proof_path.read_bytes()).hexdigest(),
        }
        path = root / "rollback.json"
        path.write_text(json.dumps(record), encoding="utf-8")
        return path

    def mutate(self, path: Path, fn) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        fn(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_two_identical_outputs_pass(self):
        self.assertEqual(compare_outputs(self.output(), self.output()), ["artifact.bin", "meta/version.txt"])

    def test_changed_bytes_fail(self):
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            compare_outputs(self.output(), self.output(b"changed\n"))

    def test_missing_output_fails(self):
        second = self.output()
        (second / "meta" / "version.txt").unlink()
        with self.assertRaisesRegex(ValueError, "file set mismatch"):
            compare_outputs(self.output(), second)

    def test_symlink_fails_closed(self):
        root = self.output()
        try:
            (root / "alias").symlink_to(root / "artifact.bin")
        except OSError:
            self.skipTest("symlinks unavailable on this runner")
        with self.assertRaisesRegex(ValueError, "symlink"):
            compare_outputs(root, self.output())

    def test_valid_rollback_record_passes(self):
        self.assertEqual(verify_rollback_record(self.rollback()), ["current", "previous-valid", "source-workflow-binding", "evidence-binding", "unauthorized-by-default"])

    def test_preauthorized_rollback_fails(self):
        path = self.rollback()
        self.mutate(path, lambda data: data.__setitem__("authorized", True))
        with self.assertRaisesRegex(ValueError, "unauthorized"):
            verify_rollback_record(path)

    def test_wrong_policy_fails(self):
        path = self.rollback()
        self.mutate(path, lambda data: data.__setitem__("policy_version", "mutable"))
        with self.assertRaisesRegex(ValueError, "policy_version"):
            verify_rollback_record(path)

    def test_invalid_source_commit_fails(self):
        path = self.rollback()
        self.mutate(path, lambda data: data["current"].__setitem__("source_commit", "main"))
        with self.assertRaisesRegex(ValueError, "source_commit"):
            verify_rollback_record(path)

    def test_tampered_evidence_fails(self):
        path = self.rollback()
        (path.parent / "rollback-evidence.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify_rollback_record(path)

    def test_substituted_previous_manifest_fails(self):
        path = self.rollback()
        proof_path = path.parent / "rollback-evidence.json"
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["previous_manifest_sha256"] = "3" * 64
        proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
        self.mutate(path, lambda data: data.__setitem__("evidence_sha256", hashlib.sha256(proof_path.read_bytes()).hexdigest()))
        with self.assertRaisesRegex(ValueError, "previous manifest mismatch"):
            verify_rollback_record(path)

    def test_schema_test_assertion_fails_closed(self):
        path = self.rollback()
        proof_path = path.parent / "rollback-evidence.json"
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
        proof["schema_test_passed"] = False
        proof_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")
        self.mutate(path, lambda data: data.__setitem__("evidence_sha256", hashlib.sha256(proof_path.read_bytes()).hexdigest()))
        with self.assertRaisesRegex(ValueError, "successful schema"):
            verify_rollback_record(path)

    def test_path_traversal_fails(self):
        path = self.rollback()
        self.mutate(path, lambda data: data.__setitem__("evidence_ref", "../rollback-evidence.json"))
        with self.assertRaisesRegex(ValueError, "canonical relative path"):
            verify_rollback_record(path)


if __name__ == "__main__":
    unittest.main()
