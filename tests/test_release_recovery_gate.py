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
        path = root / "rollback.json"
        path.write_text(json.dumps({
            "current": {"version": "1.1.0", "manifest_sha256": "1" * 64},
            "previous_valid": {"version": "1.0.0", "manifest_sha256": "2" * 64},
            "authorized": False,
            "schema_compatible": True,
        }), encoding="utf-8")
        return path

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
        self.assertEqual(verify_rollback_record(self.rollback()), [
            "current", "previous-valid", "unauthorized-by-default", "schema-compatible"
        ])

    def test_preauthorized_rollback_fails(self):
        path = self.rollback()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["authorized"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unauthorized"):
            verify_rollback_record(path)

    def test_same_version_fails(self):
        path = self.rollback()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["previous_valid"]["version"] = data["current"]["version"]
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must differ"):
            verify_rollback_record(path)

    def test_schema_incompatibility_fails(self):
        path = self.rollback()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["schema_compatible"] = False
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "schema compatibility"):
            verify_rollback_record(path)


if __name__ == "__main__":
    unittest.main()
