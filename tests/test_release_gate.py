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
        sbom = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "metadata": {"properties": [{"name": "nexus:graph-completeness", "value": "complete"}]},
            "components": [
                {"type": "library", "name": "root", "version": "1", "bom-ref": "pkg:generic/root@1", "purl": "pkg:generic/root@1"},
                {"type": "library", "name": "dep", "version": "1", "bom-ref": "pkg:generic/dep@1", "purl": "pkg:generic/dep@1"},
            ],
            "dependencies": [
                {"ref": "pkg:generic/root@1", "dependsOn": ["pkg:generic/dep@1"]},
                {"ref": "pkg:generic/dep@1", "dependsOn": []},
            ],
        }
        (root / "sbom.cdx.json").write_text(json.dumps(sbom), encoding="utf-8")
        (root / "provenance.json").write_text(json.dumps({"source_commit": "0" * 40, "builder": "github-actions", "subjects": [{"path": "dataset.bin", "sha256": digest}]}), encoding="utf-8")
        return root

    def mutate_sbom(self, root: Path, fn) -> None:
        path = root / "sbom.cdx.json"
        sbom = json.loads(path.read_text())
        fn(sbom)
        path.write_text(json.dumps(sbom), encoding="utf-8")

    def test_unsigned_ci_bundle_passes_internal_consistency(self):
        self.assertEqual(verify(self.bundle(), require_signature=False), ["manifest", "sbom-complete", "provenance", "artifact-digests"])

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

    def test_unknown_completeness_is_explicit(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["metadata"].pop("properties"))
        self.assertIn("sbom-unknown", verify(root, require_signature=False))

    def test_complete_graph_requires_dependency_entry_per_component(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["dependencies"].pop())
        with self.assertRaisesRegex(ValueError, "one dependency entry per component"):
            verify(root, require_signature=False)

    def test_cycle_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["dependencies"][1]["dependsOn"].append("pkg:generic/root@1"))
        with self.assertRaisesRegex(ValueError, "cycle"):
            verify(root, require_signature=False)

    def test_unknown_dependency_target_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["dependencies"][0]["dependsOn"].append("pkg:generic/missing@1"))
        with self.assertRaisesRegex(ValueError, "unknown dependency target"):
            verify(root, require_signature=False)

    def test_malformed_purl_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["components"][0].update({"purl": "pkg:bad value"}))
        with self.assertRaisesRegex(ValueError, "malformed component purl"):
            verify(root, require_signature=False)

    def test_empty_inventory_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s.update({"components": [], "dependencies": []}))
        with self.assertRaisesRegex(ValueError, "non-empty"):
            verify(root, require_signature=False)


if __name__ == "__main__":
    unittest.main()
