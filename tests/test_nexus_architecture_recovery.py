from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from nexus_architecture_validator import ContractValidationError, load_and_validate

REGISTRY = Path("docs/architecture/module-contract-registry.yaml")


def test_failed_candidate_does_not_replace_previous_valid_registry(tmp_path: Path) -> None:
    previous_valid = REGISTRY.read_text(encoding="utf-8")
    payload = yaml.safe_load(previous_valid)
    payload["rules"]["live_execution"] = "allowed"

    candidate = tmp_path / "candidate-registry.yaml"
    candidate.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ContractValidationError, match="live_execution"):
        load_and_validate(candidate)

    restored = tmp_path / "restored-registry.yaml"
    restored.write_text(previous_valid, encoding="utf-8")
    load_and_validate(restored)

    assert restored.read_text(encoding="utf-8") == previous_valid
