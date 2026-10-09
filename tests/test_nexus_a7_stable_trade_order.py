"""Regression for duplicate timestamps preserving file-chronological trade order."""
from __future__ import annotations

import pandas as pd

import bybit_spot_backfill as backfill


def test_same_millisecond_trades_keep_source_open_close():
    start = pd.Timestamp("2026-10-07T00:00:00Z")
    step = pd.Timedelta(15, unit="min")
    last = pd.Timedelta(14, unit="min") + pd.Timedelta(59, unit="s")
    rows = []
    for quarter in range(96):
        begin = start + quarter * step
        base = 1000.0 + quarter
        for offset, (timestamp, delta) in enumerate(
            ((begin, 0.01), (begin, 0.02), (begin + last, 0.03), (begin + last, 0.04))
        ):
            rows.append({
                "timestamp": timestamp, "price": base + delta, "size": 1.0,
                "side": "Buy", "trade_id": str(4 * quarter + offset + 1),
                "symbol": "XRPUSDT",
            })
    validated, quality = backfill.validate_trade_range(
        pd.DataFrame(rows), "XRPUSDT", "2026-10-07", "2026-10-07"
    )
    assert quality["duplicate_trade_id_count"] == 0
    assert quality["valid_trade_rows"] == len(rows)
    for timeframe, per_bar in (("minute15", 1), ("hour1", 4), ("hour4", 16)):
        result = backfill.trades_to_range_candles(
            validated, "XRPUSDT", timeframe, "2026-10-07", "2026-10-07"
        )
        assert len(result) == 96 // per_bar
        for index, candle in enumerate(result.itertuples(index=False)):
            first = index * per_bar
            last_quarter = (index + 1) * per_bar - 1
            assert abs(candle.open - (1000.0 + first + 0.01)) < 1e-10
            assert abs(candle.close - (1000.0 + last_quarter + 0.04)) < 1e-10
            assert abs(candle.volume - 4.0 * per_bar) < 1e-10
