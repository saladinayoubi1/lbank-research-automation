from __future__ import annotations

from copy import deepcopy

import pytest

import phase5_gate9_e2e as gate9


def test_gate9_terminal_kill_and_cutover_evidence_is_deterministic():
    source = "a" * 40
    first = gate9.run_gate9(source)
    second = gate9.run_gate9(source)
    assert first == second
    gate9.validate_gate9_evidence(first, expected_source_sha=source)
    assert first["gate6"]["status"] == "killed"
    assert first["gate6"]["kill_reasons"] == ["ROBUSTNESS_KILL"]
    assert first["gate6"]["replay_identical"] is True
    assert first["gate6"]["profitability_claim"] is False
    assert first["gate7"]["source"] == "Bybit"
    assert first["gate7"]["source_role"] == "primary"
    assert first["gate8"]["cutover_ready"] is True
    assert all(first["gate8"]["chaos"].values())
    assert first["authority"]["live_execution_allowed"] is False
    assert first["authority"]["l4_owner_required"] is True


def test_gate9_evidence_is_bound_to_exact_git_source_sha():
    evidence = gate9.run_gate9("a" * 40)
    with pytest.raises(gate9.Gate9Error, match="source SHA"):
        gate9.validate_gate9_evidence(evidence, expected_source_sha="b" * 40)


def test_gate9_tampering_and_authority_widening_fail_closed():
    evidence = gate9.run_gate9("a" * 40)
    widened = deepcopy(evidence)
    widened["paper_only"] = False
    with pytest.raises(gate9.Gate9Error, match="authority"):
        gate9.validate_gate9_evidence(widened, expected_source_sha="a" * 40)

    tampered = deepcopy(evidence)
    tampered["gate8"]["cutover_ready"] = False
    with pytest.raises(gate9.Gate9Error, match="cutover"):
        gate9.validate_gate9_evidence(tampered, expected_source_sha="a" * 40)
