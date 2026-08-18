from __future__ import annotations

from copy import deepcopy

import pytest

import phase7_e2e_proof as proof


SOURCE = "a" * 40


def test_phase7_proof_runs_canonical_data_through_strategy_risk_paper_and_performance():
    result = proof.build_proof(SOURCE)
    proof.validate_proof(result, expected_source_sha=SOURCE)

    assert result["paper_only"] is True
    assert result["profitability_claim"] is False
    assert result["live_trading_authority"] is False
    assert result["canonical_data"]["source"] == "Bybit"
    assert result["canonical_data"]["source_role"] == "primary"
    assert result["canonical_data"]["finality"] == "closed_only"
    assert result["canonical_data"]["row_count"] == 90
    assert result["strategy"]["qualification_status"] == "paper_candidate"
    assert result["risk"]["allowed"] is True
    assert result["risk"]["reason_code"] == "risk_allowed"
    assert result["paper"]["event_count"] >= 8
    assert len(result["paper"]["event_digests"]) == result["paper"]["event_count"]
    assert result["performance_drift"]["metrics"]["elapsed_years"] > 0
    assert result["performance_drift"]["drift_status"] in {"OBSERVED_BOUNDED_PAPER_COST", "NO_NEGATIVE_DRIFT"}


def test_phase7_proof_is_byte_deterministic_for_exact_source():
    first = proof.build_proof(SOURCE)
    second = proof.build_proof(SOURCE)
    assert first == second
    assert first["proof_digest"] == second["proof_digest"]


def test_phase7_proof_tamper_and_source_mismatch_fail_closed():
    original = proof.build_proof(SOURCE)
    tampered = deepcopy(original)
    tampered["paper"]["ending_equity"] = "999999"
    with pytest.raises(proof.Phase7ProofError, match="digest"):
        proof.validate_proof(tampered, expected_source_sha=SOURCE)
    with pytest.raises(proof.Phase7ProofError, match="source SHA"):
        proof.validate_proof(original, expected_source_sha="b" * 40)


def test_phase7_proof_rejects_invalid_source_sha():
    with pytest.raises(proof.Phase7ProofError, match="40-character"):
        proof.build_proof("not-a-sha")
