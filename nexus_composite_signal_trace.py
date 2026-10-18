"""Capture generated signals before replay and retain the independent fill trace.

This records batch-replay output, not a live/prospective observation. Financial
producer fills are unavailable; the linked fills come from the distinct Decimal
oracle already used by VAL-40. QA replays and compares the complete artifact.
The verifier is standard-library only and does not generate signals or trades.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
from typing import Any

SCHEMA = "nexus.composite-emitted-signal-trace.v1"
STEP_MS = 900_000
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
OUTCOMES = {"ENTRY_FILLED", "INVALID_STOP_GEOMETRY", "NO_COLLATERAL_CAPACITY",
            "DRAWDOWN_HALT", "DAILY_LOSS_PAUSE", "POSITION_OCCUPIED",
            "ENTRY_BAR_REARM_SUPPRESSED", "TERMINAL_NO_NEXT_OPEN",
            "UNAVAILABLE_POSITIVE_PRIOR_RANGE"}
BOUNDARIES = {"batch_replay_not_prospective_capture": True,
              "financial_producer_emitted_fills_available": False,
              "independent_signal_equations_verified": False,
              "higher_timeframe_asof_independently_verified": False,
              "paper_execution_authority": False, "live_trading_authority": False}


class SignalTraceError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _scalar(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if type(value) is float and not math.isfinite(value):
        return {"nonfinite_feature": str(value)}
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise SignalTraceError("unsupported decision feature value")


def capture_signals(frame: Any, signals: Any, *, candidate: Mapping[str, Any],
                    source_sha: str, symbol: str, datasets: Mapping[str, Any],
                    peer_binding: str | None) -> dict:
    """Called immediately after signal_for, before either cost-profile backtest.

    Hash every decision-feature prefix, including false-signal rows. Later bars
    cannot rewrite an earlier event ID. Whole-window canonical dataset bindings
    are retained separately; an event ID is not a provider-authentication proof.
    """
    if len(frame) != len(signals) or len(frame) < 2 or len(set(frame.columns)) != len(frame.columns):
        raise SignalTraceError("unaligned signal/decision frame")
    columns = list(frame.columns)
    bits, events, times = [], [], []
    chain = digest({"symbol": symbol, "columns": columns})
    identity = {"candidate_digest": candidate["candidate_digest"], "source_sha": source_sha,
                "symbol": symbol, "strategy_config_digest": digest(candidate["strategy_config"])}
    for i, values in enumerate(frame.itertuples(index=False, name=None)):
        row = dict(zip(columns, values))
        at = row.get("decision_at")
        if getattr(at, "tzinfo", None) is None or at.utcoffset().total_seconds() != 0:
            raise SignalTraceError("decision timestamps must be UTC")
        at_ms = int(at.value // 1_000_000)
        if at.value % 1_000_000 or at_ms % STEP_MS or (times and at_ms != times[-1] + STEP_MS):
            raise SignalTraceError("noncontiguous closed 15m decision clock")
        times.append(at_ms)
        emitted = _scalar(signals[i])
        if type(emitted) is not bool:
            raise SignalTraceError("signal capture requires an explicit boolean mask")
        bits.append("1" if emitted else "0")
        chain = digest({"previous_prefix_sha256": chain,
                        "features": {k: _scalar(v) for k, v in row.items()}})
        if emitted:
            core = {**identity, "signal_bar": i, "available_at_ms": at_ms,
                    "earliest_entry_open_ms": at_ms, "decision_prefix_sha256": chain}
            events.append({**core, "event_id": digest(core)})
    core = {"identity": identity, "datasets_digest": digest(dict(datasets)),
            "peer_minute15_binding_sha256": peer_binding,
            "decision_grid": {"rows": len(times), "first_close_ms": times[0],
                              "last_close_ms": times[-1]},
            "signal_mask": "".join(bits), "events": events,
            "capture_phase": "after_signal_generation_before_cost_profile_replay"}
    return {**core, "capture_digest": digest(core)}


def bind_fill_audits(capture: Mapping[str, Any], audits: Mapping[str, Any]) -> dict:
    by_bar = {e["signal_bar"]: e["event_id"] for e in capture["events"]}
    profiles = {}
    for name, audit in audits.items():
        def linked(row):
            try:
                return {**row, "event_id": by_bar[row["signal_bar"]]}
            except KeyError as exc:
                raise SignalTraceError("oracle refers to a signal that was not emitted") from exc
        profiles[name] = {"decisions": [linked(r) for r in audit["signal_decisions"]],
                          "fills": [linked(r) for r in audit["fills"]]}
    core = {"schema_version": SCHEMA, "capture": dict(capture),
            "independent_fill_audits": profiles, **BOUNDARIES}
    return {**core, "trace_digest": digest(core)}


def _number(value: Any) -> Decimal:
    try:
        if type(value) not in (str, int, float):
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError()
        return result
    except (ValueError, InvalidOperation) as exc:
        raise SignalTraceError("nonfinite independent fill value") from exc


def verify_trace(trace: Any, *, candidate: Mapping[str, Any], source_sha: str,
                 symbol: str, datasets: Mapping[str, Any], peer_binding: str | None,
                 profiles: list[dict]) -> None:
    """Check stored coverage/identity/chronology; source replay remains QA's job."""
    if (type(trace) is not dict or set(trace) != {"schema_version", "capture", "independent_fill_audits",
                                                "trace_digest", *BOUNDARIES}
        or trace.get("schema_version") != SCHEMA
        or any(trace.get(k) is not v for k, v in BOUNDARIES.items())
        or trace.get("trace_digest") != digest({k: v for k, v in trace.items() if k != "trace_digest"})):
        raise SignalTraceError("signal trace digest or scope is invalid")
    cap = trace["capture"]
    identity = {"candidate_digest": candidate["candidate_digest"], "source_sha": source_sha,
                "symbol": symbol, "strategy_config_digest": digest(candidate["strategy_config"])}
    if (not HEX64.fullmatch(str(identity["candidate_digest"])) or not HEX40.fullmatch(str(source_sha))
        or symbol not in {"BTCUSDT", "ETHUSDT"}
        or type(cap) is not dict or set(cap) != {"identity", "datasets_digest", "peer_minute15_binding_sha256",
                                                "decision_grid", "signal_mask", "events", "capture_phase", "capture_digest"}
        or cap.get("identity") != identity or cap.get("datasets_digest") != digest(dict(datasets))
        or cap.get("peer_minute15_binding_sha256") != peer_binding
        or cap.get("capture_phase") != "after_signal_generation_before_cost_profile_replay"
        or cap.get("capture_digest") != digest({k: v for k, v in cap.items() if k != "capture_digest"})):
        raise SignalTraceError("signal capture does not bind this evaluation")
    grid, mask, events = cap["decision_grid"], cap["signal_mask"], cap["events"]
    source = datasets["minute15"]
    if (type(grid) is not dict or set(grid) != {"rows", "first_close_ms", "last_close_ms"}
        or any(type(v) is not int for v in grid.values()) or grid["rows"] < 2
        or grid["last_close_ms"] - grid["first_close_ms"] != (grid["rows"] - 1) * STEP_MS
        or grid["first_close_ms"] % STEP_MS or grid["last_close_ms"] % STEP_MS
        or grid["first_close_ms"] != source["first_open_time_ms"] + STEP_MS
        or grid["last_close_ms"] != source["last_open_time_ms"] + STEP_MS
        or grid["rows"] != source["row_count"]
        or type(mask) is not str or len(mask) != grid["rows"] or set(mask) - {"0", "1"}
        or type(events) is not list or len(events) != mask.count("1")):
        raise SignalTraceError("signal mask or physical decision grid is invalid")
    expected_bars = [i for i, bit in enumerate(mask) if bit == "1"]
    by_bar = {}
    for bar, event in zip(expected_bars, events):
        at = grid["first_close_ms"] + bar * STEP_MS
        if (type(event) is not dict or set(event) != {*identity, "signal_bar", "available_at_ms",
                                                     "earliest_entry_open_ms", "decision_prefix_sha256", "event_id"}
            or any(event.get(k) != v for k, v in identity.items())
            or type(event.get("signal_bar")) is not int or event["signal_bar"] != bar
            or type(event.get("available_at_ms")) is not int or event["available_at_ms"] != at
            or type(event.get("earliest_entry_open_ms")) is not int or event["earliest_entry_open_ms"] != at
            or not HEX64.fullmatch(str(event.get("decision_prefix_sha256")))
            or event.get("event_id") != digest({k: v for k, v in event.items() if k != "event_id"})):
            raise SignalTraceError("missing, reordered or altered emitted signal")
        by_bar[bar] = event["event_id"]
    audits = trace["independent_fill_audits"]
    if type(audits) is not dict or set(audits) != {"conservative", "stress"}:
        raise SignalTraceError("both independent fill profiles are required")
    for profile in profiles:
        audit = audits[profile["profile"]]
        if type(audit) is not dict or set(audit) != {"decisions", "fills"}:
            raise SignalTraceError("invalid independent fill audit")
        decisions, fills = audit["decisions"], audit["fills"]
        if type(decisions) is not list or len(decisions) != len(events) or type(fills) is not list:
            raise SignalTraceError("each emitted signal requires one disposition per cost profile")
        admitted = set()
        for bar, decision in zip(expected_bars, decisions):
            if (type(decision) is not dict or set(decision) != {"signal_bar", "event_id", "outcome"}
                or type(decision.get("signal_bar")) is not int or decision["signal_bar"] != bar
                or decision.get("event_id") != by_bar[bar] or decision.get("outcome") not in OUTCOMES):
                raise SignalTraceError("signal disposition is missing, duplicated or unbound")
            if decision["outcome"] == "ENTRY_FILLED":
                admitted.add(bar)
        active, bought, total_pnl, previous_bar = None, set(), Decimal(0), -1
        for fill in fills:
            if type(fill) is not dict:
                raise SignalTraceError("independent fill must be an object")
            bar, sig = fill.get("bar"), fill.get("signal_bar")
            side = fill.get("side")
            keys = {"bar", "signal_bar", "side", "price", "quantity", "fee", "event_id"}
            if side == "SELL":
                keys |= {"pnl", "reason"}
            if (set(fill) != keys or type(bar) is not int or not previous_bar <= bar < grid["rows"]
                or type(sig) is not int or sig not in admitted or fill.get("event_id") != by_bar[sig]
                or _number(fill["price"]) <= 0 or _number(fill["quantity"]) <= 0 or _number(fill["fee"]) < 0):
                raise SignalTraceError("fill is outside the emitted event/closed decision grid")
            previous_bar = bar
            quantity, price, fee = (_number(fill[k]) for k in ("quantity", "price", "fee"))
            expected_fee = quantity * price * _number(profile["fee_bps"]) / Decimal(10000)
            if abs(fee - expected_fee) > Decimal("0.000000000001"):
                raise SignalTraceError("independent fill fee disagrees with the bound cost profile")
            if side == "BUY" and active is None and sig not in bought and bar == sig + 1:
                active = (sig, fill["quantity"], price, fee)
                bought.add(sig)
            elif (side == "SELL" and active is not None and active[:2] == (sig, fill["quantity"])
                  and fill["reason"] in {"stop", "target", "time_or_terminal"}):
                net = quantity * (price - active[2]) - active[3] - fee
                if abs(net - _number(fill["pnl"])) > Decimal("0.000000000001"):
                    raise SignalTraceError("independent exit PnL disagrees with its paired fill")
                total_pnl += _number(fill["pnl"])
                active = None
            else:
                raise SignalTraceError("missing next-open entry or unmatched independent exit")
        if (active is not None or bought != admitted or len(fills) != 2 * profile["closed_round_trips"]
            or abs(total_pnl - _number(profile["net_pnl_usdt"])) > Decimal("0.0001")):
            raise SignalTraceError("signal/fill coverage or aggregate PnL disagrees")
