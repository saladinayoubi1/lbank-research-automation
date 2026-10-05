from __future__ import annotations

from pathlib import Path

import pytest

from nexus_product_paper_protective_exit import (
    ProductPaperProtectiveExitError,
    evaluate_protective_exit,
)
from product_runtime import ProductRuntime


OPEN_AT = "2026-10-05T00:00:00Z"
CLOSE_MS = 1791160199999


def _runtime(tmp_path: Path, *, side: str = "long") -> ProductRuntime:
    runtime = ProductRuntime(tmp_path, opening_cash="500", clock=lambda: OPEN_AT)
    if side == "long":
        request = {
            "operation": "open", "symbol": "XRPUSDT", "timeframe": "minute15",
            "side": "long", "quantity": "0.4", "reference_price": "100",
            "stop_price": "95", "target_price": "110",
        }
    else:
        request = {
            "operation": "open", "symbol": "XRPUSDT", "timeframe": "minute15",
            "side": "short", "quantity": "0.4", "reference_price": "100",
            "stop_price": "105", "target_price": "90",
        }
    result = runtime.submit_paper_order(request)
    assert result["accepted"] is True
    return runtime


def _candle(*, high: str, low: str, source: str = "Bybit", closed: bool = True):
    return {
        "source": source, "market_type": "spot", "symbol": "XRPUSDT",
        "interval": "15", "open_time_ms": CLOSE_MS - 899_999,
        "close_time_ms": CLOSE_MS, "open": "100", "high": high,
        "low": low, "close": "100", "volume": "10", "turnover": "1000",
        "closed": closed,
    }


def test_guard_holds_when_neither_protection_level_is_touched(tmp_path: Path):
    runtime = _runtime(tmp_path)
    before = runtime.paper_snapshot()
    result = evaluate_protective_exit(
        runtime=runtime, candle=_candle(high="105", low="96"),
        symbol="XRPUSDT", timeframe="minute15",
        strategy_version="trend_breakout-product-v1",
    )
    after = runtime.paper_snapshot()
    assert result["status"] == "HELD"
    assert result["reason_code"] == "PROTECTION_NOT_TOUCHED"
    assert result["event_count_added"] == 0
    assert after["event_count"] == before["event_count"]
    assert len(after["account"]["positions"]) == 1
    assert result["paper_only"] is True
    assert result["live_trading_authority"] is False
    assert result["exposure_increased"] is False


def test_guard_closes_long_at_stop_with_automatic_provenance(tmp_path: Path):
    runtime = _runtime(tmp_path)
    result = evaluate_protective_exit(
        runtime=runtime, candle=_candle(high="104", low="94"),
        symbol="XRPUSDT", timeframe="minute15",
        strategy_version="trend_breakout-product-v1",
    )
    snapshot = runtime.paper_snapshot()
    events = runtime.paper_events(limit=100)["events"]
    assert result["status"] == "CLOSED"
    assert result["trigger"] == "STOP"
    assert result["reason_code"] == "STOP_TOUCHED"
    assert result["reference_price"] == "95"
    assert snapshot["account"]["positions"] == []
    protective = [e for e in events if e["provenance"]["source_id"] == "nexus-product-paper-protective-exit"]
    assert protective
    assert all(e["provenance"]["kind"] == "automatic" for e in protective)
    assert all(e["provenance"]["strategy_version"] == "trend_breakout-product-v1" for e in protective)
    assert result["risk_reason"] == "risk_reducing_exit"
    assert result["live_trading_authority"] is False
    assert result["exposure_increased"] is False


def test_guard_closes_long_at_target(tmp_path: Path):
    runtime = _runtime(tmp_path)
    result = evaluate_protective_exit(
        runtime=runtime, candle=_candle(high="111", low="96"),
        symbol="XRPUSDT", timeframe="minute15",
        strategy_version="trend_breakout-product-v1",
    )
    assert result["status"] == "CLOSED"
    assert result["trigger"] == "TARGET"
    assert result["reason_code"] == "TARGET_TOUCHED"
    assert result["reference_price"] == "110"
    assert runtime.paper_snapshot()["account"]["positions"] == []


def test_same_candle_stop_and_target_uses_conservative_stop_first(tmp_path: Path):
    runtime = _runtime(tmp_path)
    result = evaluate_protective_exit(
        runtime=runtime, candle=_candle(high="111", low="94"),
        symbol="XRPUSDT", timeframe="minute15",
        strategy_version="trend_breakout-product-v1",
    )
    assert result["status"] == "CLOSED"
    assert result["trigger"] == "STOP"
    assert result["reason_code"] == "STOP_AND_TARGET_TOUCHED_STOP_FIRST"
    assert result["reference_price"] == "95"


@pytest.mark.parametrize(
    ("high", "low", "expected_trigger", "expected_reference"),
    [("106", "95", "STOP", "105"), ("104", "89", "TARGET", "90")],
)
def test_short_position_protection_is_directionally_correct(
    tmp_path: Path, high: str, low: str, expected_trigger: str, expected_reference: str
):
    runtime = _runtime(tmp_path, side="short")
    result = evaluate_protective_exit(
        runtime=runtime, candle=_candle(high=high, low=low),
        symbol="XRPUSDT", timeframe="minute15",
        strategy_version="trend_breakout-product-v1",
    )
    assert result["status"] == "CLOSED"
    assert result["trigger"] == expected_trigger
    assert result["reference_price"] == expected_reference
    assert runtime.paper_snapshot()["account"]["positions"] == []


@pytest.mark.parametrize(
    "candle",
    [
        _candle(high="105", low="96", source="Bitget"),
        _candle(high="105", low="96", closed=False),
        {**_candle(high="105", low="96"), "interval": "60"},
        {**_candle(high="105", low="96"), "symbol": "BTCUSDT"},
        {**_candle(high="90", low="96")},
    ],
)
def test_guard_rejects_unverified_or_mismatched_candle_evidence(tmp_path: Path, candle):
    runtime = _runtime(tmp_path)
    with pytest.raises(ProductPaperProtectiveExitError):
        evaluate_protective_exit(
            runtime=runtime, candle=candle, symbol="XRPUSDT", timeframe="minute15",
            strategy_version="trend_breakout-product-v1",
        )
    assert len(runtime.paper_snapshot()["account"]["positions"]) == 1


def test_guard_is_flat_idempotent_after_close(tmp_path: Path):
    runtime = _runtime(tmp_path)
    candle = _candle(high="104", low="94")
    first = evaluate_protective_exit(
        runtime=runtime, candle=candle, symbol="XRPUSDT", timeframe="minute15",
        strategy_version="trend_breakout-product-v1",
    )
    second = evaluate_protective_exit(
        runtime=runtime, candle=candle, symbol="XRPUSDT", timeframe="minute15",
        strategy_version="trend_breakout-product-v1",
    )
    assert first["status"] == "CLOSED"
    assert second["status"] == "FLAT"
    assert second["event_count_added"] == 0
