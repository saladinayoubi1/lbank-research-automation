from __future__ import annotations

from pathlib import Path

from nexus_demo_paper_position_maintenance import maintain_task_position
from nexus_paper_performance_pipeline import extract_closed_paper_trades
from product_runtime import ProductRuntime


NOW = "2026-08-25T04:00:00Z"
LAST_OPEN_MS = 1_756_092_600_000


def _runtime_with_position(tmp_path: Path) -> ProductRuntime:
    runtime = ProductRuntime(tmp_path / "paper", clock=lambda: NOW)
    result = runtime.submit_paper_order({
        "operation": "open",
        "symbol": "ETHUSDT",
        "timeframe": "hour4",
        "side": "long",
        "quantity": "1",
        "reference_price": "100",
        "stop_price": "98",
        "target_price": "103",
    })
    assert result["accepted"] is True
    assert result["account"]["positions"]
    return runtime


def _task(*, target: float = 0.0, qualification_status: str = "paper_candidate") -> dict:
    binding = "a" * 64
    return {
        "family": "trend_breakout",
        "research_result": {
            "request": {
                "symbol": "ETHUSDT",
                "timeframe": "hour4",
                "family": "trend_breakout",
            },
            "dataset": {
                "binding_sha256": binding,
                "last_open_time_ms": LAST_OPEN_MS,
                "last_close": "105",
            },
            "qualification": {
                "family": "trend_breakout",
                "status": qualification_status,
                "dataset_binding_sha256": binding,
                "strategy_version": "trend_breakout-product-v1",
            },
            "strategy_record": {
                "family": "trend_breakout",
                "record_digest": "b" * 64,
            },
            "latest_target": target,
        },
    }


def test_flat_target_closes_existing_position_and_produces_closed_trade(tmp_path: Path) -> None:
    runtime = _runtime_with_position(tmp_path)
    result = maintain_task_position(runtime=runtime, task=_task(target=0.0))

    assert result["status"] == "CLOSED"
    assert result["reason_code"] == "LATEST_TARGET_FLAT"
    assert result["risk_reason"] == "risk_reducing_exit"
    assert result["exposure_increased"] is False
    assert runtime.paper_snapshot()["account"]["positions"] == []

    events = runtime._read_events()
    assert any(
        event["event_type"] == "signal_recorded"
        and event["provenance"]["kind"] == "automatic"
        and event["provenance"]["source_id"] == "nexus-demo-position-maintenance"
        for event in events
    )
    trades = extract_closed_paper_trades(events)
    assert len(trades) == 1
    assert trades[0]["gross_pnl"] != "0"


def test_active_target_holds_without_writing_events(tmp_path: Path) -> None:
    runtime = _runtime_with_position(tmp_path)
    before = runtime._read_events()
    result = maintain_task_position(runtime=runtime, task=_task(target=1.0))
    after = runtime._read_events()

    assert result["status"] == "HELD"
    assert result["event_count_added"] == 0
    assert after == before
    assert runtime.paper_snapshot()["account"]["positions"]


def test_lost_qualification_forces_risk_reducing_close(tmp_path: Path) -> None:
    runtime = _runtime_with_position(tmp_path)
    result = maintain_task_position(
        runtime=runtime,
        task=_task(target=1.0, qualification_status="killed"),
    )

    assert result["status"] == "CLOSED"
    assert result["reason_code"] == "CURRENT_QUALIFICATION_NOT_PAPER_ELIGIBLE"
    assert result["risk_reason"] == "risk_reducing_exit"
    assert runtime.paper_snapshot()["account"]["positions"] == []


def test_maintenance_is_idempotent_after_close(tmp_path: Path) -> None:
    runtime = _runtime_with_position(tmp_path)
    first = maintain_task_position(runtime=runtime, task=_task(target=0.0))
    count = len(runtime._read_events())
    second = maintain_task_position(runtime=runtime, task=_task(target=0.0))

    assert first["status"] == "CLOSED"
    assert second["status"] == "FLAT"
    assert second["event_count_added"] == 0
    assert len(runtime._read_events()) == count
