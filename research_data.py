from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from data_readiness import evaluate_readiness
from main import COLUMNS, analyze_timestamp_integrity

DEFAULT_DATA_ROOT = Path("data/market")
DEFAULT_STATUS_PATH = DEFAULT_DATA_ROOT / "_backfill_status.csv"
EXPECTED_COLUMNS = COLUMNS + ["symbol", "timeframe"]


class ResearchDataError(RuntimeError):
    pass


def get_series_readiness(
    symbol: str,
    timeframe: str,
    status_path: Path = DEFAULT_STATUS_PATH,
    minimum_rows: int = 0,
) -> dict[str, Any]:
    if not status_path.exists():
        raise ResearchDataError(f"Readiness source not found: {status_path}")

    status_frame = pd.read_csv(status_path)
    readiness = evaluate_readiness(status_frame, minimum_rows=minimum_rows)
    match = readiness.loc[
        (readiness["symbol"] == symbol)
        & (readiness["timeframe"] == timeframe)
    ]
    if match.empty:
        raise ResearchDataError(
            f"Series is absent from readiness status: {symbol} {timeframe}"
        )
    if len(match) > 1:
        raise ResearchDataError(
            f"Series appears multiple times in readiness status: {symbol} {timeframe}"
        )
    return match.iloc[0].to_dict()


def validate_research_frame(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    if frame.columns.tolist() != EXPECTED_COLUMNS:
        raise ResearchDataError(
            "Unexpected Parquet schema for "
            f"{symbol} {timeframe}: {frame.columns.tolist()}"
        )
    if frame.empty:
        raise ResearchDataError(f"Parquet dataset is empty: {symbol} {timeframe}")

    normalized = frame.copy()
    normalized["timestamp"] = pd.to_datetime(
        normalized["timestamp"],
        utc=True,
        errors="raise",
    )
    normalized = normalized.sort_values("timestamp").reset_index(drop=True)

    symbols = set(normalized["symbol"].dropna().astype(str))
    timeframes = set(normalized["timeframe"].dropna().astype(str))
    if symbols != {symbol}:
        raise ResearchDataError(
            f"Unexpected symbol values for {symbol} {timeframe}: {sorted(symbols)}"
        )
    if timeframes != {timeframe}:
        raise ResearchDataError(
            f"Unexpected timeframe values for {symbol} {timeframe}: "
            f"{sorted(timeframes)}"
        )

    integrity = analyze_timestamp_integrity(normalized["timestamp"], timeframe)
    if not integrity["integrity_ok"]:
        raise ResearchDataError(
            f"Runtime integrity check failed for {symbol} {timeframe}: {integrity}"
        )
    return normalized


def load_research_series(
    symbol: str,
    timeframe: str,
    data_root: Path = DEFAULT_DATA_ROOT,
    status_path: Path | None = None,
    minimum_rows: int = 0,
) -> pd.DataFrame:
    resolved_status_path = status_path or data_root / "_backfill_status.csv"
    readiness = get_series_readiness(
        symbol,
        timeframe,
        status_path=resolved_status_path,
        minimum_rows=minimum_rows,
    )
    if not readiness["ready_for_research"]:
        raise ResearchDataError(
            f"Series is not research-ready: {symbol} {timeframe} "
            f"({readiness['readiness_reason']})"
        )

    parquet_path = data_root / symbol / f"{timeframe}.parquet"
    if not parquet_path.exists():
        raise ResearchDataError(f"Parquet file not found: {parquet_path}")

    frame = pd.read_parquet(parquet_path)
    validated = validate_research_frame(frame, symbol, timeframe)
    if len(validated) < minimum_rows:
        raise ResearchDataError(
            f"Series row count fell below minimum after load: "
            f"{len(validated)} < {minimum_rows}"
        )
    return validated
