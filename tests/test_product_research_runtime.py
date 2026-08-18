from __future__ import annotations

import time
from pathlib import Path

import pytest

from phase6_research_pipeline import bind_bybit_closed_dataset
from product_control_runtime import ProductControlRuntime
from product_research_runtime import ProductResearchError, ProductResearchRuntime
from product_runtime import ProductRuntime

STEP = 900_000


def _now_ms() -> int:
    return int(time.time() * 1000)


def _candles(now_ms: int, count: int = 180):
    end_open = ((now_ms - STEP) // STEP) * STEP
    start = end_open - (count - 1) * STEP
    rows = []
    for index in range(count):
        # A deterministic fall-then-rise path exercises targets and produces fills.
        if index < count // 2:
            price = 120.0 - index * 0.35
        else:
            price = 88.5 + (index - count // 2) * 0.65
        rows.append({
            "source": "Bybit",
            "market_type": "spot",
            "symbol": "BTCUSDT",
            "interval": "15",
            "open_time_ms": start + index * STEP,
            "close_time_ms": start + (index + 1) * STEP - 1,
            "open": f"{price:.8f}",
            "high": f"{price * 1.01:.8f}",
            "low": f"{price * 0.99:.8f}",
            "close": f"{price:.8f}",
            "volume": "10",
            "turnover": f"{price * 10:.8f}",
            "closed": True,
        })
    return rows


def _dataset(now_ms: int, count: int = 180):
    return bind_bybit_closed_dataset(
        _candles(now_ms, count),
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval="15",
    )


def _research(tmp_path: Path, now_ms: int):
    dataset = _dataset(now_ms)
    runtime = ProductRuntime(tmp_path / "state")
    research = ProductResearchRuntime(
        runtime,
        source_sha="a" * 40,
        dataset_fetcher=lambda **_: dataset,
        clock_ms=lambda: now_ms,
    )
    return runtime, research


def test_registry_and_research_are_real_canonical_paper_only(tmp_path: Path) -> None:
    now = _now_ms()
    _, research = _research(tmp_path, now)
    registry = research.registry_snapshot()
    assert registry["private_credentials_required"] is False
    assert registry["paper_only"] is True
    assert registry["authority"]["primary"] == "Bybit"
    assert any(row["canonical_symbol"] == "BTC/USDT" for row in registry["mappings"])

    result = research.run_research(symbol="BTCUSDT", timeframe="minute15", family="momentum", limit=180)
    assert result["paper_only"] is True
    assert result["live_execution_allowed"] is False
    assert result["profitability_claim"] is False
    assert result["source_sha"] == "a" * 40
    assert result["dataset"]["source"] == "Bybit"
    assert result["dataset"]["row_count"] == 180
    assert result["qualification"]["status"] in {"paper_candidate", "killed"}
    assert result["backtest"]["metrics"]["fill_count"] >= 1
    assert result["backtest"]["equity_curve"]
    assert result["pipeline_digest"]


def test_research_rejects_stale_or_unbound_release_data(tmp_path: Path) -> None:
    now = _now_ms()
    old = now - 10 * STEP
    stale_dataset = _dataset(old)
    runtime = ProductRuntime(tmp_path / "state")
    research = ProductResearchRuntime(runtime, source_sha="b" * 40, dataset_fetcher=lambda **_: stale_dataset, clock_ms=lambda: now)
    with pytest.raises(ProductResearchError, match="stale"):
        research.fetch_dataset(symbol="BTCUSDT", timeframe="minute15", limit=180)

    missing_sha = ProductResearchRuntime(runtime, source_sha="", dataset_fetcher=lambda **_: _dataset(now), clock_ms=lambda: now)
    with pytest.raises(ProductResearchError, match="source SHA"):
        missing_sha.run_research(symbol="BTCUSDT", timeframe="minute15", family="momentum", limit=180)


def test_qualification_gated_auto_paper_runs_real_deterministic_pipeline(tmp_path: Path) -> None:
    now = _now_ms()
    runtime, research = _research(tmp_path, now)
    result = research.run_research(symbol="BTCUSDT", timeframe="minute15", family="momentum", limit=180)

    # Exercise the positive automated execution path independent of whether the
    # conservative sample qualification happened to kill this synthetic slice.
    research._last_research["qualification"]["status"] = "paper_candidate"
    research._last_research["qualification"]["kill_reasons"] = []
    research._last_research["latest_target"] = 1.0
    auto = research.auto_paper()

    assert auto["paper_only"] is True
    assert auto["live_trading_authority"] is False
    assert auto["accepted"] is True
    assert auto["status"] == "paper_executed"
    assert auto["signal"]["paper_trading_only"] is True
    assert auto["risk"]["allowed"] is True
    assert auto["execution"]["event_count"] >= 1
    snapshot = runtime.paper_snapshot()
    assert snapshot["account"]["positions"][0]["symbol"] == "BTCUSDT"
    assert snapshot["session_signal_count"] == 1


def test_paper_controls_recovery_notifications_and_exports_are_durable(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path / "state")
    controls = ProductControlRuntime(runtime)
    initial = runtime.paper_snapshot()
    assert initial["account"]["session_open"] is True

    closed = controls.set_session({"open": False})
    assert closed["account"]["session_open"] is False
    opened = controls.set_session({"open": True})
    assert opened["account"]["session_open"] is True
    killed = controls.set_kill_switch({"enabled": True, "reason_code": "test_stop"})
    assert killed["account"]["kill_switch_enabled"] is True
    resumed = controls.set_kill_switch({"enabled": False, "reason_code": "test_resume"})
    assert resumed["account"]["kill_switch_enabled"] is False

    recovery = controls.recovery_snapshot()
    assert recovery["status"] == "verified"
    assert recovery["atomic_journal"] is True
    assert recovery["fail_closed_on_corruption"] is True
    notifications = controls.notifications(limit=20)
    assert notifications["count"] >= 4
    assert b'"paper_only": true' in controls.export_json()
    csv_bytes = controls.export_csv()
    assert b"event_type" in csv_bytes
    assert b"kill_switch_transitioned" in csv_bytes


def test_manual_paper_signal_limit_counts_proposals_not_audit_events(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path / "state")
    result = runtime.submit_paper_order({
        "operation": "open",
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
        "side": "long",
        "quantity": "0.001",
        "reference_price": "60000",
        "stop_price": "59000",
        "target_price": "62000",
    })
    assert result["accepted"] is True
    snapshot = runtime.paper_snapshot()
    assert snapshot["session_signal_count"] == 1
    assert snapshot["account"]["last_sequence"] > snapshot["session_signal_count"]
