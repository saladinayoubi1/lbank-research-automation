from __future__ import annotations

import json
from pathlib import Path

import pytest

from product_runtime import ProductRuntime, ProductRuntimeError


def order(**overrides):
    value = {
        "operation": "open",
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
        "side": "long",
        "quantity": "0.001",
        "reference_price": "60000",
        "stop_price": "59000",
        "target_price": "62000",
    }
    value.update(overrides)
    return value


def test_product_runtime_bootstraps_real_replayable_paper_account(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path)
    snapshot = runtime.paper_snapshot()
    assert snapshot["paper_only"] is True
    assert snapshot["live_trading_authority"] is False
    assert snapshot["account"]["cash"] == "10000"
    assert snapshot["account"]["equity"] == "10000"
    assert snapshot["account"]["session_open"] is True
    assert snapshot["event_count"] == 2
    journal = runtime.paper_events()
    assert [event["event_type"] for event in journal["events"]] == [
        "demo_account_opened",
        "session_boundary_recorded",
    ]


def test_product_runtime_executes_open_through_deterministic_risk(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path)
    result = runtime.submit_paper_order(order())
    assert result["accepted"] is True
    assert result["risk"]["allowed"] is True
    assert result["risk"]["reason_code"] == "risk_allowed"
    assert result["execution"]["event_count"] >= 7
    snapshot = runtime.paper_snapshot()
    assert snapshot["account"]["positions"][0]["symbol"] == "BTCUSDT"
    assert snapshot["account"]["positions"][0]["side"] == "long"
    assert snapshot["account"]["equity"] != "10000"


def test_product_runtime_can_close_only_as_risk_reducing_paper_action(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path)
    opened = runtime.submit_paper_order(order())
    assert opened["accepted"] is True
    closed = runtime.submit_paper_order(order(
        operation="close",
        reference_price="61000",
        stop_price="59000",
        target_price="62000",
    ))
    assert closed["accepted"] is True
    assert closed["risk"]["reason_code"] == "risk_reducing_exit"
    assert closed["account"]["positions"] == []


def test_product_runtime_rejects_oversized_open_at_risk_gate(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path)
    result = runtime.submit_paper_order(order(quantity="1"))
    assert result["accepted"] is False
    assert result["risk"]["allowed"] is False
    assert result["risk"]["reason_code"] in {"position_size_limit", "aggregate_exposure_limit"}
    assert runtime.paper_snapshot()["account"]["positions"] == []


def test_product_runtime_has_no_live_order_authority(tmp_path: Path) -> None:
    surface = ProductRuntime(tmp_path).live_surface()
    assert surface["status"] == "locked_owner_controlled"
    assert surface["enabled"] is False
    assert surface["live_trading_authority"] is False
    assert surface["exchange_credentials_configured"] is False
    assert surface["orders_allowed"] is False
    assert surface["withdrawals_allowed"] is False


def test_product_runtime_fails_closed_on_corrupt_journal(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path)
    runtime.paper_snapshot()
    runtime.paper_events_path.write_text('{"broken":true}\n', encoding="utf-8")
    with pytest.raises(ProductRuntimeError, match="corrupt"):
        runtime.paper_snapshot()
    assert json.loads(runtime.paper_events_path.read_text(encoding="utf-8"))["broken"] is True


def test_product_runtime_rejects_unknown_or_extra_order_fields(tmp_path: Path) -> None:
    runtime = ProductRuntime(tmp_path)
    with pytest.raises(ProductRuntimeError, match="schema mismatch"):
        runtime.submit_paper_order({**order(), "live": True})
    with pytest.raises(ProductRuntimeError, match="unsupported paper symbol"):
        runtime.submit_paper_order(order(symbol="UNKNOWNUSDT"))
