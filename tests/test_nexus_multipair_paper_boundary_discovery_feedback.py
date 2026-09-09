from __future__ import annotations

import copy

import pytest

import nexus_multipair_paper_boundary_discovery_feedback as feedback
from nexus_multipair_trusted_surface import FAMILIES, SYMBOLS, TIMEFRAMES


SHA = "1" * 40
HOUR4_MS = 4 * 60 * 60 * 1000
BOUNDARY_MS = HOUR4_MS * 100_000


def _loop_snapshot() -> dict:
    cells = sorted(f"{symbol}:{timeframe}" for symbol in SYMBOLS for timeframe in TIMEFRAMES)
    return {
        "source_sha": SHA,
        "loop_digest": "2" * 64,
        "run_id": "123456789",
        "status": "PAPER_LOOP_ACTIVE",
        "regime_status": "VERIFIED",
        "expected_cell_count": 12,
        "fresh_cell_count": 12,
        "expected_lane_count": 36,
        "fresh_cells": cells,
        "strategy_research_required": True,
        "strategy_discovery_health_trigger_requested": True,
        "regime_selected_rebalance_operational": True,
        "performance_health_feedback_operational": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
    }


def _matrix_state() -> dict:
    cells = {}
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            cells[f"{symbol}:{timeframe}"] = {
                "status": "VERIFIED",
                "source_sha": SHA,
                "last_completed_open_ms": BOUNDARY_MS if timeframe == "hour4" else BOUNDARY_MS + 1,
            }
    return {"cells": cells}


def _proof(*, status: str = "NO_WORK", proposal_count: int = 0) -> dict:
    qualified = 0 if status == "NO_WORK" else 1
    rejected = 0 if status == "NO_WORK" else proposal_count - qualified
    return {
        "schema_version": feedback.PROOF_SCHEMA,
        "source_sha": SHA,
        "run_id": "987654321",
        "execution_plane": "nexus-bybit-network",
        "trusted_surface_source": "config/nexus-demo-strategy-matrix-v2.json",
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "families": list(FAMILIES),
        "snapshot_cell_count": 12,
        "discovery_hypothesis_count": 9,
        "snapshot_digest": "3" * 64,
        "discovery_digest": "4" * 64,
        "runtime_snapshot_digest": "5" * 64,
        "requalification_digest": "6" * 64,
        "runtime_snapshot_history_limit": 240,
        "runtime_snapshot_data_origin": "canonical_public_bybit_closed_candles",
        "runtime_snapshot_transport": "digest_pinned_physical_bybit_rest_snapshot",
        "runtime_snapshot_distinct_from_discovery": True,
        "historical_discovery_snapshot_reused": False,
        "runtime_snapshot_freshness_verified": True,
        "runtime_snapshot_as_of_ms": BOUNDARY_MS + HOUR4_MS + 60_000,
        "blocked_runtime_data_count": 0,
        "runtime_data_is_fresh_not_snapshot_reuse": True,
        "requalification_status": status,
        "research_proposal_count": proposal_count,
        "qualified_for_review_count": qualified,
        "rejected_count": rejected,
        "research_only": True,
        "paper_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
    }


def _context(monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(feedback, "verify_loop_snapshot", lambda value: {"decision": "pass"})
    value = feedback.build_boundary_context(_loop_snapshot(), _matrix_state())
    assert feedback.verify_boundary_context(value)["decision"] == "pass"
    return value


def test_builds_exact_four_symbol_twelve_cell_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _context(monkeypatch)
    assert context["symbols"] == list(SYMBOLS)
    assert context["timeframes"] == list(TIMEFRAMES)
    assert context["families"] == list(FAMILIES)
    assert context["fresh_cell_count"] == 12
    assert context["hour4_boundary_ms"] == {symbol: BOUNDARY_MS for symbol in SYMBOLS}
    assert context["issue_984_state_artifact_touched"] is False


def test_boundary_rejects_missing_fresh_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feedback, "verify_loop_snapshot", lambda value: {"decision": "pass"})
    loop = _loop_snapshot()
    loop["fresh_cells"] = loop["fresh_cells"][:-1]
    with pytest.raises(feedback.MultiPairPaperBoundaryFeedbackError):
        feedback.build_boundary_context(loop, _matrix_state())


def test_boundary_rejects_matrix_cell_from_wrong_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feedback, "verify_loop_snapshot", lambda value: {"decision": "pass"})
    matrix = _matrix_state()
    matrix["cells"][f"{SYMBOLS[0]}:hour4"]["source_sha"] = "9" * 40
    with pytest.raises(feedback.MultiPairPaperBoundaryFeedbackError):
        feedback.build_boundary_context(_loop_snapshot(), matrix)


def test_zero_proposal_proof_yields_verified_no_work(monkeypatch: pytest.MonkeyPatch) -> None:
    result = feedback.build_feedback(_context(monkeypatch), _proof())
    assert result["status"] == "VERIFIED_NO_RESEARCH_PROPOSALS"
    assert result["proposal_count"] == 0
    assert result["paper_boundary_coverage_verified"] is True
    assert result["candidate_state_created"] is False
    assert feedback.verify_feedback(result)["decision"] == "pass"


def test_evaluated_proof_yields_verified_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    result = feedback.build_feedback(_context(monkeypatch), _proof(status="EVALUATED", proposal_count=2))
    assert result["status"] == "VERIFIED_RESEARCH_PROPOSALS_EVALUATED"
    assert result["qualified_for_review_count"] == 1
    assert result["rejected_count"] == 1
    assert feedback.verify_feedback(result)["decision"] == "pass"


def test_feedback_rejects_proof_from_different_source(monkeypatch: pytest.MonkeyPatch) -> None:
    proof = _proof()
    proof["source_sha"] = "8" * 40
    with pytest.raises(feedback.MultiPairPaperBoundaryFeedbackError):
        feedback.build_feedback(_context(monkeypatch), proof)


def test_feedback_rejects_runtime_snapshot_before_paper_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    proof = _proof()
    proof["runtime_snapshot_as_of_ms"] = BOUNDARY_MS + HOUR4_MS - 1
    with pytest.raises(feedback.MultiPairPaperBoundaryFeedbackError):
        feedback.build_feedback(_context(monkeypatch), proof)


def test_feedback_rejects_authority_widening(monkeypatch: pytest.MonkeyPatch) -> None:
    proof = _proof()
    proof["automatic_strategy_promotion"] = True
    with pytest.raises(feedback.MultiPairPaperBoundaryFeedbackError):
        feedback.build_feedback(_context(monkeypatch), proof)


def test_verifier_rejects_mutated_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    result = feedback.build_feedback(_context(monkeypatch), _proof())
    mutated = copy.deepcopy(result)
    mutated["live_trading_authority"] = True
    assert feedback.verify_feedback(mutated)["decision"] == "reject"
