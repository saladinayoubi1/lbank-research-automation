import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.release_gate import verify


class ReleaseGateTests(unittest.TestCase):
    def bundle(self) -> Path:
        root = Path(tempfile.mkdtemp())
        artifact = root / "dataset.bin"
        artifact.write_bytes(b"deterministic-release-payload\n")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        (root / "artifact-manifest.json").write_text(json.dumps({"artifacts": [{"path": "dataset.bin", "sha256": digest, "size": artifact.stat().st_size}]}), encoding="utf-8")
        (root / "sbom.cdx.json").write_text(json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}), encoding="utf-8")
        (root / "provenance.json").write_text(json.dumps({"source_commit": "0" * 40, "builder": "github-actions", "subjects": [{"path": "dataset.bin", "sha256": digest}]}), encoding="utf-8")
        return root

    def test_unsigned_ci_bundle_passes_internal_consistency(self):
        self.assertEqual(verify(self.bundle(), require_signature=False), ["manifest", "sbom", "provenance", "artifact-digests"])

    def test_production_fails_closed_without_signature_policy(self):
        with self.assertRaisesRegex(ValueError, "signature"):
            verify(self.bundle(), require_signature=True)

    def test_tampered_artifact_fails_closed(self):
        root = self.bundle()
        (root / "dataset.bin").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            verify(root, require_signature=False)

    def test_missing_sbom_fails_closed(self):
        root = self.bundle()
        (root / "sbom.cdx.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing required file"):
            verify(root, require_signature=False)

    def test_path_traversal_fails_closed(self):
        root = self.bundle()
        manifest = json.loads((root / "artifact-manifest.json").read_text())
        manifest["artifacts"][0]["path"] = "../dataset.bin"
        (root / "artifact-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "safe relative path"):
            verify(root, require_signature=False)


if __name__ == "__main__":
    unittest.main()
