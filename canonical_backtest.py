from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from backtest_engine import BacktestConfig, BacktestError, BacktestResult, run_target_exposure_backtest
from phase5_data_binding import CanonicalDataError, validate_canonical_dataset


class CanonicalBacktestError(ValueError):
    """Raised when an authoritative backtest cannot prove canonical data lineage."""


def canonical_market_frame(
    dataset: Mapping[str, Any], *, registry_path: Path | None = None
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Validate the complete Gate-7 artifact before exposing a market frame.

    This is the only repository boundary allowed to feed the low-level raw-frame
    backtest engine from authoritative research/product code.  The low-level engine
    remains intentionally reusable for unit tests and non-authoritative mechanics.
    """
    try:
        if registry_path is None:
            artifact = validate_canonical_dataset(dataset)
        else:
            artifact = validate_canonical_dataset(dataset, registry_path=registry_path)
    except CanonicalDataError as exc:
        raise CanonicalBacktestError(f"canonical dataset rejected: {exc}") from exc

    rows = artifact["rows"]
    frame = pd.DataFrame(rows)
    try:
        frame["timestamp"] = pd.to_datetime(frame["open_time_ms"], unit="ms", utc=True)
        frame = frame[["timestamp", "open", "high", "low", "close"]].copy()
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalBacktestError("canonical rows cannot form a deterministic market frame") from exc
    if len(frame) != artifact["row_count"]:
        raise CanonicalBacktestError("canonical row count changed while constructing market frame")
    return artifact, frame


def run_canonical_target_exposure_backtest(
    dataset: Mapping[str, Any],
    target_exposures: Sequence[float],
    config: BacktestConfig | None = None,
    *,
    registry_path: Path | None = None,
    start: int = 0,
    end: int | None = None,
) -> BacktestResult:
    """Run the raw backtest engine only after full semantic/provenance validation.

    Slice selection happens *inside* this boundary.  Callers therefore cannot make
    an authoritative OOS/regime result from a detached DataFrame that has lost its
    source, role, timeframe, endpoint, mapping-policy, finality, row-hash or binding
    identity.
    """
    artifact, frame = canonical_market_frame(dataset, registry_path=registry_path)
    targets = list(target_exposures)
    if len(targets) != artifact["row_count"]:
        raise CanonicalBacktestError("target exposure count must match canonical row count")

    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        raise CanonicalBacktestError("canonical backtest start must be a non-negative integer")
    resolved_end = artifact["row_count"] if end is None else end
    if isinstance(resolved_end, bool) or not isinstance(resolved_end, int):
        raise CanonicalBacktestError("canonical backtest end must be an integer")
    if resolved_end > artifact["row_count"] or resolved_end <= start:
        raise CanonicalBacktestError("canonical backtest slice is outside the bound dataset")

    bounded_frame = frame.iloc[start:resolved_end].reset_index(drop=True)
    bounded_targets = targets[start:resolved_end]
    try:
        return run_target_exposure_backtest(bounded_frame, bounded_targets, config)
    except BacktestError as exc:
        raise CanonicalBacktestError(f"deterministic backtest rejected canonical input: {exc}") from exc
