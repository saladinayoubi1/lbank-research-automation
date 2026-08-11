from __future__ import annotations

from pathlib import Path

import pytest

import project_memory_ci_gate as gate

BASE = "a" * 40
HEAD = "b" * 40


def test_gate_skips_unrelated_changes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gate, "changed_paths", lambda *_args, **_kwargs: {"data/market/example.csv"})
    result = gate.validate_pr(tmp_path, BASE, HEAD)
    assert result == {"validated": False, "reason": "no protected Project Memory path changed"}


def test_gate_binds_validator_to_pr_base_sha(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gate, "changed_paths", lambda *_args, **_kwargs: {"docs/project_memory/STATE.json"})
    seen = {}

    def fake_validate(root, expected_observed_main=None):
        seen["root"] = root
        seen["sha"] = expected_observed_main
        return {"observed_main_sha": expected_observed_main}

    monkeypatch.setattr(gate.pmv, "validate_repository", fake_validate)
    result = gate.validate_pr(tmp_path, BASE, HEAD)
    assert seen["sha"] == BASE
    assert result["validated"] is True
    assert result["protected_changes"] == ["docs/project_memory/STATE.json"]


def test_validator_change_cannot_bypass_memory_gate(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(gate, "changed_paths", lambda *_args, **_kwargs: {"project_memory_validator.py"})

    def reject(*_args, **_kwargs):
        raise gate.pmv.MemoryValidationError("stale Project Memory")

    monkeypatch.setattr(gate.pmv, "validate_repository", reject)
    with pytest.raises(gate.pmv.MemoryValidationError, match="stale Project Memory"):
        gate.validate_pr(tmp_path, BASE, HEAD)


def test_malformed_sha_fails_closed(tmp_path: Path):
    with pytest.raises(ValueError, match="base SHA"):
        gate.changed_paths("not-a-sha", HEAD, tmp_path)
