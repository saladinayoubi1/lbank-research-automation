from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from nexus_demo_archive_replay import ARCHIVE_SHA256
from nexus_multitimeframe_strategy_discovery import (
    APPROVED_FAMILIES,
    APPROVED_TIMEFRAMES,
    _digest as discovery_digest,
)
from nexus_strategy_proposal_runtime_requalification import (
    ProductResearchError,
    build_requalification,
    verify_requalification,
)
from nexus_strategy_review_qa_handoff import (
    StrategyReviewQaHandoffError,
    build_handoff,
    verify_handoff,
)


SOURCE_SHA = "a" * 40
NOW_MS = 1_787_875_200_000


def _discovery():
    proposal_core = {
        "proposal_state": "RESEARCH_PROPOSAL",
        "family": "momentum",
        "timeframe": "hour4",
        "strategy_config": {"lookback": 16, "entry_threshold": 0.0015},
        "variant_id": "variant-001",
        "cell_digest": "c" * 64,
        "dataset_archive_sha256": ARCHIVE_SHA256,
        "requires_independent_runtime_requalification": True,
        "paper_only": True,
        "live_trading_authority": False,
        "promotion_authority": False,
    }
    proposal = {
        **proposal_core,
        "proposal_digest": discovery_digest(proposal_core),
    }
    cells = [
        {"timeframe": timeframe, "family": family}
        for timeframe in APPROVED_TIMEFRAMES
        for family in APPROVED_FAMILIES
    ]
    discovery_core = {
        "schema_version": "nexus.multitimeframe-strategy-discovery.v1",
        "source_sha": SOURCE_SHA,
        "dataset_archive_sha256": ARCHIVE_SHA256,
        "cells": cells,
        "research_proposals": [proposal],
        "research_proposal_count": 1,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "automatic_paper_forward_started": False,
    }
    discovery = {
        **discovery_core,
        "discovery_digest": discovery_digest(discovery_core),
    }
    queue = {
        "schema_version": "nexus.strategy-research-proposal-queue.v1",
        "source_discovery_sha": SOURCE_SHA,
        "source_discovery_digest": discovery["discovery_digest"],
        "proposals": [proposal],
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return discovery, queue


def _evaluation(proposal, symbol, status="paper_candidate"):
    return {
        "symbol": symbol,
        "family": proposal["family"],
        "timeframe": proposal["timeframe"],
        "variant_id": proposal["variant_id"],
        "runtime_dataset_binding_sha256": ("d" if symbol == "BTCUSDT" else "e") * 64,
        "runtime_last_open_time_ms": NOW_MS,
        "qualification_status": status,
        "pipeline_digest": ("2" if symbol == "BTCUSDT" else "3") * 64,
        "qualification_digest": ("f" if symbol == "BTCUSDT" else "1") * 64,
        "kill_reasons": [] if status == "paper_candidate" else ["OOS_KILL"],
        "deterministic_replay_verified": True,
        "data_origin": "canonical_public_bybit_runtime",
        "closed_candle_finality_verified": True,
        "paper_only": True,
        "live_trading_authority": False,
        "paper_execution_started": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }


def _requalification(tmp_path: Path, *, eth_status="paper_candidate"):
    discovery, queue = _discovery()

    def evaluator(proposal, symbol, *_args):
        return _evaluation(
            proposal,
            symbol,
            eth_status if symbol == "ETHUSDT" else "paper_candidate",
        )

    result = build_requalification(
        discovery,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path,
        now_ms=NOW_MS,
        evaluator=evaluator,
    )
    verification = verify_requalification(result)
    assert verification["decision"] == "pass"
    return result, verification


def test_qualified_review_builds_exact_qa41_handoff(tmp_path: Path) -> None:
    result, verification = _requalification(tmp_path)

    handoff = build_handoff(result, verification)

    assert handoff["status"] == "READY_FOR_QA"
    assert handoff["task_count"] == 1
    assert handoff["required_verifier"] == "qa-verifier-agent"
    assert handoff["source_sha"] == SOURCE_SHA
    assert handoff["requalification_digest"] == result["requalification_digest"]
    assert handoff["requalification_verification_digest"] == verification["verification_digest"]
    assert handoff["candidate_creation_authority"] is False
    assert handoff["qualification_authority"] is False
    assert handoff["promotion_authority"] is False
    assert handoff["paper_execution_authority"] is False
    assert handoff["automatic_strategy_promotion"] is False
    assert handoff["live_trading_authority"] is False

    task = handoff["tasks"][0]
    source_row = result["proposal_results"][0]
    assert task["id"] == f"STRATEGY-QA-{source_row['proposal_digest']}"
    assert task["system_map_node"] == "QA-41"
    assert task["status"] == "READY_FOR_QA_DISPATCH"
    assert task["proposal_digest"] == source_row["proposal_digest"]
    assert task["proposal_result_digest"] == source_row["result_digest"]
    assert task["required_verifier"] == "qa-verifier-agent"
    assert task["strategy_config"] == {"lookback": 16, "entry_threshold": 0.0015}
    assert task["strategy_config_digest"] == source_row["strategy_config_digest"]
    assert [item["symbol"] for item in task["runtime_evidence"]] == ["BTCUSDT", "ETHUSDT"]
    assert verify_handoff(handoff)["decision"] == "pass"


def test_rejected_review_produces_no_qa_work(tmp_path: Path) -> None:
    result, verification = _requalification(tmp_path, eth_status="killed")
    assert result["proposal_results"][0]["verdict"] == "REJECTED"

    handoff = build_handoff(result, verification)

    assert handoff["status"] == "NO_WORK"
    assert handoff["task_count"] == 0
    assert handoff["tasks"] == []
    assert verify_handoff(handoff)["decision"] == "pass"


def test_blocked_runtime_data_produces_no_qa_work(tmp_path: Path) -> None:
    discovery, queue = _discovery()

    def evaluator(*_args):
        raise ProductResearchError("canonical public dataset unavailable")

    result = build_requalification(
        discovery,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path,
        now_ms=NOW_MS,
        evaluator=evaluator,
    )
    verification = verify_requalification(result)
    assert result["status"] == "WAITING_FOR_RUNTIME_DATA"
    assert verification["decision"] == "pass"

    handoff = build_handoff(result, verification)

    assert handoff["status"] == "NO_WORK"
    assert handoff["task_count"] == 0
    assert verify_handoff(handoff)["decision"] == "pass"


def test_stale_or_tampered_requalification_verification_is_rejected(tmp_path: Path) -> None:
    result, verification = _requalification(tmp_path)
    tampered = deepcopy(verification)
    tampered["checks"] = dict(tampered["checks"])
    tampered["checks"]["results"] = False

    with pytest.raises(StrategyReviewQaHandoffError, match="verification artifact"):
        build_handoff(result, tampered)


def test_authority_or_source_tamper_cannot_enter_qa_handoff(tmp_path: Path) -> None:
    result, _ = _requalification(tmp_path)

    authority_tamper = deepcopy(result)
    authority_tamper["promotion_authority"] = True
    authority_core = dict(authority_tamper)
    authority_core.pop("requalification_digest")
    authority_tamper["requalification_digest"] = discovery_digest(authority_core)
    authority_verification = verify_requalification(authority_tamper)
    assert authority_verification["decision"] == "reject"
    with pytest.raises(StrategyReviewQaHandoffError, match="failed verification"):
        build_handoff(authority_tamper, authority_verification)

    source_tamper = deepcopy(result)
    source_tamper["discovery_source_sha"] = "b" * 40
    source_core = dict(source_tamper)
    source_core.pop("requalification_digest")
    source_tamper["requalification_digest"] = discovery_digest(source_core)
    source_verification = verify_requalification(source_tamper)
    assert source_verification["decision"] == "reject"
    with pytest.raises(StrategyReviewQaHandoffError, match="failed verification"):
        build_handoff(source_tamper, source_verification)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_verifier", "generic-verifier"),
        ("live_trading_authority", True),
        ("paper_execution_authority", True),
        ("qualification_authority", True),
    ],
)
def test_handoff_verifier_rejects_authority_or_verifier_tamper(
    tmp_path: Path, field: str, value
) -> None:
    result, verification = _requalification(tmp_path)
    handoff = build_handoff(result, verification)
    tampered = deepcopy(handoff)
    tampered["tasks"][0][field] = value

    assert verify_handoff(tampered)["decision"] == "reject"


def test_strategy_config_tamper_is_fail_closed(tmp_path: Path) -> None:
    result, verification = _requalification(tmp_path)
    handoff = build_handoff(result, verification)

    tampered_task = deepcopy(handoff)
    tampered_task["tasks"][0]["strategy_config"]["lookback"] = 99
    assert verify_handoff(tampered_task)["decision"] == "reject"

    tampered_requalification = deepcopy(result)
    tampered_requalification["proposal_results"][0]["strategy_config"]["lookback"] = 99
    tampered_verification = verify_requalification(tampered_requalification)
    assert tampered_verification["decision"] == "reject"
    with pytest.raises(StrategyReviewQaHandoffError, match="failed verification"):
        build_handoff(tampered_requalification, tampered_verification)


def test_handoff_is_deterministic_for_identical_verified_evidence(tmp_path: Path) -> None:
    result, verification = _requalification(tmp_path)

    first = build_handoff(result, verification)
    second = build_handoff(deepcopy(result), deepcopy(verification))

    assert first == second
    assert first["handoff_digest"] == second["handoff_digest"]
    assert first["tasks"][0]["task_digest"] == second["tasks"][0]["task_digest"]
