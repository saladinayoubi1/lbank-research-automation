from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import nexus_paper_performance_pipeline as pipeline
from nexus_paper_performance_pipeline import (
    PaperPerformancePipelineError,
    build_paper_performance_projection,
    extract_closed_paper_trades,
    save_paper_performance_projection,
)
from paper_event_store import GENESIS_DIGEST, build_event


def _journal(*, reduced: bool = False):
    events = []
    previous = GENESIS_DIGEST

    def append(kind, at, correlation, payload):
        nonlocal previous
        event = build_event(
            event_id=f"event-{len(events) + 1}", event_type=kind,
            aggregate_id="paper-momentum", sequence=len(events) + 1,
            occurred_at=at, correlation_id=correlation,
            causation_id=f"cause-{len(events) + 1}",
            provenance={
                "kind": "automatic", "source_id": "strategy-supervisor",
                "source_timestamp": at, "received_timestamp": at,
                "timeframe": "minute15", "confidence": "1",
                "strategy_version": "momentum-v1", "policy_version": "paper-v1",
            },
            previous_event_digest=previous, payload=payload,
        )
        previous = event["event_digest"]
        events.append(event)

    append("demo_account_opened", "2026-08-25T00:00:00Z", "account", {
        "currency": "USDT", "opening_cash": "10000",
    })
    append("position_opened", "2026-08-25T00:01:00Z", "open-1", {
        "symbol": "BTCUSDT", "side": "long", "quantity": "1", "entry_price": "100",
    })
    append("fee_recorded", "2026-08-25T00:01:01Z", "open-1", {
        "amount": "0.10", "currency": "USDT",
    })
    append("slippage_recorded", "2026-08-25T00:01:02Z", "open-1", {
        "amount": "0.05", "currency": "USDT",
    })
    if reduced:
        append("position_reduced", "2026-08-25T00:05:00Z", "reduce-1", {
            "symbol": "BTCUSDT", "quantity": "0.5", "exit_price": "105",
            "realized_pnl": "2.5",
        })
    append("position_closed", "2026-08-25T00:10:00Z", "close-1", {
        "symbol": "BTCUSDT", "exit_price": "110", "realized_pnl": "10",
    })
    append("fee_recorded", "2026-08-25T00:10:01Z", "close-1", {
        "amount": "0.11", "currency": "USDT",
    })
    append("slippage_recorded", "2026-08-25T00:10:02Z", "close-1", {
        "amount": "0.05", "currency": "USDT",
    })
    return events


def test_extracts_closed_trade_with_correlated_costs() -> None:
    trades = extract_closed_paper_trades(_journal())
    assert len(trades) == 1
    assert trades[0]["gross_pnl"] == "10"
    assert trades[0]["fees"] == "0.31"
    assert trades[0]["entry_notional"] == "100"
    assert trades[0]["exit_notional"] == "110"
    assert trades[0]["closed_at_ms"] > trades[0]["opened_at_ms"]


def test_tampered_or_ambiguous_journal_fails_closed() -> None:
    tampered = deepcopy(_journal())
    tampered[-1]["payload"]["amount"] = "99"
    with pytest.raises(PaperPerformancePipelineError, match="failed replay"):
        extract_closed_paper_trades(tampered)
    with pytest.raises(PaperPerformancePipelineError, match="partial reductions"):
        extract_closed_paper_trades(_journal(reduced=True))


def test_verified_projection_is_paper_only_and_persisted(tmp_path: Path, monkeypatch) -> None:
    ledger = {
        "tasks": [{"task_id": "task-1", "family": "momentum", "status": "paper_executed"}]
    }
    monkeypatch.setattr(pipeline, "verify_ledger", lambda _ledger: {
        "decision": "pass", "verification_digest": "v" * 64,
    })
    monkeypatch.setattr(pipeline, "evaluate_paper_drift", lambda **_kwargs: {
        "strategy_id": "strategy-1", "status": "HEALTHY", "lifecycle_state": "PAPER",
        "closed_trade_count": 5,
        "analytics": {"expectancy": "2", "max_drawdown_pct": "1", "net_pnl": "10"},
        "monitor_digest": "m" * 64,
    })
    projection = build_paper_performance_projection(
        supervisor_ledger=ledger, journals_by_family={"momentum": _journal()},
        baselines_by_family={"momentum": {"expectancy": "2", "fee_per_trade": "0.31"}},
    )
    assert projection["paper_only"] is True
    assert projection["live_trading_authority"] is False
    assert projection["strategies"][0]["max_drawdown_pct"] == "1"
    target = tmp_path / "mission-control" / "paper-performance.json"
    save_paper_performance_projection(target, projection)
    assert target.exists()


def test_projection_rejects_unverified_or_missing_inputs(monkeypatch) -> None:
    ledger = {
        "tasks": [{"task_id": "task-1", "family": "momentum", "status": "paper_executed"}]
    }
    monkeypatch.setattr(pipeline, "verify_ledger", lambda _ledger: {"decision": "fail"})
    with pytest.raises(PaperPerformancePipelineError, match="not verified"):
        build_paper_performance_projection(
            supervisor_ledger=ledger, journals_by_family={}, baselines_by_family={},
        )
