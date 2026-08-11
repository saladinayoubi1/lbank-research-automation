from __future__ import annotations

from dataclasses import asdict, dataclass
import logging
from pathlib import Path

import pandas as pd
import requests

from gap_repair_checkpoint import (
    CheckpointError,
    build_checkpoint,
    read_checkpoint,
    write_checkpoint,
)
from main import (
    LBankError,
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
MAX_REPAIR_FAILURES_PER_RUN = 3


@dataclass(frozen=True)
class GapRepairOutcome:
    symbol: str
    timeframe: str
    gap_start_utc: str
    status: str
    recovered_candles: int
    detail: str


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

    step = pd.Timedelta(TIMEFRAME_SECONDS[timeframe], unit="s")
    deltas = normalized.diff()
    gap_positions = deltas[deltas > step].index
    return [normalized.iloc[position - 1] + step for position in gap_positions]


def missing_timestamp_set(
    timestamps: pd.Series,
    timeframe: str,
) -> set[pd.Timestamp]:
    """Return all missing timestamps between the first and last candle."""
    normalized = pd.DatetimeIndex(
        pd.to_datetime(timestamps, utc=True).drop_duplicates().sort_values()
    )
    if normalized.empty:
        return set()

    expected = pd.date_range(
        start=normalized[0],
        end=normalized[-1],
        freq=pd.Timedelta(TIMEFRAME_SECONDS[timeframe], unit="s"),
    )
    return set(expected.difference(normalized))


def select_missing_rows(
    frame: pd.DataFrame,
    missing: set[pd.Timestamp],
) -> pd.DataFrame:
    """Keep only API rows that correspond to currently missing timestamps."""
    if frame.empty or not missing:
        return frame.iloc[0:0].copy()

    normalized_missing = pd.DatetimeIndex(missing)
    return frame.loc[frame["timestamp"].isin(normalized_missing)].copy()


def _checkpoint_path(symbol: str, timeframe: str) -> Path:
    return Path(OUTPUT_ROOT) / "_gap_repair_checkpoints" / symbol / f"{timeframe}.json"


def _load_start_index(
    symbol: str,
    timeframe: str,
    gap_starts: list[pd.Timestamp],
) -> int:
    path = _checkpoint_path(symbol, timeframe)
    if not path.exists():
        return 0
    checkpoint = read_checkpoint(
        path,
        symbol=symbol,
        timeframe=timeframe,
        gap_starts=[value.isoformat() for value in gap_starts],
    )
    return checkpoint.cursor


def _persist_next_index(
    symbol: str,
    timeframe: str,
    gap_starts: list[pd.Timestamp],
    cursor: int,
) -> None:
    checkpoint = build_checkpoint(
        symbol=symbol,
        timeframe=timeframe,
        gap_starts=[value.isoformat() for value in gap_starts],
        cursor=cursor,
    )
    write_checkpoint(_checkpoint_path(symbol, timeframe), checkpoint)


def repair_series_with_outcomes(
    symbol: str,
    timeframe: str,
) -> tuple[int, int, list[GapRepairOutcome]]:
    """Repair bounded gap windows and classify each attempted or deferred gap."""
    output_path = Path(OUTPUT_ROOT) / symbol / f"{timeframe}.parquet"
    existing = read_existing(output_path)
    if existing.empty:
        return 0, 0, []

    gap_starts = find_gap_starts(existing["timestamp"], timeframe)
    if not gap_starts:
        return 0, 0, []

    missing = missing_timestamp_set(existing["timestamp"], timeframe)
    repaired_frames: list[pd.DataFrame] = []
    outcomes: list[GapRepairOutcome] = []
    request_count = 0
    request_failures = 0

    try:
        start_index = _load_start_index(symbol, timeframe, gap_starts)
    except CheckpointError as exc:
        outcomes.append(GapRepairOutcome(
            symbol=symbol,
            timeframe=timeframe,
            gap_start_utc=gap_starts[0].isoformat(),
            status="checkpoint_invalid",
            recovered_candles=0,
            detail=str(exc),
        ))
        return 0, 0, outcomes

    ordered_gap_starts = gap_starts[start_index:] + gap_starts[:start_index]

    for gap_start in ordered_gap_starts:
        if gap_start not in missing:
            continue
        if request_count >= MAX_GAP_WINDOWS_PER_SERIES_PER_RUN:
            outcomes.append(GapRepairOutcome(
                symbol=symbol,
                timeframe=timeframe,
                gap_start_utc=gap_start.isoformat(),
                status="deferred_budget",
                recovered_candles=0,
                detail="per-series request budget exhausted",
            ))
            continue

        request_count += 1
        try:
            rows = get_klines(symbol, timeframe, int(gap_start.timestamp()))
        except (requests.RequestException, LBankError) as exc:
            request_failures += 1
            outcomes.append(GapRepairOutcome(
                symbol=symbol,
                timeframe=timeframe,
                gap_start_utc=gap_start.isoformat(),
                status="fetch_failed",
                recovered_candles=0,
                detail=type(exc).__name__,
            ))
            LOGGER.exception(
                "Gap request failed for %s %s from %s",
                symbol,
                timeframe,
                gap_start,
            )
            continue

        frame = rows_to_frame(rows, symbol, timeframe)
        repaired = select_missing_rows(frame, missing)
        if repaired.empty:
            outcomes.append(GapRepairOutcome(
                symbol=symbol,
                timeframe=timeframe,
                gap_start_utc=gap_start.isoformat(),
                status="source_unavailable",
                recovered_candles=0,
                detail="request succeeded but returned no currently missing candle",
            ))
            LOGGER.warning(
                "No missing candles recovered for %s %s from %s",
                symbol,
                timeframe,
                gap_start,
            )
            continue

        recovered_count = len(repaired)
        repaired_frames.append(repaired)
        missing.difference_update(
            pd.DatetimeIndex(pd.to_datetime(repaired["timestamp"], utc=True))
        )
        outcomes.append(GapRepairOutcome(
            symbol=symbol,
            timeframe=timeframe,
            gap_start_utc=gap_start.isoformat(),
            status="recovered",
            recovered_candles=recovered_count,
            detail="missing candle rows returned and selected",
        ))

    if gap_starts and request_count:
        next_index = (start_index + request_count) % len(gap_starts)
        _persist_next_index(symbol, timeframe, gap_starts, next_index)

    if not repaired_frames:
        return 0, request_failures, outcomes

    before = len(existing)
    after = save_merged(existing, repaired_frames, output_path)
    repaired_count = max(0, after - before)
    LOGGER.info("Repaired %s candle(s) for %s %s", repaired_count, symbol, timeframe)
    return repaired_count, request_failures, outcomes


def repair_series(symbol: str, timeframe: str) -> tuple[int, int]:
    """Backward-compatible repair API returning repaired and failed counts."""
    repaired, failures, _ = repair_series_with_outcomes(symbol, timeframe)
    return repaired, failures


def write_gap_repair_report(outcomes: list[GapRepairOutcome]) -> None:
    """Write machine-readable and human-readable gap outcome reports."""
    output_root = Path(OUTPUT_ROOT)
    output_root.mkdir(parents=True, exist_ok=True)
    columns = [
        "symbol",
        "timeframe",
        "gap_start_utc",
        "status",
        "recovered_candles",
        "detail",
    ]
    frame = pd.DataFrame([asdict(outcome) for outcome in outcomes], columns=columns)
    if not frame.empty:
        frame = frame.sort_values(["symbol", "timeframe", "gap_start_utc"])

    frame.to_csv(output_root / "_gap_repair_status.csv", index=False)

    lines = [
        "# LBank Gap Repair Status",
        "",
        "Successful requests that return no missing candle are classified as "
        "`source_unavailable`; transport or API exceptions are `fetch_failed`. "
        "Invalid persisted fairness state is `checkpoint_invalid` and blocks that series for the run.",
        "",
        "| Symbol | Timeframe | Gap start UTC | Status | Recovered | Detail |",
        "|---|---|---|---|---:|---|",
    ]
    for row in frame.to_dict("records"):
        lines.append(
            "| {symbol} | {timeframe} | {gap_start_utc} | {status} | "
            "{recovered_candles} | {detail} |".format(**row)
        )
    (output_root / "_gap_repair_status.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def repair_all() -> int:
    repaired_total = 0
    failure_total = 0
    outcomes: list[GapRepairOutcome] = []

    try:
        for symbol in SYMBOLS:
            for timeframe in TIMEFRAMES:
                repaired_count, request_failures, series_outcomes = (
                    repair_series_with_outcomes(symbol, timeframe)
                )
                repaired_total += repaired_count
                failure_total += request_failures
                outcomes.extend(series_outcomes)

                if failure_total >= MAX_REPAIR_FAILURES_PER_RUN:
                    raise RuntimeError(
                        "Stopped gap repair after "
                        f"{failure_total} failed API request windows"
                    )
    finally:
        write_gap_repair_report(outcomes)
        write_backfill_status()

    return repaired_total


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    repair_all()
