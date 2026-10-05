from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nexus_product_paper_protective_exit_loop import (
    ProductPaperProtectiveExitLoopError,
    run_cycle,
)
from product_runtime import ProductRuntime


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp() * 1000)


OPEN_AT = "2026-10-05T00:00:00Z"
STEP = 15 * 60 * 1000


def _open_runtime(tmp_path: Path) -> ProductRuntime:
    runtime = ProductRuntime(tmp_path, opening_cash="500", clock=lambda: OPEN_AT)
    result = runtime.submit_paper_order({
        "operation": "open", "symbol": "XRPUSDT", "timeframe": "minute15",
        "side": "long", "quantity": "0.4", "reference_price": "100",
        "stop_price": "95", "target_price": "110",
    })
    assert result["accepted"] is True
    return runtime


def _row(open_ms: int, *, high: str = "105", low: str = "96"):
    return {
        "source": "Bybit", "market_type": "spot", "symbol": "XRPUSDT",
        "interval": "15", "open_time_ms": open_ms, "close_time_ms": open_ms + STEP - 1,
        "open": "100", "high": high, "low": low, "close": "100",
        "volume": "10", "turnover": "1000", "closed": True,
    }


def _fetcher(rows_by_open, calls):
    def fetch(symbol, interval, **kwargs):
        calls.append({"symbol": symbol, "interval": interval, **kwargs})
        start, end = kwargs["start_time_ms"], kwargs["end_time_ms"]
        return [rows_by_open[t] for t in range(start, end + 1, STEP)]
    return fetch


def test_flat_account_creates_truthful_idle_cursor(tmp_path: Path):
    cursor = tmp_path / "guard" / "cursor.json"
    result = run_cycle(root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:31:00Z"))
    assert result["status"] == "FLAT"
    assert result["checked_position_count"] == 0
    assert result["paper_only"] is True
    assert result["live_trading_authority"] is False
    assert json.loads(cursor.read_text())["positions"] == {}


def test_cycle_replays_closed_candles_and_closes_on_later_stop(tmp_path: Path):
    runtime = _open_runtime(tmp_path)
    cursor = tmp_path / "guard" / "cursor.json"
    start = _ms(OPEN_AT)
    rows = {
        start: _row(start, high="105", low="96"),
        start + STEP: _row(start + STEP, high="104", low="94"),
    }
    calls = []
    result = run_cycle(
        root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:31:00Z"),
        fetcher=_fetcher(rows, calls),
    )
    assert result["status"] == "CLOSED"
    assert [x["status"] for x in result["results"]] == ["HELD", "CLOSED"]
    assert result["results"][-1]["trigger"] == "STOP"
    assert calls[0]["limit"] == 2
    assert runtime.paper_snapshot()["account"]["positions"] == []


def test_cursor_skips_already_processed_closed_candle(tmp_path: Path):
    _open_runtime(tmp_path)
    cursor = tmp_path / "guard" / "cursor.json"
    start = _ms(OPEN_AT)
    rows = {
        start: _row(start),
        start + STEP: _row(start + STEP),
    }
    calls = []
    fetch = _fetcher(rows, calls)
    first = run_cycle(
        root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:16:00Z"), fetcher=fetch,
    )
    second = run_cycle(
        root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:31:00Z"), fetcher=fetch,
    )
    assert first["status"] == "ACTIVE"
    assert second["status"] == "ACTIVE"
    assert calls[0]["start_time_ms"] == start
    assert calls[0]["end_time_ms"] == start
    assert calls[1]["start_time_ms"] == start + STEP
    assert calls[1]["end_time_ms"] == start + STEP


def test_waits_when_no_complete_post_entry_candle_exists(tmp_path: Path):
    _open_runtime(tmp_path)
    cursor = tmp_path / "guard" / "cursor.json"
    result = run_cycle(
        root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:00:10Z"),
        fetcher=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("fetch should not run")),
    )
    assert result["status"] == "ACTIVE"
    assert result["results"][0]["status"] == "WAITING_FOR_FULL_CLOSED_CANDLE"


def test_new_position_digest_resets_cursor_for_same_symbol(tmp_path: Path):
    runtime = _open_runtime(tmp_path)
    cursor = tmp_path / "guard" / "cursor.json"
    start = _ms(OPEN_AT)
    calls = []
    run_cycle(
        root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:16:00Z"),
        fetcher=_fetcher({start: _row(start)}, calls),
    )
    close = runtime.submit_paper_order({
        "operation": "close", "symbol": "XRPUSDT", "timeframe": "minute15",
        "side": "long", "quantity": "0.4", "reference_price": "101",
        "stop_price": "101", "target_price": "101",
    })
    assert close["accepted"] is True
    runtime.clock = lambda: "2026-10-05T00:20:00Z"
    reopened = runtime.submit_paper_order({
        "operation": "open", "symbol": "XRPUSDT", "timeframe": "minute15",
        "side": "long", "quantity": "0.3", "reference_price": "100",
        "stop_price": "95", "target_price": "110",
    })
    assert reopened["accepted"] is True
    new_open = _ms("2026-10-05T00:30:00Z")
    later_calls = []
    result = run_cycle(
        root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:46:00Z"),
        fetcher=_fetcher({new_open: _row(new_open)}, later_calls),
    )
    assert result["status"] == "ACTIVE"
    assert later_calls[0]["start_time_ms"] == new_open


def test_incomplete_or_discontinuous_fetch_fails_closed(tmp_path: Path):
    _open_runtime(tmp_path)
    cursor = tmp_path / "guard" / "cursor.json"
    start = _ms(OPEN_AT)

    def bad_fetch(*args, **kwargs):
        return [_row(start + STEP)]

    with pytest.raises(ProductPaperProtectiveExitLoopError, match="incomplete|discontinuity"):
        run_cycle(
            root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:31:00Z"),
            fetcher=bad_fetch,
        )
    assert len(ProductRuntime(tmp_path, opening_cash="500").paper_snapshot()["account"]["positions"]) == 1


def test_fetch_failure_does_not_advance_cursor(tmp_path: Path):
    _open_runtime(tmp_path)
    cursor = tmp_path / "guard" / "cursor.json"

    def fail(*args, **kwargs):
        raise OSError("network unavailable")

    with pytest.raises(OSError, match="network unavailable"):
        run_cycle(
            root=tmp_path, cursor_path=cursor, now_ms=_ms("2026-10-05T00:16:00Z"), fetcher=fail,
        )
    assert not cursor.exists()
