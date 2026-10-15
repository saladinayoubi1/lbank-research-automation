"""Source-bound CPython observation of the unchanged isolated research engine.

No frame-local or simulator-state writes. Line events capture copies after the
original entry/exit assignments. Unsupported source or existing tracing blocks
observation. This module never connects to Paper or an exchange.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import math
from pathlib import Path
import sys
import types

import numpy as np
import pandas as pd

EXPECTED_BACKTEST_SHA256 = "e44e2bada1efbf2427edfee224d75e96067bfcf1e3fa07b79fa39a09782b9bfb"
DOCS = "https://docs.python.org/3.12/library/sys.html#sys.settrace"


def _binding(function):
    path = Path(inspect.getsourcefile(function))
    source = path.read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "backtest")
    segment = ast.get_source_segment(source, node)
    digest = hashlib.sha256(segment.encode()).hexdigest()
    if digest != EXPECTED_BACKTEST_SHA256:
        raise ValueError("Observational gate: shared backtest source differs")
    # Compile the entire module without executing it. CPython's compiler can
    # emit different module-attribute call opcodes when imports are in scope.
    compiled = compile(source, str(path), "exec", dont_inherit=True)
    expected = next(c for c in compiled.co_consts if isinstance(c, types.CodeType) and c.co_name == "backtest")
    for attr in ("co_code", "co_consts", "co_names", "co_varnames", "co_freevars", "co_flags", "co_firstlineno", "co_linetable"):
        if getattr(function.__code__, attr) != getattr(expected, attr):
            raise ValueError("Observational gate: loaded backtest code differs")
    markers = {
        "attempt": "if stop > 0 and math.isfinite(stop) and math.isfinite(target):",
        "entry": "total_turnover += qty * entry_price",
        "exit": "gross_profit += max(0., pnl)",
        "schedule": "pending = float(row.atr)",
        "decision": "if in_pos is None and not just_entered and not halted and not day_paused and i < len(frame) - 1:",
    }
    lines = source.splitlines()
    anchors = {}
    for kind, text in markers.items():
        matches = [i + 1 for i in range(node.lineno - 1, node.end_lineno) if lines[i].strip() == text]
        if len(matches) != 1:
            raise ValueError("Observational gate: ambiguous source anchor")
        anchors[kind] = matches[0]
    return {"backtest_source_sha256": digest, "source_file": path.name,
            "line_anchors": anchors, "python_implementation": sys.implementation.name,
            "python_version": sys.version.split()[0], "api_documentation": DOCS}


def _finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def observe_backtest(function, frame, signals, *, fee_bps, slip_bps, risk_variant,
                     index_offset=0, event_profile="macro_retest"):
    """Return unchanged metrics plus actual execution observations, one cell."""
    if event_profile not in ("macro_retest", "elliott_five_swing", "abc_correction"):
        raise ValueError("Observational gate: unsupported event profile")
    is_elliott = event_profile == "elliott_five_swing"
    is_abc = event_profile == "abc_correction"
    event_field = ("abc_first_close_break_event" if is_abc else
                   "elliott5_close_breakout_event" if is_elliott else
                   "macro_retest_close_breakout_event")
    if (is_elliott or is_abc) and event_field not in frame:
        raise ValueError("Observational gate: research event field missing")
    setup_names = (
        "lagged_elliott5_origin_low", "lagged_elliott5_wave1_high", "lagged_elliott5_wave2_low",
        "lagged_elliott5_origin_index", "lagged_elliott5_wave1_index", "lagged_elliott5_wave2_index",
        "lagged_elliott5_confirmed_at", "lagged_elliott5_retracement",
        "elliott5_trigger_index", "elliott5_decision_atr", "elliott5_flat_cost", "elliott5_target_net",
    ) if is_elliott else (
        "lagged_abc_h0", "lagged_abc_la", "lagged_abc_hb", "lagged_abc_lc",
        "lagged_abc_h0_index", "lagged_abc_la_index", "lagged_abc_hb_index",
        "lagged_abc_lc_index", "lagged_abc_confirmed_at", "lagged_abc_b_retrace",
        "lagged_abc_c_extension", "abc_trigger_index", "abc_decision_range",
        "abc_flat_cost", "abc_target_net",
    ) if is_abc else (
        "lagged_macro_h4_index", "lagged_macro_closed_ms", "lagged_macro_break_high",
        "lagged_macro_break_low", "lagged_macro_break_span", "lagged_macro_retest_h1_index",
        "lagged_macro_retest_confirmed_ms", "lagged_macro_retest_trigger_high",
        "macro_retest_trigger_index", "macro_retest_flat_cost", "macro_retest_target_net",
    )
    admission_fields = ("h4_up", "h1_vol_ok", "lagged_elliott5_active", "elliott5_cost_feasible") if is_elliott else (
        "h4_up", "h1_vol_ok", "lagged_abc_active", "abc_stress_cost_feasible"
    ) if is_abc else (
        "h4_up", "h1_vol_ok", "lagged_macro_retest_active", "macro_retest_stress_cost_feasible",
    )
    if sys.implementation.name != "cpython" or sys.gettrace() is not None:
        raise ValueError("Observational gate requires untraced isolated CPython")
    binding = _binding(function)
    target_code = function.__code__
    anchors = binding["line_anchors"]
    trades, events, attempts = [], [], []
    active_trade = None
    pending_decision = None
    event_indices = (set(np.flatnonzero(frame[event_field].to_numpy() == 1))
                     if event_field in frame else set())

    def stamp(i):
        row = frame.iloc[i]
        decision = pd.Timestamp(row["decision_at"])
        opened = pd.Timestamp(row["timestamp"]) if "timestamp" in row else decision - pd.Timedelta(minutes=15)
        return {"bar_index": int(i + index_offset), "open_at": opened.isoformat(),
                "decision_at": decision.isoformat()}

    def setup(i):
        row = frame.iloc[i]
        return {name: _finite(row[name]) for name in setup_names if name in row}

    def cost_span(row):
        if is_elliott:
            return _finite(row.get("lagged_elliott5_wave1_high", np.nan)
                           - row.get("lagged_elliott5_origin_low", np.nan))
        if is_abc:
            return _finite(row.get("lagged_abc_h0", np.nan)
                           - row.get("lagged_abc_lc", np.nan))
        return _finite(row.get("lagged_macro_break_span", np.nan))

    def local_trace(current, event, arg):
        nonlocal pending_decision, active_trade
        if event != "line":
            return local_trace
        line = current.f_lineno
        if line not in anchors.values():
            return local_trace
        loc = current.f_locals
        i = loc["i"]
        if line == anchors["attempt"]:
            valid = loc["stop"] > 0 and math.isfinite(loc["stop"]) and math.isfinite(loc["target"])
            attempts.append({"decision": pending_decision, "fill_bar": stamp(i),
                             "entry_reference": loc["price_open"], "entry_slipped": loc["entry_price"],
                             "atr": loc["entry_atr"], "stop": loc["stop"], "target": loc["target"],
                             "disposition": "pending_quantity_check" if valid else "invalid_stop_or_target"})
        elif line == anchors["schedule"]:
            pending_decision = {**stamp(i), "setup": setup(i), "atr": float(loc["row"].atr)}
        elif line == anchors["entry"]:
            if pending_decision is None or active_trade is not None:
                raise ValueError("Observational gate: unmatched engine entry")
            pos = dict(loc["in_pos"])
            active_trade = {"trade_index": len(trades), "decision": pending_decision,
                            "fill": stamp(i), "entry_reference": loc["price_open"],
                            "entry_slipped": pos["entry"], "quantity": pos["qty"],
                            "entry_fee": pos["entry_fee"], "stop": pos["stop"],
                            "target": pos["target"], "entry_atr": loc["entry_atr"]}
            attempts[-1].update(disposition="filled", quantity=pos["qty"])
            pending_decision = None
        elif line == anchors["exit"]:
            if active_trade is None:
                raise ValueError("Observational gate: unmatched engine exit")
            pos = dict(loc["in_pos"])
            if loc["price_lo"] <= pos["stop"]:
                reason = "stop_open_gap" if loc["price_open"] < pos["stop"] else "stop"
            elif loc["price_hi"] >= pos["target"]:
                reason = "target"
            elif pos["age"] >= 64:
                reason = "time_64_bars"
            else:
                reason = "terminal_liquidation"
            trades.append({**active_trade, "exit": stamp(i), "exit_reference": loc["exit_at"],
                           "exit_slipped": loc["exit_price"], "exit_fee": loc["exit_fee"],
                           "net_pnl": loc["pnl"], "exposure_bars": pos["age"], "exit_reason": reason})
            active_trade = None
        elif line == anchors["decision"]:
            if attempts and attempts[-1]["fill_bar"]["bar_index"] == i + index_offset:
                if attempts[-1]["disposition"] == "pending_quantity_check":
                    attempts[-1]["disposition"] = "quantity_or_cash_denied"
                if attempts[-1]["disposition"] != "filled":
                    pending_decision = None
            if i not in event_indices:
                return local_trace
            row = frame.iloc[i]
            denials = []
            for name in admission_fields:
                if name not in row or row[name] != 1:
                    denials.append(name)
            if not row["close"] > row["open"]:
                denials.append("bullish_body")
            if "previous_close" in row and not row["close"] > row["previous_close"]:
                denials.append("fresh_close")
            if not math.isfinite(float(row["atr"])) or row["atr"] <= 0:
                denials.append("valid_atr")
            if loc["halted"]:
                admission = "drawdown_halt"
            elif loc["day_paused"]:
                admission = "daily_loss_pause"
            elif loc["in_pos"] is not None:
                admission = "position_occupied"
            elif loc["just_entered"]:
                admission = "same_bar_entry"
            elif i == len(frame) - 1:
                admission = "terminal_bar"
            elif not bool(signals[i]):
                admission = "signal_denied"
            elif denials:
                admission = "atr_denied" if "valid_atr" in denials else "signal_contract_mismatch"
            else:
                admission = "scheduled_next_open"
            events.append({**stamp(i), "setup": setup(i), "signal": bool(signals[i]),
                           "admission": admission, "denial_fields": denials,
                           "cost_inputs": {"close": _finite(row["close"]), "atr": _finite(row["atr"]),
                                           "span": cost_span(row),
                                           "screen_fee_bps": 25, "screen_slip_bps": 15}})
        return local_trace

    def global_trace(current, event, arg):
        return local_trace if event == "call" and current.f_code is target_code else None

    try:
        sys.settrace(global_trace)
        metrics = function(frame, signals, fee_bps=fee_bps, slip_bps=slip_bps, risk_variant=risk_variant)
    finally:
        sys.settrace(None)
    if active_trade is not None or len(trades) != metrics["closed_round_trips"]:
        raise ValueError("Observational gate: incomplete trade capture")
    return {"schema": "nexus.observed-backtest.v1", "source_binding": binding,
            "metrics": metrics, "trades": trades, "price_events": events, "entry_attempts": attempts,
            "unfilled_pending_decision": pending_decision,
            "simulation_costs": {"fee_bps": fee_bps, "slip_bps": slip_bps, "risk_variant": risk_variant},
            "research_only": True, "live_enabled": False}
