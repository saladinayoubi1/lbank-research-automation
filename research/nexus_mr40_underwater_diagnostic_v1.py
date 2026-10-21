"""Descriptive recovery risk from hash-pinned MR40 curves; no strategy execution."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

STEP = 14_400_000
CAPITAL = 10_000.0
ARCHIVE_SHA256 = "074ebdd7ca7712498194817d949b3c712884c9c0efff5d9d8fa4d6a677b11226"
PARENT_RESULT = "a2458859f9462208a6127d738e4a104de6dc066342436692394bc9048d12591b"
COHORTS = ("retrospective_42_months", "october_01_19", "august_october19_continuous")
PROFILES = ("normal", "stress")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def iso(stamp):
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()


def episode(peak_ms, peak, first_ms, trough_ms, trough, end_ms, recovered):
    return {"peak_close_ms": peak_ms, "first_underwater_close_ms": first_ms,
            "trough_close_ms": trough_ms, "recovery_close_ms": end_ms if recovered else None,
            "observation_end_ms": end_ms, "peak_equity_usdt": peak, "trough_equity_usdt": trough,
            "drawdown_pct": 100 * (1 - trough / peak),
            "peak_to_end_hours": (end_ms - peak_ms) / 3_600_000,
            "peak_to_trough_hours": (trough_ms - peak_ms) / 3_600_000,
            "recovered": recovered, "right_censored": not recovered}


def summarize(curve):
    """Last equal peak before a decline; observation times are four-hour closes."""
    if not curve:
        raise ValueError("empty curve")
    peak = CAPITAL
    peak_ms = curve[0]["bar_open_ms"]
    previous_ms = peak_ms - STEP
    episodes = []
    active = None
    underwater = 0
    below_initial = 0
    for row in curve:
        opened, value = row["bar_open_ms"], row["equity"]
        if (type(opened) is not int or opened != previous_ms + STEP
                or not math.isfinite(value) or value <= 0):
            raise ValueError("invalid or non-contiguous equity observations")
        previous_ms = opened
        closed = opened + STEP
        below_initial += value < CAPITAL
        if value >= peak:
            if active is not None:
                episodes.append(episode(active["peak_ms"], active["peak"], active["first_ms"],
                                        active["trough_ms"], active["trough"], closed, True))
                active = None
            peak, peak_ms = value, closed
        else:
            underwater += 1
            if active is None:
                active = {"peak_ms": peak_ms, "peak": peak, "first_ms": closed,
                          "trough_ms": closed, "trough": value}
            elif value < active["trough"]:
                active["trough_ms"], active["trough"] = closed, value
    end_ms = curve[-1]["bar_open_ms"] + STEP
    if active is not None:
        episodes.append(episode(active["peak_ms"], active["peak"], active["first_ms"],
                                active["trough_ms"], active["trough"], end_ms, False))
    worst = max(episodes, key=lambda x: x["drawdown_pct"], default=None)
    longest = max(episodes, key=lambda x: x["peak_to_end_hours"], default=None)
    closed_episodes = [x for x in episodes if x["recovered"]]
    recovered_longest = max((x["peak_to_end_hours"] for x in closed_episodes), default=None)
    latest = episodes[-1] if active is not None else None
    return {"bars": len(curve), "days": len(curve) / 6,
            "start_utc": iso(curve[0]["bar_open_ms"]), "end_exclusive_utc": iso(end_ms),
            "final_usdt": curve[-1]["equity"], "net_pnl_usdt": curve[-1]["equity"] - CAPITAL,
            "ending_drawdown_pct": 100 * (1 - curve[-1]["equity"] / peak),
            "maximum_close_drawdown_pct": worst["drawdown_pct"] if worst else 0.0,
            "underwater_close_observations": underwater,
            "underwater_close_observations_pct": 100 * underwater / len(curve),
            "below_initial_capital_close_observations": below_initial,
            "below_initial_capital_close_observations_pct": 100 * below_initial / len(curve),
            "drawdown_episodes": len(episodes), "recovered_episodes": len(closed_episodes),
            "open_episodes": int(active is not None),
            "longest_observed_peak_to_end_days": longest["peak_to_end_hours"] / 24 if longest else 0.0,
            "longest_completed_peak_to_recovery_days": recovered_longest / 24 if recovered_longest is not None else None,
            "current_underwater_elapsed_days": latest["peak_to_end_hours"] / 24 if latest else 0.0,
            "worst_episode": worst, "longest_observed_episode": longest, "episodes": episodes}


def independent_episodes(curve):
    """Separate Decimal prefix-max/run detector, not the streaming state machine."""
    values = [Decimal(str(row["equity"])) for row in curve]
    peaks = []
    running = Decimal(10000)
    for value in values:
        running = max(running, value)
        peaks.append(running)
    lower = [value < peak for value, peak in zip(values, peaks)]
    result = []
    index = 0
    while index < len(values):
        if not lower[index]:
            index += 1
            continue
        start = index
        while index < len(values) and lower[index]:
            index += 1
        recovered = index < len(values)
        trough = min(range(start, index), key=lambda i: values[i])
        peak_ms = curve[start - 1]["bar_open_ms"] + STEP if start else curve[0]["bar_open_ms"]
        end_ms = curve[index]["bar_open_ms"] + STEP if recovered else curve[-1]["bar_open_ms"] + STEP
        peak_value = peaks[start]
        result.append({"peak_close_ms": peak_ms, "first_underwater_close_ms": curve[start]["bar_open_ms"] + STEP,
                       "trough_close_ms": curve[trough]["bar_open_ms"] + STEP,
                       "recovery_close_ms": end_ms if recovered else None, "observation_end_ms": end_ms,
                       "peak_equity_usdt": float(peak_value), "trough_equity_usdt": float(values[trough]),
                       "drawdown_pct": float(100 * (peak_value - values[trough]) / peak_value),
                       "peak_to_end_hours": (end_ms - peak_ms) / 3_600_000,
                       "peak_to_trough_hours": (curve[trough]["bar_open_ms"] + STEP - peak_ms) / 3_600_000,
                       "recovered": recovered, "right_censored": not recovered})
    return result


def assert_oracle(actual, expected):
    if len(actual) != len(expected):
        raise AssertionError("independent drawdown episode count")
    error = 0.0
    for left, right in zip(actual, expected):
        for key in left:
            if key == "drawdown_pct":
                error = max(error, abs(left[key] - right[key]))
            elif left[key] != right[key]:
                raise AssertionError("independent recovery mismatch: " + key)
    if error > 1e-9:
        raise AssertionError("independent drawdown arithmetic")
    return error


def run(archive, output, source_sha):
    if output.exists():
        raise ValueError("refuse diagnostic overwrite")
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("exact committed diagnostic source required")
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("parent archive substitution")
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
        inventory = json.loads(bundle.read("INVENTORY.json"))
        for item in inventory["files"]:
            value = bundle.read(item["path"])
            if len(value) != item["bytes"] or hashlib.sha256(value).hexdigest() != item["sha256"]:
                raise ValueError("parent inventory substitution")
        prior = json.loads(bundle.read("recorded_results/results.json"))
        if prior["result_digest"] != PARENT_RESULT or digest({k: v for k, v in prior.items() if k != "result_digest"}) != PARENT_RESULT:
            raise ValueError("parent result substitution")
        manifest = json.loads(bundle.read("input_manifest.json"))
        curves = {(c, p): [] for c in COHORTS for p in PROFILES}
        for row in csv.DictReader(io.StringIO(bundle.read("recorded_results/equity_curve.csv").decode())):
            key = (row["cohort"], row["profile"])
            if row["scenario"] == "baseline_control" and key in curves:
                curves[key].append({"bar_open_ms": int(row["bar_open_ms"]), "equity": float(row["equity"]),
                                    "in_market": row["in_market"] == "True"})
    results, episodes, checks = [], [], []
    for (cohort, profile), curve in curves.items():
        expected = manifest["control_curves"][cohort + "/" + profile]
        if len(curve) != expected["bars"] or digest(curve) != expected["canonical_sha256"]:
            raise ValueError("frozen baseline curve substitution")
        matching = [r for r in prior["results"] if r["scenario"] == "baseline_control"
                    and r["cohort"] == cohort and r["profile"] == profile]
        if len(matching) != 1:
            raise ValueError("ambiguous baseline")
        stats = summarize(curve)
        max_error = assert_oracle(stats["episodes"], independent_episodes(curve))
        control = matching[0]
        if abs(stats["maximum_close_drawdown_pct"] - control["max_close_drawdown_pct"]) > 1e-9 or stats["final_usdt"] != control["final_usdt"]:
            raise AssertionError("diagnostic changes accepted baseline metrics")
        label = {"cohort": cohort, "profile": profile}
        results.append({**label, **{k: v for k, v in stats.items() if k != "episodes"}})
        episodes.extend({**label, "episode_index": i, **e} for i, e in enumerate(stats["episodes"]))
        checks.append({**label, "parent_curve_exact": True, "decimal_episode_oracle_exact": True,
                       "maximum_drawdown_difference_pct": max_error, "episodes": stats["drawdown_episodes"]})
    result = {"schema": "nexus.mr40-underwater-diagnostic.v1", "source_commit": source_sha,
              "parent_archive_sha256": ARCHIVE_SHA256, "parent_result_digest": PARENT_RESULT,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "classification": "DESCRIPTIVE_FROZEN_CURVES_NOT_NEW_BACKTEST_OR_INDEPENDENT_QUALIFICATION",
              "definitions": {"observation_time": "bar_open_ms + four hours, including accepted final equity mark",
                              "peak": "initial capital at window start; then latest close at or above prior peak; equality recovers",
                              "duration": "last equal peak to first recovery close, or observed end for a right-censored episode",
                              "underwater_share": "fraction of close observations strictly below running peak; not intrabar wall time",
                              "below_initial_share": "fraction of close observations strictly below 10000 USDT",
                              "right_censoring": "no observed recovery by sample end; future recovery time is unknown"},
              "new_market_data": False, "strategy_changes": False, "research_only": True,
              "live_enabled": False, "auto_demo": False, "orders": 0,
              "results": results, "episodes": episodes, "checks": checks}
    result["result_digest"] = digest(result)
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    summaries = [{k: v for k, v in r.items() if k not in ("worst_episode", "longest_observed_episode")} for r in results]
    for name, values in (("summary.csv", summaries), ("episodes.csv", episodes)):
        with (output / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(values)
    print(json.dumps({"result_digest": result["result_digest"], "curves": len(results), "episodes": len(episodes),
                      "exact_parent_curves": len(checks), "decimal_oracles": len(checks), "orders": 0}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    run(args.archive, args.output, args.source_sha)
