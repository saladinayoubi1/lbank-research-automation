"""Causal daily-clock volume context for the existing Research factory."""
from __future__ import annotations

import numpy as np
import pandas as pd

SLOTS_PER_DAY = 96
HISTORY_DAYS = 7
FEATURE_COLUMNS = (
    "lagged_utc_slot_volume_mean_7d",
    "lagged_utc_slot_volume_ratio_7d",
    "lagged_utc_slot_volume_cv_7d",
)


def build_lagged_utc_slot_volume_features(
    timestamp: pd.Series, volume: pd.Series,
) -> pd.DataFrame:
    """At decision i, compare event volume i-1 to its seven prior UTC slots.

    Baseline samples are i-1-96*k, k=1..7; the event cannot set its own
    baseline. All seven exact daily observations are required. Missing history
    or a zero baseline is unavailable, never an infinite signal. This is
    candle participation context, not an order-book or trade-flow measurement.
    """
    if not isinstance(timestamp, pd.Series) or not isinstance(volume, pd.Series):
        raise ValueError("slot inputs must be aligned Series")
    if not timestamp.index.equals(volume.index):
        raise ValueError("slot input indices differ")
    times = pd.to_datetime(timestamp, errors="raise")
    if not isinstance(times.dtype, pd.DatetimeTZDtype) or times.isna().any():
        raise ValueError("slot timestamps must be timezone-aware and finite")
    times = times.dt.tz_convert("UTC")
    tick_ns = pd.Timedelta(minutes=15).value
    ticks = pd.DatetimeIndex(times).asi8
    if (
        times.duplicated().any()
        or not times.is_monotonic_increasing
        or (len(ticks) > 1 and not np.all(np.diff(ticks) == tick_ns))
        or np.any(ticks % tick_ns)
    ):
        raise ValueError("slot timestamps require a contiguous aligned UTC 15m grid")
    values = pd.to_numeric(volume, errors="raise").astype(float)
    if not np.isfinite(values.to_numpy()).all() or (values < 0).any():
        raise ValueError("slot volume must be finite and nonnegative")
    history = pd.concat(
        [values.shift(SLOTS_PER_DAY * day) for day in range(1, HISTORY_DAYS + 1)],
        axis=1,
    )
    complete = history.notna().all(axis=1)
    mean = history.mean(axis=1).where(complete)
    denominator = mean.where(mean > 0)
    ratio = values / denominator
    cv = history.std(axis=1, ddof=0) / denominator
    return pd.DataFrame({
        FEATURE_COLUMNS[0]: mean.shift(1),
        FEATURE_COLUMNS[1]: ratio.shift(1),
        FEATURE_COLUMNS[2]: cv.shift(1),
    }, index=volume.index).replace([np.inf, -np.inf], np.nan)
