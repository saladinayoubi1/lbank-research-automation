from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest

import product_research_runtime as product_research
from nexus_isolated_product_runtime import (
    IsolatedProductRuntime,
    regime_paper_account_id,
)
from nexus_regime_paper_lane import prepare_regime_paper_lane
from nexus_regime_strategy_runtime import run_regime_strategy_runtime, verify_runtime_evidence
from product_research_runtime import ProductResearchError, ProductResearchRuntime
from product_runtime import PAPER_ACCOUNT_ID, ProductRuntime, ProductRuntimeError
from tests.test_nexus_regime_strategy_selector import context, policy
from tests.test_product_research_runtime import _dataset, _permissive_kills


SOURCE_SHA = "a" * 40


def _now_ms() -> int:
    return int(time.time() * 1000)


def _research(tmp_path: Path, now_ms: int) -> tuple[IsolatedProductRuntime, ProductResearchRuntime]:
    dataset = _dataset(now_ms)
    account_id = regime_paper_account_id(
        symbol="BTCUSDT", timeframe="minute15", family="momentum"
    )
    runtime = IsolatedProductRuntime(
        tmp_path / "state",
        account_id=account_id,
        clock=lambda: product_research._utc_ms(now_ms),
    )
    research = ProductResearchRuntime(
        runtime,
        source_sha=SOURCE_SHA,
        dataset_fetcher=lambda **_: dataset,
        clock_ms=lambda: now_ms,
    )
    return runtime, research


def _candidate(prepared):
    family = prepared["family"]
    version = prepared["strategy_version"]
    return {
        "family": family,
        "strategy_id": family,
        "strategy_version": version,
        "lifecycle_state": "PAPER",
        "health_state": "HEALTHY",
        "record_digest": prepared["strategy_record_digest"],
        "health_digest": hashlib.sha256(f"{family}:{version}:HEALTHY".encode()).hexdigest(),
        "paper_only": True,
        "live_trading_authority": False,
    }


def test_isolated_runtime_keeps_default_runtime_unchanged_and_aggregates_distinct(tmp_path: Path) -> None:
    default = ProductRuntime(tmp_path / "default")
    first = IsolatedProductRuntime(
        tmp_path / "first",
        account_id=regime_paper_account_id(
            symbol="BTCUSDT", timeframe="minute15", family="momentum"
        ),
    )
    second = IsolatedProductRuntime(
        tmp_path / "second",
        account_id=regime_paper_account_id(
            symbol="BTCUSDT", timeframe="minute15", family="trend_breakout"
        ),
    )
    assert default.paper_snapshot()["account"]["aggregate_id"] == PAPER_ACCOUNT_ID
    first_id = first.paper_snapshot()["account"]["aggregate_id"]
    second_id = second.paper_snapshot()["account"]["aggregate_id"]
    assert first_id != second_id
    assert first_id == first.account_id
    assert second_id == second.account_id


def test_isolated_runtime_rejects_invalid_or_substituted_account_binding(tmp_path: Path) -> None:
    with pytest.raises(ProductRuntimeError, match="account_id"):
        IsolatedProductRuntime(tmp_path / "invalid", account_id="x")
    with pytest.raises(ProductRuntimeError, match="account_id"):
        IsolatedProductRuntime(tmp_path / "long", account_id="x" * 97)

    root = tmp_path / "bound"
    IsolatedProductRuntime(root, account_id="nexus-regime-demo:first").paper_snapshot()
    with pytest.raises(ProductRuntimeError, match="aggregate binding mismatch"):
        IsolatedProductRuntime(root, account_id="nexus-regime-demo:second")


def test_preparation_stops_before_risk_or_execution_then_existing_runtime_executes(tmp_path: Path, monkeypatch) -> None:
    now = _now_ms()
    monkeypatch.setattr(product_research, "KILL_CRITERIA", _permissive_kills())
    runtime, research = _research(tmp_path, now)
    result = research.run_research(
        symbol="BTCUSDT", timeframe="minute15", family="momentum", limit=180
    )
    assert result["qualification"]["status"] == "paper_candidate"
    assert result["latest_target"] == 1.0

    prepared = prepare_regime_paper_lane(research)
    assert prepared["status"] == "ready"
    assert prepared["lane_ready"] is True
    assert prepared["execution_performed"] is False
    assert prepared["paper_only"] is True
    assert prepared["live_trading_authority"] is False
    assert prepared["account_id"] == runtime.account_id
    assert prepared["lane"]["portfolio_state"].aggregate_id == runtime.account_id
    assert runtime.paper_snapshot()["session_signal_count"] == 0
    assert runtime.paper_snapshot()["account"]["positions"] == []

    selected_policy = policy()
    executed = run_regime_strategy_runtime(
        context=context("ALIGNED_UP"),
        candidates=[_candidate(prepared)],
        selector_policy=selected_policy,
        lanes=[prepared["lane"]],
        source_sha=SOURCE_SHA,
        occurred_at=product_research._utc_ms(now),
    )
    assert executed.evidence["deterministic_risk_final_authority"] is True
    assert executed.evidence["lanes"][0]["portfolio_id"] == runtime.account_id
    assert executed.pipelines[0].risk_decision.allowed is True
    assert executed.pipelines[0].execution is not None
    assert verify_runtime_evidence(executed.evidence)["decision"] == "pass"
    # The adapter and orchestration proof do not silently mutate the durable journal.
    assert runtime.paper_snapshot()["session_signal_count"] == 0


def test_preparation_preserves_cash_surface_for_no_signal(tmp_path: Path, monkeypatch) -> None:
    now = _now_ms()
    monkeypatch.setattr(product_research, "KILL_CRITERIA", _permissive_kills())
    runtime, research = _research(tmp_path, now)
    result = research.run_research(
        symbol="BTCUSDT", timeframe="minute15", family="momentum", limit=180
    )
    assert result["qualification"]["status"] == "paper_candidate"
    research._last_research["latest_target"] = 0.0

    prepared = prepare_regime_paper_lane(research)
    assert prepared["status"] == "no_open_signal"
    assert prepared["lane_ready"] is False
    assert prepared["lane"] is None
    assert prepared["execution_performed"] is False
    assert runtime.paper_snapshot()["session_signal_count"] == 0


def test_preparation_rejects_canonical_lineage_tamper_before_risk(tmp_path: Path, monkeypatch) -> None:
    now = _now_ms()
    monkeypatch.setattr(product_research, "KILL_CRITERIA", _permissive_kills())
    runtime, research = _research(tmp_path, now)
    research.run_research(
        symbol="BTCUSDT", timeframe="minute15", family="momentum", limit=180
    )
    research._last_research["_dataset"]["source_role"] = "secondary_validation"

    with pytest.raises(ProductResearchError, match="invalid canonical lineage"):
        prepare_regime_paper_lane(research)
    assert runtime.paper_snapshot()["session_signal_count"] == 0
