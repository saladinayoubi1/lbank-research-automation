from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import nexus_demo_regime_cycle as regime_cycle
from nexus_demo_regime_cycle import (
    CELL_SCHEMA,
    SCHEMA,
    DemoRegimeCycleError,
    _append_events_once,
    _common_as_of,
    _digest,
    build_synchronized_context,
    verify_cycle_snapshot,
)
from nexus_isolated_product_runtime import IsolatedProductRuntime, regime_paper_account_id
from paper_event_store import build_event
from phase6_research_pipeline import bind_bybit_closed_dataset
from product_runtime import _paper_provenance


AS_OF_MS = 1_728_000_000_000  # exactly aligned to a 4h boundary
SOURCE_SHA = "a" * 40
_INTERVAL_STEP = {"15": 900_000, "60": 3_600_000, "240": 14_400_000}


def _archive_fetcher(**kwargs):
    interval = str(kwargs["interval"])
    step = _INTERVAL_STEP[interval]
    start = int(kwargs["start_time_ms"])
    end = int(kwargs["end_time_ms"])
    now = int(kwargs["now_ms"])
    limit = int(kwargs["limit"])
    assert end + step <= now
    opens = list(range(start, end + 1, step))
    assert len(opens) == limit
    candles = []
    for index, open_ms in enumerate(opens):
        price = 100.0 + index
        candles.append({
            "source": "Bybit",
            "market_type": "spot",
            "symbol": kwargs["source_symbol"],
            "interval": interval,
            "open_time_ms": open_ms,
            "close_time_ms": open_ms + step - 1,
            "open": f"{price:.8f}",
            "high": f"{price * 1.001:.8f}",
            "low": f"{price * 0.999:.8f}",
            "close": f"{price:.8f}",
            "volume": "10",
            "turnover": f"{price * 10:.8f}",
            "closed": True,
        })
    return bind_bybit_closed_dataset(
        candles,
        canonical_symbol=kwargs["canonical_symbol"],
        source_symbol=kwargs["source_symbol"],
        interval=interval,
    )


def _cell(symbol: str, timeframe: str) -> dict:
    core = {
        "schema_version": CELL_SCHEMA,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_sha": SOURCE_SHA,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "cell_digest": _digest(core)}


def _snapshot() -> dict:
    cells = [
        _cell(symbol, timeframe)
        for symbol in ("BTCUSDT", "ETHUSDT")
        for timeframe in ("minute15", "hour1", "hour4")
    ]
    core = {
        "schema_version": SCHEMA,
        "matrix_id": "nexus-demo-btc-eth-3tf-3strategy-v1",
        "source_sha": SOURCE_SHA,
        "archive_sha256": "b" * 64,
        "context_digests": {"BTCUSDT": "c" * 64, "ETHUSDT": "d" * 64},
        "expected_cell_count": 6,
        "verified_cell_count": 6,
        "cells": cells,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "frozen_prospective_hour4_lane_mutated": False,
    }
    return {**core, "cycle_digest": _digest(core)}


def test_common_cursor_is_the_verified_hour4_close_and_fails_closed() -> None:
    state = {
        "cells": {
            "BTCUSDT:hour4": {
                "status": "VERIFIED",
                "last_completed_open_ms": AS_OF_MS - 14_400_000,
            }
        }
    }
    assert _common_as_of(state, "BTCUSDT") == AS_OF_MS

    blocked = deepcopy(state)
    blocked["cells"]["BTCUSDT:hour4"]["status"] = "BLOCKED"
    with pytest.raises(DemoRegimeCycleError, match="hour4 matrix cell"):
        _common_as_of(blocked, "BTCUSDT")


def test_synchronized_context_uses_closed_15m_1h_4h_windows_only() -> None:
    context, datasets = build_synchronized_context(
        fetcher=_archive_fetcher,
        symbol="BTCUSDT",
        as_of_ms=AS_OF_MS,
        history_limit=60,
    )

    assert context["instrument"] == "BTC/USDT"
    assert context["alignment"] == "ALIGNED_UP"
    assert [row["timeframe"] for row in context["timeframes"]] == ["15m", "1h", "4h"]
    assert all(row["available_at_ms"] <= AS_OF_MS for row in context["timeframes"])
    assert datasets["minute15"]["rows"][-1]["open_time_ms"] + 900_000 == AS_OF_MS
    assert datasets["hour1"]["rows"][-1]["open_time_ms"] + 3_600_000 == AS_OF_MS
    assert datasets["hour4"]["rows"][-1]["open_time_ms"] + 14_400_000 == AS_OF_MS


def test_ready_proposal_must_match_synchronized_context_dataset(monkeypatch, tmp_path: Path) -> None:
    class DummyResearch:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_research(self, **_kwargs):
            return {"qualification": {"strategy_version": "momentum-product-v1"}}

    monkeypatch.setattr(regime_cycle, "_runtime_for", lambda **_kwargs: object())
    monkeypatch.setattr(regime_cycle, "ProductResearchRuntime", DummyResearch)
    monkeypatch.setattr(
        regime_cycle,
        "prepare_regime_paper_lane",
        lambda _research: {
            "status": "ready",
            "preparation_digest": "c" * 64,
            "account_id": "nexus-demo-regime-btc-minute15-momentum",
            "lane_ready": True,
            "execution_performed": False,
            "dataset_binding_sha256": "b" * 64,
            "strategy_version": "momentum-product-v1",
            "lane": {"family": "momentum"},
        },
    )
    health_rows = {
        "momentum": {
            "strategy_version": "momentum-product-v1",
            "health_state": "HEALTHY",
            "record_digest": "d" * 64,
            "health_digest": "e" * 64,
        }
    }

    with pytest.raises(DemoRegimeCycleError, match="not bound to synchronized"):
        regime_cycle._prepare_candidates_and_lanes(
            state_root=tmp_path,
            source_sha=SOURCE_SHA,
            symbol="BTCUSDT",
            timeframe="minute15",
            as_of_ms=AS_OF_MS,
            history_limit=60,
            fetcher=_archive_fetcher,
            health_rows=health_rows,
            expected_dataset_binding="a" * 64,
        )


def test_restart_reconciliation_appends_paper_events_exactly_once(tmp_path: Path) -> None:
    at = "2024-10-04T00:00:00Z"
    account_id = regime_paper_account_id(
        symbol="BTCUSDT", timeframe="minute15", family="momentum"
    )
    runtime = IsolatedProductRuntime(
        tmp_path / "paper",
        account_id=account_id,
        clock=lambda: at,
    )
    existing = runtime._ensure_account()
    provenance = _paper_provenance(timeframe="minute15", at=at)
    signal = build_event(
        event_id="regime-cycle-test:signal",
        event_type="signal_recorded",
        aggregate_id=account_id,
        sequence=3,
        occurred_at=at,
        correlation_id="regime-cycle-test",
        causation_id="regime-cycle-test:proposal",
        provenance=provenance,
        previous_event_digest=existing[-1]["event_digest"],
        payload={
            "symbol": "BTCUSDT",
            "timeframe": "minute15",
            "side": "long",
            "quantity": "1",
            "reference_price": "100",
        },
    )
    rejection = build_event(
        event_id="regime-cycle-test:risk-reject",
        event_type="risk_rejection_recorded",
        aggregate_id=account_id,
        sequence=4,
        occurred_at=at,
        correlation_id="regime-cycle-test",
        causation_id=signal["event_id"],
        provenance=provenance,
        previous_event_digest=signal["event_digest"],
        payload={"reason_code": "test_fail_closed"},
    )

    _append_events_once(runtime, [signal, rejection])
    first = runtime._read_events()
    _append_events_once(runtime, [signal, rejection])
    second = runtime._read_events()

    assert len(first) == 4
    assert second == first
    assert second[-1]["event_digest"] == rejection["event_digest"]


def test_cycle_snapshot_is_digest_bound_and_preserves_authority() -> None:
    snapshot = _snapshot()
    assert verify_cycle_snapshot(snapshot)["decision"] == "pass"

    tampered = deepcopy(snapshot)
    tampered["cells"][0]["live_trading_authority"] = True
    assert verify_cycle_snapshot(tampered)["decision"] == "reject"

    tampered = deepcopy(snapshot)
    tampered["frozen_prospective_hour4_lane_mutated"] = True
    assert verify_cycle_snapshot(tampered)["decision"] == "reject"


def _health_inputs(
    *,
    supervisor_status: str = "no_open_signal",
    performance_status: str = "HEALTHY",
    lifecycle_state: str = "PAPER",
    task_family: str = "momentum",
    performance_family: str = "momentum",
    task_strategy_id: str = "momentum-canonical-v1",
    performance_strategy_id: str = "momentum-canonical-v1",
) -> tuple[dict, dict]:
    ledger = {
        "tasks": [{
            "family": task_family,
            "status": supervisor_status,
            "research_result": {
                "strategy_record": {
                    "strategy_id": task_strategy_id,
                    "family": task_family,
                    "record_digest": "d" * 64,
                },
                "qualification": {
                    "family": task_family,
                    "strategy_version": "momentum-product-v1",
                },
            },
        }]
    }
    performance = {
        "strategies": [{
            "family": performance_family,
            "strategy_id": performance_strategy_id,
            "status": performance_status,
            "lifecycle_state": lifecycle_state,
            "monitor_digest": "e" * 64,
        }]
    }
    return ledger, performance


def test_flat_no_open_signal_with_bound_paper_evidence_is_eligible() -> None:
    ledger, performance = _health_inputs()

    eligible = regime_cycle._eligible_health_rows(ledger, performance)

    assert eligible == {
        "momentum": {
            "family": "momentum",
            "canonical_strategy_id": "momentum-canonical-v1",
            "strategy_version": "momentum-product-v1",
            "record_digest": "d" * 64,
            "health_state": "HEALTHY",
            "health_digest": "e" * 64,
            "lifecycle_state": "PAPER",
        }
    }


def test_flat_no_open_signal_still_rejects_strategy_identity_substitution() -> None:
    ledger, performance = _health_inputs(
        performance_strategy_id="substituted-strategy-v1"
    )

    with pytest.raises(DemoRegimeCycleError, match="identity substitution"):
        regime_cycle._eligible_health_rows(ledger, performance)


def test_unrecognized_supervisor_status_remains_fail_closed() -> None:
    ledger, performance = _health_inputs(supervisor_status="paused")

    with pytest.raises(DemoRegimeCycleError, match="active verified Supervisor evidence"):
        regime_cycle._eligible_health_rows(ledger, performance)


def test_flat_insufficient_evidence_cannot_become_selector_health() -> None:
    ledger, performance = _health_inputs(performance_status="INSUFFICIENT_EVIDENCE")

    assert regime_cycle._eligible_health_rows(ledger, performance) == {}


def test_performance_projection_authority_remains_paper_only() -> None:
    verification_digest = "f" * 64
    core = {
        "contract_version": "nexus.mission-control.paper-performance.v1",
        "supervisor_verification_digest": verification_digest,
        "paper_only": True,
        "live_trading_authority": False,
        "strategy_count": 0,
        "status_counts": {},
        "strategies": [],
    }
    projection = {**core, "projection_digest": _digest(core)}
    assert regime_cycle._validate_performance_projection(
        projection, verification_digest
    )["live_trading_authority"] is False

    live_core = {**core, "live_trading_authority": True}
    live_projection = {**live_core, "projection_digest": _digest(live_core)}
    with pytest.raises(DemoRegimeCycleError, match="verification failed"):
        regime_cycle._validate_performance_projection(live_projection, verification_digest)
