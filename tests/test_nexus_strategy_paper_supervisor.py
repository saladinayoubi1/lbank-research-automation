from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time

import pytest

import product_research_runtime as product_research
from nexus_strategy_paper_supervisor import (
    StrategyPaperSupervisorError,
    run_once,
    verify_ledger,
)
from phase6_research_pipeline import bind_bybit_closed_dataset

STEP = 900_000
NOW = int(time.time() * 1000)
SOURCE_SHA = "a" * 40


def _dataset(count: int = 240, *, now_ms: int = NOW):
    end_open = ((now_ms - STEP) // STEP) * STEP
    start = end_open - (count - 1) * STEP
    candles = []
    for index in range(count):
        if index < count // 2:
            price = 120.0 - index * 0.25
        else:
            price = 90.0 + (index - count // 2) * 0.55
        candles.append({
            "source": "Bybit", "market_type": "spot", "symbol": "BTCUSDT",
            "interval": "15", "open_time_ms": start + index * STEP,
            "close_time_ms": start + (index + 1) * STEP - 1,
            "open": f"{price:.8f}", "high": f"{price * 1.01:.8f}",
            "low": f"{price * 0.99:.8f}", "close": f"{price:.8f}",
            "volume": "10", "turnover": f"{price * 10:.8f}", "closed": True,
        })
    return bind_bybit_closed_dataset(
        candles, canonical_symbol="BTC/USDT", source_symbol="BTCUSDT", interval="15"
    )


def _fetcher(**_):
    return deepcopy(_dataset())


def _permissive_kills():
    return {
        "min_robustness_score": -1.0,
        "max_cost_stress_loss_pct": 100.0,
        "min_walk_forward_score": -1.0,
        "min_oos_score": -1.0,
        "max_drawdown_pct": 100.0,
        "min_regime_pass_ratio": 0.0,
        "max_failure_mode_severity": 10.0,
    }


def test_supervisor_runs_each_family_as_fenced_verified_task(tmp_path: Path) -> None:
    ledger = run_once(
        source_sha=SOURCE_SHA,
        state_root=tmp_path,
        families=("momentum", "trend_breakout", "mean_reversion"),
        now_ms=NOW,
        dataset_fetcher=_fetcher,
    )

    assert ledger["final_status"] == "VERIFIED"
    assert ledger["paper_only"] is True
    assert ledger["live_trading_authority"] is False
    assert ledger["verification"]["decision"] == "pass"
    assert len(ledger["tasks"]) == 3
    assert len({row["lease_id"] for row in ledger["tasks"]}) == 3
    assert all(row["producer_result"]["outcome"] == "success" for row in ledger["tasks"])
    assert all(row["evidence_digest"] for row in ledger["tasks"])
    assert all(row["status"] in {
        "paper_executed", "qualification_killed", "no_open_signal",
        "position_exists", "risk_rejected",
    } for row in ledger["tasks"])
    assert (tmp_path / "supervisor-ledger.json").is_file()
    assert all((tmp_path / "evidence" / f"{family}.json").is_file() for family in (
        "momentum", "trend_breakout", "mean_reversion"
    ))


def test_candidate_crosses_real_deterministic_risk_into_isolated_paper(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(product_research, "KILL_CRITERIA", _permissive_kills())
    ledger = run_once(
        source_sha=SOURCE_SHA,
        state_root=tmp_path,
        families=("momentum",),
        now_ms=NOW,
        dataset_fetcher=_fetcher,
    )

    task = ledger["tasks"][0]
    assert task["research_result"]["qualification"]["status"] == "paper_candidate"
    assert task["status"] == "paper_executed"
    assert task["paper_result"]["risk"]["allowed"] is True
    assert task["paper_result"]["execution"]["event_count"] >= 1
    assert task["portfolio_snapshot"]["account"]["positions"][0]["symbol"] == "BTCUSDT"


def test_historical_replay_uses_one_clock_through_paper_execution(
    tmp_path: Path, monkeypatch
) -> None:
    historical_now = 1_700_000_000_000
    monkeypatch.setattr(product_research, "KILL_CRITERIA", _permissive_kills())
    ledger = run_once(
        source_sha=SOURCE_SHA,
        state_root=tmp_path,
        families=("momentum",),
        now_ms=historical_now,
        dataset_fetcher=lambda **_: deepcopy(_dataset(now_ms=historical_now)),
    )

    task = ledger["tasks"][0]
    assert task["status"] == "paper_executed"
    assert task["paper_result"]["risk"]["allowed"] is True
    assert task["paper_only"] is True
    assert task["live_trading_authority"] is False


def test_independent_verifier_rejects_live_authority_or_lease_spoof(tmp_path: Path) -> None:
    ledger = run_once(
        source_sha=SOURCE_SHA, state_root=tmp_path, families=("momentum",),
        now_ms=NOW, dataset_fetcher=_fetcher,
    )
    core = {key: value for key, value in ledger.items() if key not in {
        "verification", "final_status", "ledger_digest"
    }}
    core["tasks"][0]["live_trading_authority"] = True
    core["tasks"][0]["lease_id"] = "spoofed"
    assert verify_ledger(core)["decision"] == "reject"


def test_missing_public_dataset_fails_before_any_paper_state(tmp_path: Path) -> None:
    def unavailable(**_):
        raise OSError("network unavailable")

    with pytest.raises(StrategyPaperSupervisorError, match="dataset unavailable"):
        run_once(
            source_sha=SOURCE_SHA, state_root=tmp_path, families=("momentum",),
            now_ms=NOW, dataset_fetcher=unavailable,
        )
    assert not (tmp_path / "supervisor-ledger.json").exists()
    assert not (tmp_path / "portfolios").exists()


def test_restart_reuses_isolated_paper_state_without_duplicate_position(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(product_research, "KILL_CRITERIA", _permissive_kills())
    first = run_once(
        source_sha=SOURCE_SHA, state_root=tmp_path, families=("momentum",),
        now_ms=NOW, dataset_fetcher=_fetcher,
    )
    second = run_once(
        source_sha=SOURCE_SHA, state_root=tmp_path, families=("momentum",),
        now_ms=NOW, dataset_fetcher=_fetcher,
    )

    assert first["tasks"][0]["status"] == "paper_executed"
    assert second["tasks"][0]["status"] == "position_exists"
    assert len(second["tasks"][0]["portfolio_snapshot"]["account"]["positions"]) == 1
    assert second["verification"]["decision"] == "pass"
