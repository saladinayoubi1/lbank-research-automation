from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

import scripts.validate_research_registry as gate


def _copy_registry(tmp_path: Path) -> tuple[Path, dict]:
    registry = json.loads(gate.DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    return path, registry


def test_canonical_registry_passes():
    gate.validate()


def test_market_authority_is_bybit_first_and_lbank_tertiary():
    registry = json.loads(gate.DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    assert registry["market_authority"] == gate.AUTHORITY
    carry = gate._json(gate.ROOT / "research" / "evidence" / "funding_basis_carry_evidence_matrix.json")
    assert carry["market_authority"] == gate.AUTHORITY


def test_funding_basis_carry_claims_are_fully_bound():
    matrix = gate._json(gate.ROOT / "research" / "evidence" / "funding_basis_carry_evidence_matrix.json")
    evidence_ids = {row["id"] for row in matrix["evidence"]}
    assert len(matrix["claims"]) == 3
    assert len(matrix["evidence"]) == 9
    for claim in matrix["claims"]:
        assert len(claim["source_ids"]) == 3
        assert set(claim["source_ids"]) <= evidence_ids
    assert matrix["minimum_paper_test_contract"]["venue"].startswith("Bybit primary")


def test_digest_substitution_fails(tmp_path: Path):
    path, registry = _copy_registry(tmp_path)
    registry["entries"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        gate.validate(path)


def test_registry_digest_normalizes_crlf(tmp_path: Path):
    path = tmp_path / "evidence.md"
    path.write_bytes(b"one\r\ntwo\r\n")
    assert gate._canonical_text_bytes(path) == b"one\ntwo\n"


@pytest.mark.parametrize("bad", [True, 0, 364, 366, "365"])
def test_review_policy_is_exact_and_bool_safe(tmp_path: Path, bad: object):
    path, registry = _copy_registry(tmp_path)
    registry["max_review_age_days"] = bad
    path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="review policy"):
        gate.validate(path)


def test_duplicate_json_key_fails(tmp_path: Path):
    path = tmp_path / "registry.json"
    path.write_text('{"schema":"x","schema":"y"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        gate.validate(path)


def test_symlink_and_hardlink_registry_targets_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    original_root = gate.ROOT
    monkeypatch.setattr(gate, "ROOT", tmp_path)
    protocol = tmp_path / "protocol.md"
    protocol.write_text("research only", encoding="utf-8")
    target = tmp_path / "matrix.md"
    target.write_text("matrix", encoding="utf-8")
    linked = tmp_path / "linked.md"
    linked.symlink_to(target)
    registry = {
        "schema": gate.SCHEMA, "status": "research-only", "paper_trading_only": True,
        "market_authority": gate.AUTHORITY, "protocol": "protocol.md", "max_review_age_days": 365,
        "entries": [{"id": "REG-TEST-001", "path": "linked.md", "sha256": hashlib.sha256(b"matrix").hexdigest(), "format": "evidence-matrix-markdown", "domains": ["test"]}],
    }
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe registry target"):
        gate.validate(path)
    linked.unlink()
    os.link(target, linked)
    with pytest.raises(ValueError, match="unsafe registry target"):
        gate.validate(path)
    monkeypatch.setattr(gate, "ROOT", original_root)
