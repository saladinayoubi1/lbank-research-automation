from __future__ import annotations

from pathlib import Path

import pytest

from nexus_multitimeframe_strategy_discovery import (
    APPROVED_FAMILIES,
    APPROVED_TIMEFRAMES,
    _digest as discovery_digest,
)
from nexus_strategy_proposal_runtime_requalification import (
    ARCHIVE_SHA256,
    ProductResearchError,
    StrategyProposalRequalificationError,
    _digest,
    build_requalification,
    verify_requalification,
)

SOURCE_SHA = "a" * 40
DATASET_SHA = ARCHIVE_SHA256


def _discovery(*, proposal_count: int = 1):
    cells = [
        {"timeframe": timeframe, "family": family}
        for timeframe in APPROVED_TIMEFRAMES
        for family in APPROVED_FAMILIES
    ]
    proposals = []
    if proposal_count:
        proposal_core = {
            "proposal_state": "RESEARCH_PROPOSAL",
            "family": "momentum",
            "timeframe": "hour4",
            "strategy_config": {"lookback": 16, "entry_threshold": 0.0015},
            "variant_id": "variant-001",
            "cell_digest": "c" * 64,
            "dataset_archive_sha256": DATASET_SHA,
            "requires_independent_runtime_requalification": True,
            "paper_only": True,
            "live_trading_authority": False,
            "promotion_authority": False,
        }
        proposals.append({**proposal_core, "proposal_digest": discovery_digest(proposal_core)})
    core = {
        "schema_version": "nexus.multitimeframe-strategy-discovery.v1",
        "dataset_archive_sha256": DATASET_SHA,
        "cells": cells,
        "research_proposals": proposals,
        "research_proposal_count": len(proposals),
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "automatic_paper_forward_started": False,
    }
    result = {**core, "discovery_digest": discovery_digest(core)}
    queue = {
        "schema_version": "nexus.strategy-research-proposal-queue.v1",
        "source_discovery_digest": result["discovery_digest"],
        "proposals": proposals,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return result, queue


def _evaluation(proposal, symbol, status="paper_candidate"):
    return {
        "symbol": symbol,
        "family": proposal["family"],
        "timeframe": proposal["timeframe"],
        "variant_id": proposal["variant_id"],
        "runtime_dataset_binding_sha256": ("d" if symbol == "BTCUSDT" else "e") * 64,
        "runtime_last_open_time_ms": 1_787_875_200_000,
        "qualification_status": status,
        "pipeline_digest": "2" * 64,
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


def test_requalification_qualifies_only_for_review_without_paper_or_promotion(tmp_path: Path):
    discovery, queue = _discovery()

    def evaluator(proposal, symbol, source_sha, now_ms, state_root):
        assert source_sha == SOURCE_SHA
        assert now_ms == 1_787_875_200_000
        assert state_root == tmp_path.resolve()
        return _evaluation(proposal, symbol)

    result = build_requalification(
        discovery,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path,
        now_ms=1_787_875_200_000,
        evaluator=evaluator,
    )
    assert result["status"] == "EVALUATED"
    assert result["qualified_for_review_count"] == 1
    assert result["rejected_count"] == 0
    assert result["blocked_runtime_data_count"] == 0
    row = result["proposal_results"][0]
    assert row["verdict"] == "QUALIFIED_FOR_REVIEW"
    assert row["candidate_state_created"] is False
    assert row["paper_execution_started"] is False
    assert row["automatic_strategy_promotion"] is False
    assert result["promotion_authority"] is False
    assert result["live_trading_authority"] is False
    assert verify_requalification(result)["decision"] == "pass"


def test_requalification_rejects_when_one_symbol_is_killed(tmp_path: Path):
    discovery, queue = _discovery()

    def evaluator(proposal, symbol, *_args):
        return _evaluation(
            proposal,
            symbol,
            "killed" if symbol == "ETHUSDT" else "paper_candidate",
        )

    result = build_requalification(
        discovery,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path,
        now_ms=1_787_875_200_000,
        evaluator=evaluator,
    )
    assert result["status"] == "EVALUATED"
    assert result["qualified_for_review_count"] == 0
    assert result["rejected_count"] == 1
    assert result["proposal_results"][0]["verdict"] == "REJECTED"
    assert verify_requalification(result)["decision"] == "pass"


def test_requalification_records_runtime_data_blocker_fail_closed(tmp_path: Path):
    discovery, queue = _discovery()

    def evaluator(*_args):
        raise ProductResearchError("canonical public dataset unavailable: HTTP 403")

    result = build_requalification(
        discovery,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path,
        now_ms=1_787_875_200_000,
        evaluator=evaluator,
    )
    assert result["status"] == "WAITING_FOR_RUNTIME_DATA"
    assert result["blocked_runtime_data_count"] == 1
    row = result["proposal_results"][0]
    assert row["verdict"] == "BLOCKED_RUNTIME_DATA"
    assert row["runtime_evaluations"] == []
    assert row["blocked"]["error_type"] == "ProductResearchError"
    assert verify_requalification(result)["decision"] == "pass"


def test_requalification_zero_proposals_is_valid_no_work(tmp_path: Path):
    discovery, queue = _discovery(proposal_count=0)
    result = build_requalification(
        discovery,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path,
        now_ms=1_787_875_200_000,
        evaluator=lambda *_args: pytest.fail("evaluator must not run for zero proposals"),
    )
    assert result["status"] == "NO_WORK"
    assert result["proposal_count"] == 0
    assert result["proposal_results"] == []
    assert verify_requalification(result)["decision"] == "pass"


def test_requalification_rejects_unbound_queue_and_tampered_completion(tmp_path: Path):
    discovery, queue = _discovery()
    with pytest.raises(StrategyProposalRequalificationError, match="exact discovery"):
        build_requalification(
            discovery,
            queue,
            source_sha=SOURCE_SHA,
            discovery_source_sha="9" * 40,
            state_root=tmp_path,
            now_ms=1_787_875_200_000,
            evaluator=lambda proposal, symbol, *_args: _evaluation(proposal, symbol),
        )

    bad_queue = dict(queue)
    bad_queue["source_discovery_digest"] = "0" * 64
    with pytest.raises(StrategyProposalRequalificationError, match="bound to discovery"):
        build_requalification(
            discovery,
            bad_queue,
            source_sha=SOURCE_SHA,
            discovery_source_sha=SOURCE_SHA,
            state_root=tmp_path,
            now_ms=1_787_875_200_000,
            evaluator=lambda proposal, symbol, *_args: _evaluation(proposal, symbol),
        )

    result = build_requalification(
        discovery,
        queue,
        source_sha=SOURCE_SHA,
        discovery_source_sha=SOURCE_SHA,
        state_root=tmp_path,
        now_ms=1_787_875_200_000,
        evaluator=lambda proposal, symbol, *_args: _evaluation(proposal, symbol),
    )
    tampered = dict(result)
    tampered["automatic_strategy_promotion"] = True
    assert verify_requalification(tampered)["decision"] == "reject"

    forged = dict(result)
    forged_rows = [dict(row) for row in result["proposal_results"]]
    forged_rows[0]["candidate_state_created"] = True
    unsigned = dict(forged_rows[0])
    unsigned.pop("result_digest")
    forged_rows[0]["result_digest"] = _digest(unsigned)
    forged["proposal_results"] = forged_rows
    unsigned_result = dict(forged)
    unsigned_result.pop("requalification_digest")
    forged["requalification_digest"] = _digest(unsigned_result)
    assert verify_requalification(forged)["decision"] == "reject"

    replay_forged = dict(result)
    replay_rows = [dict(row) for row in result["proposal_results"]]
    replay_rows[0]["runtime_evaluations"] = [
        dict(item) for item in replay_rows[0]["runtime_evaluations"]
    ]
    replay_rows[0]["runtime_evaluations"][0]["deterministic_replay_verified"] = False
    unsigned_row = dict(replay_rows[0])
    unsigned_row.pop("result_digest")
    replay_rows[0]["result_digest"] = _digest(unsigned_row)
    replay_forged["proposal_results"] = replay_rows
    unsigned_replay = dict(replay_forged)
    unsigned_replay.pop("requalification_digest")
    replay_forged["requalification_digest"] = _digest(unsigned_replay)
    assert verify_requalification(replay_forged)["decision"] == "reject"


def test_workflow_binds_exact_trigger_artifact_sha_and_read_only_authority() -> None:
    text = Path(
        ".github/workflows/nexus_strategy_proposal_runtime_requalification.yml"
    ).read_text(encoding="utf-8")
    assert "actions/runs/$TRIGGER_RUN_ID/artifacts" in text
    assert "nexus-multitimeframe-strategy-discovery-$TRIGGER_RUN_ID" in text
    assert "github.event.workflow_run.head_sha" in text
    assert '--discovery-source-sha "$TRIGGER_SOURCE_SHA"' in text
    assert 'assert result["source_sha"] == result["discovery_source_sha"]' in text
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "actions: read" in permissions
    assert "write" not in permissions
