from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_paper_boundary_discovery_feedback as feedback


SOURCE_SHA = "a" * 40
LOOP_DIGEST = "b" * 64
DISCOVERY_DIGEST = "c" * 64
REQUAL_DIGEST = "d" * 64
BTC_BOUNDARY = 1_728_000_000_000
ETH_BOUNDARY = 1_728_000_014_400


def _loop_snapshot() -> dict:
    return {
        "source_sha": SOURCE_SHA,
        "run_id": "123",
        "loop_digest": LOOP_DIGEST,
        "status": "PAPER_LOOP_ACTIVE",
        "regime_status": "VERIFIED",
        "strategy_research_required": True,
        "strategy_discovery_health_trigger_requested": True,
        "expected_cell_count": 6,
        "fresh_cell_count": 6,
        "fresh_cells": [
            "BTCUSDT:minute15",
            "BTCUSDT:hour1",
            "BTCUSDT:hour4",
            "ETHUSDT:minute15",
            "ETHUSDT:hour1",
            "ETHUSDT:hour4",
        ],
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }


def _matrix_state() -> dict:
    return {
        "cells": {
            "BTCUSDT:hour4": {
                "status": "VERIFIED",
                "source_sha": SOURCE_SHA,
                "last_completed_open_ms": BTC_BOUNDARY,
            },
            "ETHUSDT:hour4": {
                "status": "VERIFIED",
                "source_sha": SOURCE_SHA,
                "last_completed_open_ms": ETH_BOUNDARY,
            },
        }
    }


def _context(monkeypatch) -> dict:
    monkeypatch.setattr(
        feedback, "verify_loop_snapshot", lambda _value: {"decision": "pass"}
    )
    return feedback.build_boundary_context(_loop_snapshot(), _matrix_state())


def _discovery() -> dict:
    return {
        "source_sha": SOURCE_SHA,
        "discovery_digest": DISCOVERY_DIGEST,
    }


def _evaluation(symbol: str, last_open: int) -> dict:
    return {
        "symbol": symbol,
        "runtime_last_open_time_ms": last_open,
    }


def _requalification(*, btc_last: int = BTC_BOUNDARY, eth_last: int = ETH_BOUNDARY) -> dict:
    proposal = {
        "verdict": "REJECTED",
        "runtime_evaluations": [
            _evaluation("BTCUSDT", btc_last),
            _evaluation("ETHUSDT", eth_last),
        ],
    }
    return {
        "source_sha": SOURCE_SHA,
        "discovery_source_sha": SOURCE_SHA,
        "source_discovery_digest": DISCOVERY_DIGEST,
        "requalification_digest": REQUAL_DIGEST,
        "status": "EVALUATED",
        "proposal_count": 1,
        "qualified_for_review_count": 0,
        "rejected_count": 1,
        "blocked_runtime_data_count": 0,
        "proposal_results": [proposal],
    }


def test_context_binds_exact_fresh_hour4_cells(monkeypatch) -> None:
    context = _context(monkeypatch)
    assert context["source_sha"] == SOURCE_SHA
    assert context["paper_run_id"] == "123"
    assert context["hour4_boundary_ms"] == {
        "BTCUSDT": BTC_BOUNDARY,
        "ETHUSDT": ETH_BOUNDARY,
    }
    assert context["hour4_boundary_digest"] == feedback._digest(
        context["hour4_boundary_ms"]
    )
    assert feedback.verify_boundary_context(context)["decision"] == "pass"


def test_context_rejects_stale_hour4_cell(monkeypatch) -> None:
    monkeypatch.setattr(
        feedback, "verify_loop_snapshot", lambda _value: {"decision": "pass"}
    )
    matrix = _matrix_state()
    matrix["cells"]["ETHUSDT:hour4"]["source_sha"] = "f" * 40
    with pytest.raises(feedback.PaperBoundaryDiscoveryFeedbackError):
        feedback.build_boundary_context(_loop_snapshot(), matrix)


def test_context_rejects_non_health_boundary(monkeypatch) -> None:
    monkeypatch.setattr(
        feedback, "verify_loop_snapshot", lambda _value: {"decision": "pass"}
    )
    snapshot = _loop_snapshot()
    snapshot["strategy_discovery_health_trigger_requested"] = False
    with pytest.raises(feedback.PaperBoundaryDiscoveryFeedbackError):
        feedback.build_boundary_context(snapshot, _matrix_state())


def test_feedback_proves_runtime_data_covers_exact_paper_boundary(monkeypatch) -> None:
    context = _context(monkeypatch)
    monkeypatch.setattr(feedback, "verify_discovery", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        feedback, "verify_requalification", lambda _value: {"decision": "pass"}
    )
    result = feedback.build_feedback(context, _discovery(), _requalification())
    assert result["status"] == "VERIFIED_BOUNDARY_FEEDBACK"
    assert result["boundary_coverage_verified"] is True
    assert result["required_runtime_evaluation_count"] == 2
    assert result["boundary_covered_runtime_evaluation_count"] == 2
    assert result["candidate_state_created"] is False
    assert result["paper_execution_started"] is False
    assert result["live_trading_authority"] is False
    assert feedback.verify_feedback(result)["decision"] == "pass"


def test_feedback_fails_closed_when_runtime_data_is_older_than_boundary(monkeypatch) -> None:
    context = _context(monkeypatch)
    monkeypatch.setattr(feedback, "verify_discovery", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        feedback, "verify_requalification", lambda _value: {"decision": "pass"}
    )
    result = feedback.build_feedback(
        context,
        _discovery(),
        _requalification(eth_last=ETH_BOUNDARY - 14_400_000),
    )
    assert result["status"] == "RUNTIME_BOUNDARY_NOT_COVERED"
    assert result["boundary_coverage_verified"] is False
    assert result["boundary_covered_runtime_evaluation_count"] == 1
    assert feedback.verify_feedback(result)["decision"] == "pass"


def test_feedback_waits_when_requalification_is_runtime_blocked(monkeypatch) -> None:
    context = _context(monkeypatch)
    monkeypatch.setattr(feedback, "verify_discovery", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        feedback, "verify_requalification", lambda _value: {"decision": "pass"}
    )
    blocked = _requalification()
    blocked.update(
        {
            "status": "WAITING_FOR_RUNTIME_DATA",
            "qualified_for_review_count": 0,
            "rejected_count": 0,
            "blocked_runtime_data_count": 1,
            "proposal_results": [
                {"verdict": "BLOCKED_RUNTIME_DATA", "runtime_evaluations": []}
            ],
        }
    )
    result = feedback.build_feedback(context, _discovery(), blocked)
    assert result["status"] == "WAITING_FOR_RUNTIME_DATA"
    assert result["boundary_coverage_verified"] is False
    assert result["required_runtime_evaluation_count"] == 0
    assert feedback.verify_feedback(result)["decision"] == "pass"


def test_feedback_rejects_cross_sha_discovery(monkeypatch) -> None:
    context = _context(monkeypatch)
    monkeypatch.setattr(feedback, "verify_discovery", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        feedback, "verify_requalification", lambda _value: {"decision": "pass"}
    )
    discovery = _discovery()
    discovery["source_sha"] = "e" * 40
    with pytest.raises(feedback.PaperBoundaryDiscoveryFeedbackError):
        feedback.build_feedback(context, discovery, _requalification())


def test_feedback_verifier_rejects_tampering(monkeypatch) -> None:
    context = _context(monkeypatch)
    monkeypatch.setattr(feedback, "verify_discovery", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        feedback, "verify_requalification", lambda _value: {"decision": "pass"}
    )
    result = feedback.build_feedback(context, _discovery(), _requalification())
    tampered = deepcopy(result)
    tampered["hour4_boundary_ms"]["BTCUSDT"] += 1
    assert feedback.verify_feedback(tampered)["decision"] == "reject"
