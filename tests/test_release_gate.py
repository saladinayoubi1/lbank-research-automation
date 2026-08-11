import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.release_gate import verify


NOW = datetime(2026, 8, 5, 21, 30, tzinfo=timezone.utc)
SOURCE_COMMIT = "0" * 40
BUILDER = "github-actions/release-readiness"
SBOM_SERIAL = "urn:uuid:12345678-1234-5678-1234-567812345678"


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
            "serialNumber": SBOM_SERIAL,
            "metadata": {
                "timestamp": NOW.isoformat().replace("+00:00", "Z"),
                "properties": [{"name": "nexus:graph-completeness", "value": "complete"}],
            },
            "components": [
                {"type": "library", "name": "root", "version": "1", "bom-ref": "pkg:generic/root@1", "purl": "pkg:generic/root@1"},
                {"type": "library", "name": "dep", "version": "1", "bom-ref": "pkg:generic/dep@1", "purl": "pkg:generic/dep@1"},
            ],
            "dependencies": [
                {"ref": "pkg:generic/root@1", "dependsOn": ["pkg:generic/dep@1"]},
                {"ref": "pkg:generic/dep@1", "dependsOn": []},
            ],
        }
        sbom_path = root / "sbom.cdx.json"
        sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
        provenance = {
            "source_commit": SOURCE_COMMIT,
            "builder": BUILDER,
            "issued_at": NOW.isoformat().replace("+00:00", "Z"),
            "sbom_serial_number": SBOM_SERIAL,
            "sbom_sha256": hashlib.sha256(sbom_path.read_bytes()).hexdigest(),
            "subjects": [{"path": "dataset.bin", "sha256": digest}],
        }
        (root / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
        return root

    def mutate_sbom(self, root: Path, fn, *, rebind: bool = False) -> None:
        path = root / "sbom.cdx.json"
        sbom = json.loads(path.read_text())
        fn(sbom)
        path.write_text(json.dumps(sbom), encoding="utf-8")
        if rebind:
            provenance_path = root / "provenance.json"
            provenance = json.loads(provenance_path.read_text())
            provenance["sbom_serial_number"] = sbom.get("serialNumber")
            provenance["sbom_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

    def mutate_provenance(self, root: Path, fn) -> None:
        path = root / "provenance.json"
        provenance = json.loads(path.read_text())
        fn(provenance)
        path.write_text(json.dumps(provenance), encoding="utf-8")

    def verify_ci(self, root: Path):
        return verify(
            root,
            require_signature=False,
            now=NOW,
            expected_source_commit=SOURCE_COMMIT,
            expected_builder=BUILDER,
        )

    def test_unsigned_ci_bundle_passes_internal_consistency(self):
        self.assertEqual(self.verify_ci(self.bundle()), ["manifest", "bundle-inventory", "sbom-complete", "provenance-fresh", "artifact-digests"])

    def test_production_fails_closed_without_signature_policy(self):
        with self.assertRaisesRegex(ValueError, "signature"):
            verify(self.bundle(), require_signature=True, now=NOW)

    def test_tampered_artifact_fails_closed(self):
        root = self.bundle()
        (root / "dataset.bin").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.verify_ci(root)

    def test_missing_sbom_fails_closed(self):
        root = self.bundle()
        (root / "sbom.cdx.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing required file"):
            self.verify_ci(root)

    def test_path_traversal_fails_closed(self):
        root = self.bundle()
        manifest = json.loads((root / "artifact-manifest.json").read_text())
        manifest["artifacts"][0]["path"] = "../dataset.bin"
        (root / "artifact-manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "safe relative path"):
            self.verify_ci(root)

    def test_unmanifested_file_fails_closed(self):
        root = self.bundle()
        (root / "extra.bin").write_bytes(b"undeclared")
        with self.assertRaisesRegex(ValueError, "unmanifested file"):
            self.verify_ci(root)

    def test_unmanifested_nested_file_fails_closed(self):
        root = self.bundle()
        (root / "extra").mkdir()
        (root / "extra" / "payload.bin").write_bytes(b"undeclared")
        with self.assertRaisesRegex(ValueError, "unmanifested file"):
            self.verify_ci(root)

    def test_unmanifested_symlink_fails_closed(self):
        root = self.bundle()
        outside = Path(tempfile.mkdtemp()) / "outside.bin"
        outside.write_bytes(b"outside")
        try:
            (root / "extra-link").symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable on this runner")
        with self.assertRaisesRegex(ValueError, "symlink is not allowed"):
            self.verify_ci(root)

    def test_symlinked_artifact_fails_closed(self):
        root = self.bundle()
        outside = Path(tempfile.mkdtemp()) / "outside.bin"
        outside.write_bytes((root / "dataset.bin").read_bytes())
        (root / "dataset.bin").unlink()
        try:
            (root / "dataset.bin").symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable on this runner")
        with self.assertRaisesRegex(ValueError, "must not be a symlink"):
            self.verify_ci(root)

    def test_symlinked_metadata_fails_closed(self):
        root = self.bundle()
        outside = Path(tempfile.mkdtemp()) / "provenance.json"
        outside.write_bytes((root / "provenance.json").read_bytes())
        (root / "provenance.json").unlink()
        try:
            (root / "provenance.json").symlink_to(outside)
        except OSError:
            self.skipTest("symlinks unavailable on this runner")
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.verify_ci(root)

    def test_symlinked_bundle_root_fails_closed(self):
        root = self.bundle()
        link = Path(tempfile.mkdtemp()) / "bundle-link"
        try:
            link.symlink_to(root, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable on this runner")
        with self.assertRaisesRegex(ValueError, "is a symlink"):
            self.verify_ci(link)

    def test_unknown_completeness_is_explicit(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["metadata"].pop("properties"), rebind=True)
        self.assertIn("sbom-unknown", self.verify_ci(root))

    def test_complete_graph_requires_dependency_entry_per_component(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["dependencies"].pop(), rebind=True)
        with self.assertRaisesRegex(ValueError, "one dependency entry per component"):
            self.verify_ci(root)

    def test_cycle_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["dependencies"][1]["dependsOn"].append("pkg:generic/root@1"), rebind=True)
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.verify_ci(root)

    def test_unknown_dependency_target_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["dependencies"][0]["dependsOn"].append("pkg:generic/missing@1"), rebind=True)
        with self.assertRaisesRegex(ValueError, "unknown dependency target"):
            self.verify_ci(root)

    def test_malformed_purl_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["components"][0].update({"purl": "pkg:bad value"}), rebind=True)
        with self.assertRaisesRegex(ValueError, "malformed component purl"):
            self.verify_ci(root)

    def test_empty_inventory_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s.update({"components": [], "dependencies": []}), rebind=True)
        with self.assertRaisesRegex(ValueError, "non-empty"):
            self.verify_ci(root)

    def test_stale_sbom_is_rejected_even_when_digest_is_rebound(self):
        root = self.bundle()
        stale = (NOW - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
        self.mutate_sbom(root, lambda s: s["metadata"].update({"timestamp": stale}), rebind=True)
        with self.assertRaisesRegex(ValueError, "SBOM metadata.timestamp is stale"):
            self.verify_ci(root)

    def test_stale_provenance_is_rejected(self):
        root = self.bundle()
        stale = (NOW - timedelta(hours=25)).isoformat().replace("+00:00", "Z")
        self.mutate_provenance(root, lambda p: p.update({"issued_at": stale}))
        with self.assertRaisesRegex(ValueError, "provenance issued_at is stale"):
            self.verify_ci(root)

    def test_future_dated_evidence_is_rejected(self):
        root = self.bundle()
        future = (NOW + timedelta(minutes=6)).isoformat().replace("+00:00", "Z")
        self.mutate_provenance(root, lambda p: p.update({"issued_at": future}))
        with self.assertRaisesRegex(ValueError, "too far in the future"):
            self.verify_ci(root)

    def test_wrong_source_commit_is_rejected(self):
        root = self.bundle()
        self.mutate_provenance(root, lambda p: p.update({"source_commit": "1" * 40}))
        with self.assertRaisesRegex(ValueError, "source_commit mismatch"):
            self.verify_ci(root)

    def test_wrong_builder_is_rejected(self):
        root = self.bundle()
        self.mutate_provenance(root, lambda p: p.update({"builder": "untrusted-builder"}))
        with self.assertRaisesRegex(ValueError, "builder mismatch"):
            self.verify_ci(root)

    def test_sbom_substitution_is_rejected(self):
        root = self.bundle()
        self.mutate_sbom(root, lambda s: s["components"][0].update({"name": "substituted"}))
        with self.assertRaisesRegex(ValueError, "SBOM digest mismatch"):
            self.verify_ci(root)

    def test_sbom_serial_replay_is_rejected(self):
        root = self.bundle()
        self.mutate_provenance(root, lambda p: p.update({"sbom_serial_number": "urn:uuid:aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"}))
        with self.assertRaisesRegex(ValueError, "SBOM serial mismatch"):
            self.verify_ci(root)

    def test_duplicate_provenance_subject_is_rejected(self):
        root = self.bundle()
        self.mutate_provenance(root, lambda p: p["subjects"].append(dict(p["subjects"][0])))
        with self.assertRaisesRegex(ValueError, "duplicate provenance subject"):
            self.verify_ci(root)

    def test_extra_provenance_subject_is_rejected(self):
        root = self.bundle()
        extra = {"path": "extra.bin", "sha256": "a" * 64}
        self.mutate_provenance(root, lambda p: p["subjects"].append(extra))
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.verify_ci(root)


if __name__ == "__main__":
    unittest.main()
