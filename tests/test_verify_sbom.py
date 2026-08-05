import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.verify_sbom import SbomError, verify_sbom


HASH_A = "a" * 64
HASH_B = "b" * 64


def valid_sbom():
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "components": [
            {
                "type": "application",
                "bom-ref": "pkg:pypi/nexus-app@1.0.0",
                "name": "nexus-app",
                "version": "1.0.0",
                "purl": "pkg:pypi/nexus-app@1.0.0",
                "hashes": [{"alg": "SHA-256", "content": HASH_A}],
            },
            {
                "type": "library",
                "bom-ref": "pkg:pypi/example@2.0.0",
                "name": "example",
                "version": "2.0.0",
                "purl": "pkg:pypi/example@2.0.0",
                "hashes": [{"alg": "SHA-256", "content": HASH_B}],
            },
        ],
        "dependencies": [
            {"ref": "pkg:pypi/nexus-app@1.0.0", "dependsOn": ["pkg:pypi/example@2.0.0"]},
            {"ref": "pkg:pypi/example@2.0.0", "dependsOn": []},
        ],
    }


class VerifySbomTests(unittest.TestCase):
    def test_accepts_valid_document_and_is_deterministic(self):
        first = verify_sbom(valid_sbom())
        second = verify_sbom(json.loads(json.dumps(valid_sbom())))
        self.assertTrue(first["valid"])
        self.assertEqual(first, second)
        self.assertEqual(first["componentCount"], 2)

    def test_rejects_unknown_dependency(self):
        document = valid_sbom()
        document["dependencies"][0]["dependsOn"] = ["pkg:pypi/missing@1"]
        with self.assertRaisesRegex(SbomError, "unknown component"):
            verify_sbom(document)

    def test_rejects_duplicate_identity(self):
        document = valid_sbom()
        duplicate = copy.deepcopy(document["components"][0])
        document["components"].append(duplicate)
        with self.assertRaisesRegex(SbomError, "duplicate bom-ref"):
            verify_sbom(document)

    def test_rejects_missing_or_weak_hash(self):
        document = valid_sbom()
        document["components"][0]["hashes"] = [{"alg": "SHA-1", "content": "a" * 40}]
        with self.assertRaisesRegex(SbomError, "exactly one SHA-256"):
            verify_sbom(document)

    def test_rejects_self_dependency(self):
        document = valid_sbom()
        ref = document["dependencies"][0]["ref"]
        document["dependencies"][0]["dependsOn"] = [ref]
        with self.assertRaisesRegex(SbomError, "self-dependency"):
            verify_sbom(document)

    def test_cli_fails_closed_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sbom.json"
            path.write_text("{", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "scripts/verify_sbom.py", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn('"valid": false', result.stderr)


if __name__ == "__main__":
    unittest.main()
