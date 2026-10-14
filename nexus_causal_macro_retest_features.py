"""Frozen closed-4h break / first full later 1h retest / lagged 15m event.

Research features only. A price event consumes its identity before independent
body, regime and cost admission. Newly closed higher bars alter future state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pandas as pd

PREREGISTRATION = Path(__file__).resolve().parent / "research" / "causal_macro_break_retest_v10_preregistration.json"
PARAMETERS = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
_unsigned = {k: v for k, v in PARAMETERS.items() if k != "preregistration_digest"}
_digest = hashlib.sha256(json.dumps(_unsigned, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False).encode()).hexdigest()
if _digest != PARAMETERS.get("preregistration_digest") or _digest != "76d6162e5bae2685715287db0b54979e99f26180b5e34a29ea673d41b1708e08":
    raise ValueError("Frozen macro retest preregistration differs")

STEP_NS = 900_000_000_000
HOUR_NS = 4 * STEP_NS
BAND_BARS, WAIT_HOURS, READY_BARS = 6, 6, 8
STRESS_FEE, STRESS_SLIP = .0025, .0015


def stress_cost_screen(close: float, atr: float, span: float) -> dict:
    """Decision-close hypothesis, never the unknown actual next-open price."""
    result = {"close": close, "atr": atr, "span": span, "fee": STRESS_FEE,
              "slip": STRESS_SLIP, "feasible": False, "denial_reason": None}
    if not all(math.isfinite(v) and v > 0 for v in (close, atr, span)):
        result["denial_reason"] = "invalid_close_atr_or_span"
        return result
    entry = close * (1 + STRESS_SLIP)
    stop, target = entry - 1.5 * atr, entry + 3 * atr
    exit_price = target * (1 - STRESS_SLIP)
    flat_cost = 2 * close * (STRESS_FEE + STRESS_SLIP)
    net = exit_price - entry - STRESS_FEE * (entry + exit_price)
    result.update(entry=entry, stop=stop, target=target, exit=exit_price,
                  flat_cost=flat_cost, target_net=net)
    if not all(math.isfinite(v) for v in (entry, stop, target, exit_price, flat_cost, net)):
        result["denial_reason"] = "nonfinite_projection"
    elif stop <= 0:
        result["denial_reason"] = "nonpositive_stop"
    elif span <= flat_cost:
        result["denial_reason"] = "span_not_above_flat_cost"
    elif net <= 0:
        result["denial_reason"] = "nonpositive_target_net"
    else:
        result["feasible"] = True
    return result


@dataclass(frozen=True)
class MacroSetup:
    h4_index: int
    opened_ns: int
    closed_ns: int
    high: float
    low: float
    retest_index: int | None = None
    confirmed_ns: int | None = None
    trigger_high: float | None = None


def _validated(frame: pd.DataFrame, interval: int, label: str) -> tuple[np.ndarray, np.ndarray]:
    if not {"timestamp", "open", "high", "low", "close", "volume"}.issubset(frame.columns):
        raise ValueError(label + " missing timestamp/OHLCV")
    times = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    ns = times.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    if (times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing
            or (np.diff(ns) != interval).any() or (ns % interval != 0).any()):
        raise ValueError(label + " requires a complete aligned UTC grid")
    values = frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values[:, :4] <= 0).any()
            or (values[:, 4] < 0).any() or (values[:, 1] < values[:, :4].max(axis=1)).any()
            or (values[:, 2] > values[:, :4].min(axis=1)).any()):
        raise ValueError(label + " OHLCV failed strict validation")
    return ns, values


def _json_finite(value):
    if isinstance(value, dict):
        return {k: _json_finite(v) for k, v in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def build_lagged_macro_retest_features(
    frames: dict[str, pd.DataFrame], *, diagnostics: list[dict] | None = None,
) -> dict[str, pd.Series]:
    """Previous state -> 15m invalidation/event -> closed H1 -> closed H4."""
    try:
        minute, hour, four = (frames[k] for k in ("minute15", "hour1", "hour4"))
    except KeyError as exc:
        raise ValueError("Macro retest requires all three timeframes") from exc
    mt, mv = _validated(minute, STEP_NS, "minute15")
    ht, hv = _validated(hour, HOUR_NS, "hour1")
    qt, qv = _validated(four, 4 * HOUR_NS, "hour4")
    hc, qc = ht + HOUR_NS, qt + 4 * HOUR_NS
    atr = pd.Series(mv[:, 1] - mv[:, 2]).shift(1).rolling(14, min_periods=14).mean().to_numpy()
    numeric = ("lagged_macro_break_high", "lagged_macro_break_low", "lagged_macro_break_span",
               "lagged_macro_h4_index", "lagged_macro_closed_ms", "lagged_macro_retest_h1_index",
               "lagged_macro_retest_confirmed_ms", "lagged_macro_retest_trigger_high",
               "macro_retest_trigger_index", "macro_retest_flat_cost", "macro_retest_target_net")
    output = {name: np.full(len(minute), np.nan) for name in numeric}
    for name in ("lagged_macro_retest_active", "macro_retest_close_breakout_event",
                 "macro_retest_stress_cost_feasible"):
        output[name] = np.zeros(len(minute))
    setup: MacroSetup | None = None
    hi = qi = 0

    def record(kind: str, state: MacroSetup, at: int, now: int, **extra):
        if diagnostics is not None:
            diagnostics.append(_json_finite({
                "kind": kind, "decision_index": at,
                "decision_at": pd.Timestamp(now, tz="UTC").isoformat(),
                "macro_identity": {"h4_index": state.h4_index, "open_ns": state.opened_ns,
                                   "high": state.high, "low": state.low},
                "macro_closed_at": pd.Timestamp(state.closed_ns, tz="UTC").isoformat(),
                "retest_h1_index": state.retest_index,
                "retest_confirmed_at": (pd.Timestamp(state.confirmed_ns, tz="UTC").isoformat()
                                        if state.confirmed_ns is not None else None),
                "retest_high": state.trigger_high, **extra,
            }))

    for at, now_value in enumerate(mt + STEP_NS):
        now = int(now_value)
        if setup is not None:
            old = setup
            if old.confirmed_ns is not None:
                output["lagged_macro_retest_active"][at] = 1
                for name, value in (
                    ("break_high", old.high), ("break_low", old.low), ("break_span", old.high-old.low),
                    ("h4_index", old.h4_index), ("closed_ms", old.closed_ns // 1_000_000),
                    ("retest_h1_index", old.retest_index), ("retest_confirmed_ms", old.confirmed_ns // 1_000_000),
                    ("retest_trigger_high", old.trigger_high),
                ):
                    output["lagged_macro_" + name][at] = value
                screen = stress_cost_screen(float(mv[at, 3]), float(atr[at]), old.high-old.low)
                output["macro_retest_stress_cost_feasible"][at] = float(screen["feasible"])
                output["macro_retest_flat_cost"][at] = screen.get("flat_cost", np.nan)
                output["macro_retest_target_net"][at] = screen.get("target_net", np.nan)
            deadline = (old.closed_ns + WAIT_HOURS * HOUR_NS if old.confirmed_ns is None
                        else old.confirmed_ns + READY_BARS * STEP_NS)
            if now > deadline:
                record("expired", old, at, now)
                setup = None
            elif mt[at] >= old.closed_ns and (mv[at, 2] <= old.low or mv[at, 3] <= old.high):
                record("invalidated", old, at, now,
                       reason="low_at_or_below_band_low" if mv[at, 2] <= old.low else "close_at_or_below_band_high")
                setup = None
            elif (old.confirmed_ns is not None and now > old.confirmed_ns and at > 0
                  and mv[at, 3] > old.trigger_high and mv[at-1, 3] <= old.trigger_high):
                output["macro_retest_close_breakout_event"][at] = 1
                output["macro_retest_trigger_index"][at] = at
                record("price_event", old, at, now, cost_screen=screen)
                setup = None  # Consumed even when external admission denies entry.

        while hi < len(hour) and hc[hi] <= now:
            if (setup is not None and setup.confirmed_ns is None and hc[hi] == now
                    and ht[hi] >= setup.closed_ns and hc[hi] > setup.closed_ns
                    and hc[hi] <= setup.closed_ns + WAIT_HOURS * HOUR_NS
                    and hv[hi, 2] <= setup.high):
                old = setup
                if hv[hi, 3] > old.high and hv[hi, 3] > hv[hi, 0] and hv[hi, 2] > old.low:
                    setup = replace(old, retest_index=hi, confirmed_ns=int(hc[hi]), trigger_high=float(hv[hi, 1]))
                    record("retest_accepted", setup, at, now)
                else:
                    record("first_touch_denied", old, at, now, touched_h1_index=hi)
                    setup = None
            hi += 1

        while qi < len(four) and qc[qi] <= now:
            # Do not retroactively arm a macro that closed before this 15m
            # history starts; its intervening invalidation path is unobserved.
            if qi >= BAND_BARS and qc[qi] == now:
                high = float(qv[qi-BAND_BARS:qi, 1].max())
                low = float(qv[qi-BAND_BARS:qi, 2].min())
                if high > low and qv[qi, 3] > qv[qi, 0] and qv[qi, 3] > high:
                    if setup is not None:
                        record("replaced_by_new_macro", setup, at, now, next_h4_index=qi)
                    setup = MacroSetup(qi, int(qt[qi]), int(qc[qi]), high, low)
                    record("macro_accepted", setup, at, now)
            qi += 1
    return {name: pd.Series(values, index=minute.index) for name, values in output.items()}
