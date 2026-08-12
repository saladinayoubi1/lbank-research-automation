import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_release_evidence import build_bundle
from scripts.release_gate import verify


SOURCE_COMMIT = "1" * 40
BUILDER = "github-actions/nexus-build-verification/test"


class BuildReleaseEvidenceTests(unittest.TestCase):
    def test_generated_bundle_passes_unsigned_release_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"artifact-bytes\n")
            bundle = root / "bundle"
            cwd = Path.cwd()
            try:
                import os
                os.chdir(root)
                build_bundle(bundle, ["artifact.bin"], SOURCE_COMMIT, BUILDER)
            finally:
                os.chdir(cwd)

            manifest = json.loads((bundle / "artifact-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["purpose"], "ci-build-evidence")
            self.assertFalse(manifest["production_approval"])
            self.assertEqual(len(manifest["artifacts"]), 1)

            checks = verify(
                bundle,
                require_signature=False,
                expected_source_commit=SOURCE_COMMIT,
                expected_builder=BUILDER,
            )
            self.assertIn("manifest", checks)
            self.assertIn("sbom-unknown", checks)
            self.assertIn("provenance-fresh", checks)

    def test_windows_bundle_includes_executables_and_checksum_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dist = root / "desktop" / "lbank-monitor" / "dist"
            dist.mkdir(parents=True)
            (dist / "NEXUS_Setup.exe").write_bytes(b"installer")
            (dist / "NEXUS_Portable.exe").write_bytes(b"portable")
            (dist / "SHA256SUMS.txt").write_text("checksums\n", encoding="ascii")
            bundle = root / "bundle"
            cwd = Path.cwd()
            try:
                import os
                os.chdir(root)
                build_bundle(
                    bundle,
                    ["desktop/lbank-monitor/dist/*.exe", "desktop/lbank-monitor/dist/SHA256SUMS.txt"],
                    SOURCE_COMMIT,
                    BUILDER,
                )
            finally:
                os.chdir(cwd)

            manifest = json.loads((bundle / "artifact-manifest.json").read_text(encoding="utf-8"))
            paths = {entry["path"] for entry in manifest["artifacts"]}
            self.assertEqual(
                paths,
                {
                    "payload/NEXUS_Portable.exe",
                    "payload/NEXUS_Setup.exe",
                    "payload/SHA256SUMS.txt",
                },
            )

    def test_missing_artifact_glob_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = Path.cwd()
            try:
                import os
                os.chdir(root)
                with self.assertRaisesRegex(ValueError, "matched no files"):
                    build_bundle(root / "bundle", ["missing-*.bin"], SOURCE_COMMIT, BUILDER)
            finally:
                os.chdir(cwd)

    def test_invalid_source_commit_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact.bin"
            artifact.write_bytes(b"artifact")
            cwd = Path.cwd()
            try:
                import os
                os.chdir(root)
                with self.assertRaisesRegex(ValueError, "40-character Git SHA"):
                    build_bundle(root / "bundle", ["artifact.bin"], "bad", BUILDER)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
