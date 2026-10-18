"""Reconstruct bounded PRE-ENTRY rule witnesses for V119's fixed recorded fills.

This is compatibility evidence, not recovery of an original emitted signal ID.
It never imports the engine, selects new entries, replays the signal universe or
recalculates economic outcomes. All ambiguity and incompatible entries survive.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from nexus_elliott_v119_accounting_qa import (
    ENGINE_SHA256, LEDGER_SHA256, PARTS, PROFILES, RESULT_DIGEST, SOURCE_SHAS, digest,
)

SCHEMA = "nexus.elliott-v119-recorded-entry-prefix-witness-qa.v1"
PRICE_TOLERANCE = Decimal("0.00000002")  # Published bracket prices have 8 decimals.


class EntryWitnessError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EntryWitnessError(message)


def number(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise EntryWitnessError("invalid source price") from exc
    require(result.is_finite(), "nonfinite source price")
    return result


def stamp(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def available_after(bar):
    time = datetime.fromisoformat(stamp(bar["timestamp"]).replace("Z", "+00:00"))
    require(time.tzinfo is not None, "UTC source timestamp required")
    return (time + timedelta(minutes=15)).isoformat()


def entry_witnesses(bars, *, entry_index, partition_start, entry_mid, stop, target, config):
    """Check only one recorded entry's bounded closed-bar prefix.

    Earliest W2 center = entry - 2 - horizon - right; earliest W0 is a
    further max_pattern_span bars back. Three left neighbors authenticate W0.
    Even the entry bar's high/low/close are never read. No best witness is chosen.
    """
    require(type(entry_index) is int and type(partition_start) is int
            and 0 <= partition_start <= entry_index < len(bars), "entry outside source partition")
    left, right = config["pivot_left"], config["pivot_right"]
    span, horizon = config["max_pattern_span_bars"], config["retest_horizon_bars"]
    first_center = max(left, entry_index - 2 - horizon - right - span)
    first_bar = first_center - left
    require(first_bar < entry_index, "insufficient closed prefix")
    past = {}
    prefix = []
    for index in range(first_bar, entry_index):
        raw = bars[index]
        row = {k: number(raw[k]) for k in ("open", "high", "low", "close")}
        require(0 < row["low"] <= min(row["open"], row["close"])
                and row["high"] >= max(row["open"], row["close"]), "invalid prefix OHLC")
        row["timestamp"] = stamp(raw["timestamp"])
        past[index] = row
        prefix.append({"index": index, **{k: str(v) for k, v in row.items()}})
    events = []
    for center in range(first_center, entry_index - right):
        neighbors = [past[j] for j in range(center - left, center + right + 1) if j != center]
        high = all(past[center]["high"] > p["high"] for p in neighbors)
        low = all(past[center]["low"] < p["low"] for p in neighbors)
        if high != low:  # Preserve all strict events; dual extremes have no order.
            events.append((center, "HIGH" if high else "LOW", past[center]["high" if high else "low"]))
    mid, recorded_stop, recorded_target = map(number, (entry_mid, stop, target))
    witnesses = []
    for w0, w1, w2 in zip(events, events[1:], events[2:]):
        c0, c1, c2 = w0[0], w1[0], w2[0]
        known, retest = c2 + right, entry_index - 2
        if ((w0[1], w1[1], w2[1]) != ("LOW", "HIGH", "LOW")
                or c2 - c0 > span or known < partition_start
                or not known < retest <= known + horizon):
            continue
        p0, p1, p2 = w0[2], w1[2], w2[2]
        leg = p1 - p0
        if leg <= 0 or leg < number(config["min_wave1_relative_move"]) * p0 or p2 <= p0:
            continue
        retrace = (p1 - p2) / leg
        if not number(config["wave2_retrace_min"]) <= retrace <= number(config["wave2_retrace_max"]):
            continue
        expected_stop = p2 * (1 - number(config["w2_stop_buffer_fraction"]))
        if (not p0 < expected_stop < mid < p1
                or abs(expected_stop - recorded_stop) > PRICE_TOLERANCE):
            continue
        expected_target = min(p1, mid + number(config["target_r_multiple"]) * (mid - expected_stop))
        if (abs(expected_target - recorded_target) > PRICE_TOLERANCE
                or (expected_target - mid) / (mid - expected_stop) < number(config["min_structural_reward_risk"])):
            continue
        first_reclaim = None
        for index in range(known + 1, retest + 1):
            bar = past[index]
            if bar["low"] < p2:
                break
            if (bar["low"] <= p2 + number(config["support_near_leg_fraction"]) * leg
                    and bar["close"] >= p2 + number(config["reclaim_leg_fraction"]) * leg):
                following = past[index + 1]
                if following["low"] < p2:
                    break
                if following["open"] < following["close"] < p1 and following["close"] > bar["high"]:
                    first_reclaim = index
                    break
        if first_reclaim != retest:
            continue
        core = {
            "pivot_w0_center": c0, "pivot_w1_center": c1, "pivot_w2_center": c2,
            "w2_known_after_closed_index": known, "retest_completed_index": retest,
            "reclaim_completed_index": entry_index - 1, "entry_index": entry_index,
            "w0_low": str(p0), "w1_high": str(p1), "w2_low": str(p2),
            "structural_stop": str(expected_stop), "structural_target": str(expected_target),
            "w2_available_utc": available_after(past[known]),
            "retest_available_utc": available_after(past[retest]),
            "reclaim_available_utc": available_after(past[entry_index - 1]),
            "entry_mid_from_original_ledger": str(mid),
            "prefix_first_index": first_bar, "prefix_last_index": entry_index - 1,
            "closed_prefix_sha256": digest(prefix),
        }
        witnesses.append({**core, "reconstructed_witness_sha256": digest(core)})
    return witnesses


def audit_entries(ledger, frames):
    rows, counts = [], Counter()
    n = ledger["source_closed_bars_per_asset"]
    bounds = ((64, int(n * .6)), (int(n * .6), int(n * .8)), (int(n * .8), n))
    for part, (start, end) in zip(PARTS, bounds):
        profiles = ledger["results"][part]["profiles"]
        def identities(profile):
            return [(t["symbol"], t["entry_index"], t["exit_index"], t["entry_mid"],
                     t["structural_stop"], t["structural_target"]) for t in profiles[profile]["trades"]]
        require(identities("conservative") == identities("stress"), "cost profiles have different fixed paths")
        for trade in profiles["conservative"]["trades"]:
            require(start <= trade["entry_index"] < end, "recorded entry outside frozen partition")
            witnesses = entry_witnesses(frames[trade["symbol"]], entry_index=trade["entry_index"],
                partition_start=start, entry_mid=trade["entry_mid"], stop=trade["structural_stop"],
                target=trade["structural_target"], config=ledger["input_frozen_config"])
            status = "incompatible" if not witnesses else "unique_compatible_witness" if len(witnesses) == 1 else "multiple_compatible_witnesses"
            counts[status] += 1
            rows.append({"part": part, "symbol": trade["symbol"], "entry_index": trade["entry_index"],
                         "exit_index": trade["exit_index"], "status": status,
                         "compatible_witness_count": len(witnesses), "witnesses": witnesses})
    return rows, dict(sorted(counts.items()))


def run_audit(ledger_path, market_root, engine_path):
    import pandas as pd

    require(hashlib.sha256(ledger_path.read_bytes()).hexdigest() == LEDGER_SHA256, "original ledger byte identity changed")
    require(hashlib.sha256(engine_path.read_bytes()).hexdigest() == ENGINE_SHA256, "frozen engine changed")
    ledger = json.loads(ledger_path.read_bytes())
    require(ledger["result_digest"] == RESULT_DIGEST
            and digest({k: v for k, v in ledger.items() if k != "result_digest"}) == RESULT_DIGEST,
            "original result digest changed")
    frames, time_grid = {}, None
    for symbol, sha in SOURCE_SHAS.items():
        path = market_root / (symbol.lower() + "_usdt") / "minute15.parquet"
        require(hashlib.sha256(path.read_bytes()).hexdigest() == sha, "physical source SHA256 changed")
        frame = pd.read_parquet(path)
        require(len(frame) == 128544 and (frame["symbol"] == symbol.lower() + "_usdt").all()
                and (frame["timeframe"] == "minute15").all(), "physical source identity/coverage changed")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        times = frame["timestamp"]
        require((times.diff().iloc[1:] == pd.Timedelta(minutes=15)).all()
                and times.iloc[0].isoformat() == ledger["source_start_utc"]
                and times.iloc[-1].isoformat() == ledger["source_end_utc"], "source chronology changed")
        require(time_grid is None or times.equals(time_grid), "source peer grid changed")
        time_grid = times
        frames[symbol] = frame.to_dict("records")
    rows, counts = audit_entries(ledger, frames)
    require(len(rows) == 77, "original recorded entry coverage changed")
    core = {
        "schema": SCHEMA, "audit_completed": True, "ledger_raw_sha256": LEDGER_SHA256,
        "entry_checker_raw_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "result_digest": RESULT_DIGEST, "engine_raw_sha256": ENGINE_SHA256, "source_shas": SOURCE_SHAS,
        "recorded_unique_entries_checked": len(rows), "costed_ledger_rows_represented": 154,
        "counts": counts, "all_recorded_entries_compatible": counts.get("incompatible", 0) == 0,
        "price_comparison_tolerance": str(PRICE_TOLERANCE), "entries": rows,
        "evidence_kind": "retrospectively_reconstructed_closed_prefix_compatibility",
        "fixed_recorded_entry_prefixes_checked": True,
        "all_source_signal_universe_regenerated": False, "new_entry_selection_performed": False,
        "historical_backtest_reexecuted": False, "economic_result_recomputed": False,
        "original_signal_event_identity_verified": False,
        "signal_to_entry_causality_independently_verified": False,
        "full_elliott_wave_count_verified": False, "independent_future_holdout": False,
        "paper_eligible": False, "automatic_demo_promotion": False, "live_enabled": False, "orders": 0,
        "disposition": "HISTORICAL_NEGATIVE_DO_NOT_RETUNE",
    }
    return {**core, "entry_witness_qa_digest": digest(core)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("ledger", "market-root", "engine", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    inputs = {args.ledger.resolve(), args.engine.resolve()} | {
        (args.market_root / (symbol.lower() + "_usdt") / "minute15.parquet").resolve() for symbol in SOURCE_SHAS}
    require(args.output.resolve() not in inputs, "output cannot overwrite frozen inputs")
    report = run_audit(args.ledger, args.market_root, args.engine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "entries"}, sort_keys=True))


if __name__ == "__main__":
    main()
