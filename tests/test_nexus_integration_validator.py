from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from nexus_integration_validator import (
    IntegrationValidationError,
    load_and_validate,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "nexus-integration-registry.json"


def payload() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


class NexusIntegrationValidatorTests(unittest.TestCase):
    def test_current_integration_registry_is_valid(self) -> None:
        load_and_validate(REGISTRY)

    def test_every_canonical_edge_has_state_verifier_and_evidence(self) -> None:
        current = payload()
        node_types = {node["id"]: node["type"] for node in current["nodes"]}
        for edge in current["edges"]:
            self.assertTrue(edge["durable_state"])
            self.assertEqual(node_types[edge["verifier"]], "verifier")
            self.assertNotEqual(edge["verifier"], edge["producer"])
            self.assertTrue(edge["evidence"])
            self.assertEqual(edge["status"], "VERIFIED")

    def test_authority_and_verification_mutations_fail_closed(self) -> None:
        mutations = [
            (lambda value: value.__setitem__("live_trading", True), "live trading false"),
            (lambda value: value["nodes"][1].__setitem__("authority", "execution"), "AI Room"),
            (lambda value: next(node for node in value["nodes"] if node["id"] == "risk").__setitem__("authority", "advisory"), "Risk"),
            (lambda value: next(node for node in value["nodes"] if node["id"] == "paper").__setitem__("authority", "live"), "Paper"),
            (lambda value: value["edges"][2].__setitem__("verifier", "mission"), "producer cannot verify|not a verifier"),
            (lambda value: value["edges"][8].__setitem__("status", "DONE"), "unsupported"),
        ]
        for mutation, message in mutations:
            with self.subTest(message=message):
                current = deepcopy(payload())
                mutation(current)
                with self.assertRaisesRegex(IntegrationValidationError, message):
                    validate_registry(current)

    def test_missing_canonical_connection_fails_closed(self) -> None:
        current = deepcopy(payload())
        current["edges"] = [edge for edge in current["edges"] if edge["id"] != "risk-to-paper"]
        with self.assertRaisesRegex(IntegrationValidationError, "missing edges"):
            validate_registry(current)

    def test_unknown_field_fails_closed(self) -> None:
        current = deepcopy(payload())
        current["edges"][0]["allow_live"] = False
        with self.assertRaisesRegex(IntegrationValidationError, "schema mismatch"):
            validate_registry(current)

    def test_missing_evidence_file_fails_closed(self) -> None:
        current = deepcopy(payload())
        current["edges"][0]["evidence"] = ["tests/does-not-exist.py"]
        with self.assertRaisesRegex(IntegrationValidationError, "does not reference"):
            validate_registry(current)

    def test_registry_path_must_not_be_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / "registry.json"
            try:
                link.symlink_to(REGISTRY)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable")
            with self.assertRaisesRegex(IntegrationValidationError, "non-symlink"):
                load_and_validate(link)


if __name__ == "__main__":
    unittest.main()
