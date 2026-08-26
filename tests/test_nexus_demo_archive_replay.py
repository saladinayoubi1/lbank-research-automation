from __future__ import annotations

import pandas as pd

import nexus_demo_archive_replay as replay


def _frame(rows: int = 8) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=rows, freq="15min", tz="UTC"),
        "open": [100 + index for index in range(rows)],
        "high": [102 + index for index in range(rows)],
        "low": [99 + index for index in range(rows)],
        "close": [101 + index for index in range(rows)],
        "volume": [10 + index for index in range(rows)],
        "symbol": ["btc_usdt"] * rows,
        "timeframe": ["minute15"] * rows,
        "open_time_ms": [1_767_225_600_000 + index * 900_000 for index in range(rows)],
    })


def test_replay_clock_advances_one_verified_archive_candle(monkeypatch) -> None:
    monkeypatch.setattr(replay, "_load_frame", lambda *_args: _frame())
    first_now = replay.next_replay_now_ms("unused", "BTCUSDT", "minute15", -1, 4)
    second_now = replay.next_replay_now_ms(
        "unused", "BTCUSDT", "minute15", first_now - 900_000, 4
    )
    assert second_now - first_now == 900_000


def test_archive_fetcher_binds_exact_closed_bybit_window(monkeypatch) -> None:
    frame = _frame()
    monkeypatch.setattr(replay, "_load_frame", lambda *_args: frame)
    fetcher = replay.build_archive_dataset_fetcher(
        "unused", archive_sha256=replay.ARCHIVE_SHA256
    )
    start = int(frame["open_time_ms"].iloc[0])
    end = int(frame["open_time_ms"].iloc[3])
    dataset = fetcher(
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval="15",
        now_ms=end + 900_000,
        start_time_ms=start,
        end_time_ms=end,
        limit=4,
    )
    assert dataset["source"] == "Bybit"
    assert dataset["row_count"] == 4
    assert dataset["manifest"]["metadata"]["archive_sha256"] == replay.ARCHIVE_SHA256
    assert dataset["paper_only"] is True
