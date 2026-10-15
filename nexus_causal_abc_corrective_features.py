"""Causal, closed-15m ABC four-pivot feature helper: research only.

Input timestamps denote candle CLOSE; caller must prove completed-bar cutoff.
Market data archive access, execution, risk and automatic factory remain disabled.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from nexus_causal_abc_corrective_review import (
    ConfirmedABCPivot, review_abc_corrective_shape, WIDTH, MAX_AGE,
)
from nexus_causal_macro_retest_features import stress_cost_screen

RESEARCH_ONLY = True
LIVE_ENABLED = False
AUTO_DEMO = False
FACTORY_REGISTERED = False
STEP_NS = 900_000_000_000

NUMERIC = (
    "lagged_abc_h0", "lagged_abc_la", "lagged_abc_hb", "lagged_abc_lc",
    "lagged_abc_h0_index", "lagged_abc_la_index",
    "lagged_abc_hb_index", "lagged_abc_lc_index",
    "lagged_abc_confirmed_at", "lagged_abc_b_retrace",
    "lagged_abc_c_extension", "abc_trigger_index", "abc_decision_range",
    "abc_flat_cost", "abc_target_net",
)
FLAGS = ("lagged_abc_active", "abc_first_close_break_event",
         "abc_stress_cost_feasible", "abc_invalidated", "abc_expired",
         "abc_path_rejected")


def _validate(frame: pd.DataFrame, last_completed_at: pd.Timestamp) -> np.ndarray:
    required = {"timestamp", "open", "high", "low", "close"}
    if not required <= set(frame.columns):
        raise ValueError("ABC requires completed close-timestamp OHLC candles")
    times = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if times.isna().any() or any(pd.Timestamp(t).tzinfo is None for t in frame["timestamp"]):
        raise ValueError("ABC requires explicit timezone-aware close times")
    if pd.Timestamp(last_completed_at).tzinfo is None:
        raise ValueError("ABC requires aware caller-owned completed-bar cutoff")
    cut = pd.Timestamp(last_completed_at).tz_convert("UTC")
    ns = times.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    if (len(times) == 0 or not times.is_monotonic_increasing or times.duplicated().any()
            or (len(ns) > 1 and (np.diff(ns) != STEP_NS).any())
            or (ns % STEP_NS != 0).any() or times.iloc[-1] > cut):
        raise ValueError("ABC incomplete, unaligned or future OHLC input")
    prices = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if (not np.isfinite(prices).all() or (prices <= 0).any()
            or (prices[:, 1] < prices.max(axis=1)).any()
            or (prices[:, 2] > prices.min(axis=1)).any()):
        raise ValueError("ABC OHLC invalid")
    return prices


def _confirmed(highs: np.ndarray, lows: np.ndarray, at: int) -> ConfirmedABCPivot | None:
    if at < WIDTH * 2:
        return None
    center, begin = at - WIDTH, at - WIDTH * 2
    other_h = np.r_[highs[begin:center], highs[center + 1:at + 1]]
    other_l = np.r_[lows[begin:center], lows[center + 1:at + 1]]
    is_h = bool((highs[center] > other_h).all())
    is_l = bool((lows[center] < other_l).all())
    if is_h == is_l:
        return None
    return ConfirmedABCPivot("high" if is_h else "low", center, at,
                             float(highs[center] if is_h else lows[center]))


def _path_error(
    group: tuple[ConfirmedABCPivot, ...],
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    confirmed_at: int,
) -> str | None:
    h0, la, hb, lc = group
    a, b, c, d = (x.index for x in group)
    if highs[a:b + 1].max() > float(h0.price) or lows[a:b + 1].min() < float(la.price):
        return "A_segment_path_extremum"
    if highs[b:c + 1].max() > float(hb.price) or lows[b:c + 1].min() < float(la.price):
        return "B_segment_path_extremum"
    if highs[c:d + 1].max() > float(hb.price) or lows[c:d + 1].min() < float(lc.price):
        return "C_segment_path_extremum"
    if lows[d:confirmed_at + 1].min() < float(lc.price):
        return "confirmed_C_low_breached"
    if (closes[d + 1:confirmed_at + 1] > float(hb.price)).any():
        return "unobservably_early_close_break"
    return None


def build_closed_abc_features(
    closed_frame: pd.DataFrame, *, last_completed_at: pd.Timestamp,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, pd.Series]:
    """Return causal state, one-shot close-break events and stress cost projection.

    Model does not populate a trading signal: h4/h1 context, body and next-open
    execution must be checked separately at the actual completed decision bar.
    Strictly consumes first price-cross identity even when stress fails.
    """
    prices = _validate(closed_frame, last_completed_at)
    opens, highs, lows, closes = prices.T
    n = len(closed_frame)
    lagged_range = pd.Series(highs - lows).shift(1).rolling(14,min_periods=14).mean().to_numpy()
    out = {key: np.full(n, np.nan) for key in NUMERIC}
    out.update({key: np.zeros(n, dtype=bool) for key in FLAGS})
    pivots: list[ConfirmedABCPivot] = []
    setup: dict | None = None
    consumed: set[tuple[int, int]] = set()

    def emit(at: int, action: str, **kwargs) -> None:
        if diagnostics is not None:
            diagnostics.append(dict(decision_index=at, action=action, **kwargs))

    for at in range(n):
        if setup is not None:
            identity = setup["identity"]
            out["lagged_abc_active"][at] = True
            for k, v in (
                ("h0",setup["H0"]),("la",setup["LA"]),("hb",setup["HB"]),
                ("lc",setup["LC"]),("h0_index",identity[0]),
                ("la_index",setup["A_index"]),("hb_index",setup["B_index"]),
                ("lc_index",identity[1]),("confirmed_at",setup["confirmed_at"]),
                ("b_retrace",setup["B_retracement"]),
                ("c_extension",setup["C_extension"]),
            ):
                out["lagged_abc_"+k][at] = float(v)
            if lows[at] < float(setup["LC"]) or highs[at] > float(setup["H0"]):
                out["abc_invalidated"][at] = True
                emit(at,"invalidated",identity=list(identity),
                     reason="C_breach_or_orig_H0_overshoot")
                setup = None
            elif at - setup["confirmed_at"] > MAX_AGE:
                out["abc_expired"][at] = True
                emit(at,"expired",identity=list(identity))
                setup = None
            elif closes[at - 1] <= float(setup["HB"]) < closes[at]:
                consumed.add(identity)
                out["abc_first_close_break_event"][at] = True
                out["abc_trigger_index"][at] = at
                atr = float(lagged_range[at])
                screen = stress_cost_screen(float(closes[at]),atr,
                                            float(setup["H0"]-setup["LC"]))
                out["abc_decision_range"][at] = atr
                out["abc_stress_cost_feasible"][at] = bool(screen["feasible"])
                out["abc_flat_cost"][at] = screen.get("flat_cost", np.nan)
                out["abc_target_net"][at] = screen.get("target_net", np.nan)
                emit(at, "price_event_consumed", identity=list(identity),
                     cost_screen=screen)
                setup = None

        point = _confirmed(highs, lows, at)
        if point is None:
            continue
        if pivots and pivots[-1].kind == point.kind:
            old = pivots[-1]
            more = point.price > old.price if point.kind == "high" else point.price < old.price
            if not more:
                continue
            pivots[-1] = point
        else:
            pivots.append(point)
            pivots = pivots[-4:]
        setup = None
        emit(at,"pivot_accepted",kind=point.kind,center_index=point.index,
             confirmed_at=point.confirmed_at)
        if point.kind != "low" or len(pivots) != 4:
            continue
        geometry = review_abc_corrective_shape(pivots,at + 1)
        if geometry is None:
            continue
        identity = geometry["identity"]
        if identity in consumed:
            emit(at,"consumed_identity",identity=list(identity))
            continue
        path_error = _path_error(tuple(pivots),highs,lows,closes,at)
        if path_error is not None:
            out["abc_path_rejected"][at] = True
            emit(at,"path_rejected",identity=list(identity),reason=path_error)
            continue
        setup = {**geometry,"A_index":pivots[1].index,"B_index":pivots[2].index}
        emit(at,"setup_stored_for_next_bar",identity=list(identity),
             earliest_decision_index=at + 1)
    return {key: pd.Series(val,index=closed_frame.index) for key,val in out.items()}
