from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from main import (
    OUTPUT_ROOT,
    SYMBOLS,
    TIMEFRAMES,
    TIMEFRAME_SECONDS,
    get_klines,
    read_existing,
    rows_to_frame,
    save_merged,
    write_backfill_status,
)

LOGGER = logging.getLogger("lbank_gap_repair")
MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 3


def find_gap_starts(timestamps: pd.Series, timeframe: str) -> list[pd.Timestamp]:
    """Return the first missing candle timestamp for each internal gap."""
    normalized = (
        pd.to_datetime(timestamps, utc=True)
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
    )
    if len(normalized) < 2:
        return []

    step = pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    deltas = normalized.diff()
    gap_positions = deltas[deltas > step].index
    return [normalized.iloc[position - 1] + step for position in gap_positions]


def missing_timestamp_set(timestamps: pd.Series, timeframe: str) -> set[pd.Timestamp]:
    """Return all missing timestamps between the first and last candle."""
    normalized = pd.DatetimeIndex(
        pd.to_datetime(timestamps, utc=True).drop_duplicates().sort_values()
    )
    if normalized.empty:
        return set()

    expected = pd.date_range(
        start=normalized[0],
        end=normalized[-1],
        freq=pd.Timedelta(seconds=TIMEFRAME_SECONDS[timeframe]),
    )
    return set(expected.difference(normalized).to_pydatetime())


def select_missing_rows(
    frame: pd.DataFrame,
    missing: set[pd.Timestamp],
) -> pd.DataFrame:
    """Keep only API rows that correspond to currently missing timestamps."""
    if frame.empty or not missing:
        return frame.iloc[0:0].copy()

    normalized_missing = pd.DatetimeIndex(missing)
    return frame.loc[frame["timestamp"].isin(normalized_missing)].copy()


def repair_series(symbol: str, timeframe: str) -> int:
    output_path = Path(OUTPUT_ROOT) / symbol / f"{timeframe}.parquet"
    existing = read_existing(output_path)
    if existing.empty:
        return 0

    gap_starts = find_gap_starts(existing["timestamp"], timeframe)
    if not gap_starts:
        return 0

    missing = missing_timestamp_set(existing["timestamp"], timeframe)
    repaired_frames: list[pd.DataFrame] = []

    for gap_start in gap_starts[:MAX_GAP_WINDOWS_PER_SERIES_PER_RUN]:
        rows = get_klines(symbol, timeframe, int(gap_start.timestamp()))
        frame = rows_to_frame(rows, symbol, timeframe)
        repaired = select_missing_rows(frame, missing)
        if repaired.empty:
            LOGGER.warning(
                "No missing candles recovered for %s %s from %s",
                symbol,
                timeframe,
                gap_start,
            )
            continue

        repaired_frames.append(repaired)
        missing.difference_update(pd.to_datetime(repaired["timestamp"], utc=True))

    if not repaired_frames:
        return 0

    before = len(existing)
    after = save_merged(existing, repaired_frames, output_path)
    repaired_count = max(0, after - before)
    LOGGER.info("Repaired %s candle(s) for %s %s", repaired_count, symbol, timeframe)
    return repaired_count


def repair_all() -> int:
    repaired_total = 0
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            repaired_total += repair_series(symbol, timeframe)

    write_backfill_status()
    return repaired_total


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    repair_all()
