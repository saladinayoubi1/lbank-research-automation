"""Frozen-path MR40 cost and ex-post missed-winner audit; research only."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import platform
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path

CAPITAL = 10_000.0
STEP = 14_400_000
PROTOCOL_COMMIT = "0f58362edf77b9484466a4a49d2b6a754c777b9e"
PROTOCOL_SHA256 = "d40d67433d818ab278b143d95f0c325b54381b1b7323a063b1f2e62f9a64228f"
MANIFEST_SHA256 = "af978c277caddefc99bb3419d13a6ef4360562781d8e7a787b126dedc537db7f"
OLD_INPUT = "fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
OLD_RESULT = "959832aa111ba6bbab7a899547a7d4e031a0f3cd0a283de30397635f1ba5f118"
OCT_RESULT = "3209320f841a694f7711a365e93a0fd1e6777f31b1dd250c0c44f3ab630ca7ac"
EXTENSION = "17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def check_digest(value, key, expected):
    if value.get(key) != expected or digest({k: v for k, v in value.items() if k != key}) != expected:
        raise ValueError("substituted " + key)


def verified_file(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("substituted file: " + path.name)
    return raw


def closed_pairs(record, rows):
    """Accept complete, chronological lag-one natural exits only."""
    fills, positions = record["fills"], record["positions"]
    if (record["terminal_exits"] != 0 or len(fills) != 2 * len(positions)
            or record["closed_positions"] != len(positions)
            or record["fill_count"] != len(fills) or not positions):
        raise ValueError("incomplete frozen round trips")
    pairs = []
    previous_exit = -1
    for index, position in enumerate(positions):
        buy, sell = fills[2 * index:2 * index + 2]
        if (buy["side"], sell["side"]) != ("buy", "sell"):
            raise ValueError("malformed fill pair")
        for fill in (buy, sell):
            bar, signal = fill["bar_index"], fill["signal_index"]
            if (type(bar) is not int or type(signal) is not int
                    or not 0 <= signal < bar < len(rows) or bar - signal != 1
                    or fill["reason"] != "previous_closed_bar_signal"
                    or fill["fill_ms"] != rows[bar][0]
                    or fill["signal_available_ms"] != rows[signal][0] + STEP
                    or fill["signal_available_ms"] > fill["fill_ms"]
                    or not math.isfinite(fill["reference"]) or fill["reference"] <= 0
                    or fill["reference"] != float(rows[bar][1])):
                raise ValueError("invalid frozen fill identity or reference")
        if not previous_exit < buy["bar_index"] < sell["bar_index"]:
            raise ValueError("overlapping or reversed positions")
        if (position["entry_ms"] != buy["fill_ms"] or position["exit_ms"] != sell["fill_ms"]
                or position["entry_index"] != buy["bar_index"]
                or position["exit_index"] != sell["bar_index"]
                or position["exit_reason"] != sell["reason"]
                or position["entry_cash"] <= 0 or position["exit_cash"] <= 0):
            raise ValueError("position and fill identities differ")
        factor = position["exit_cash"] / position["entry_cash"]
        if abs(100 * (factor - 1) - position["return_pct"]) > 1e-10:
            raise ValueError("recorded position return mismatch")
        pairs.append({"position_index": index, "entry_ms": buy["fill_ms"],
                      "exit_ms": sell["fill_ms"], "entry_index": buy["bar_index"],
                      "exit_index": sell["bar_index"], "buy_signal_index": buy["signal_index"],
                      "sell_signal_index": sell["signal_index"],
                      "entry_reference": buy["reference"], "exit_reference": sell["reference"],
                      "recorded_factor": factor, "net_return_pct": position["return_pct"]})
        previous_exit = sell["bar_index"]
    return pairs


def fixed_mask(size, pairs):
    """Encode selected frozen intervals; selection itself can be ex-post."""
    target = [0] * size
    previous_end = -1
    for pair in pairs:
        start, end = pair["buy_signal_index"], pair["sell_signal_index"]
        if not previous_end < start < end < size:
            raise ValueError("invalid fixed intervals")
        target[start:end] = [1] * (end - start)
        previous_end = end
    return target


def best_positive(pairs, count):
    ordered = sorted((p for p in pairs if p["net_return_pct"] > 0),
                     key=lambda p: (-p["net_return_pct"], p["entry_ms"]))
    if count < 0 or count > len(ordered):
        raise ValueError("insufficient positive positions")
    return ordered[:count]


def cost_factor(fee_bps, slippage_bps):
    d = Decimal
    fee, slip = d(str(fee_bps)) / 10000, d(str(slippage_bps)) / 10000
    if min(fee, slip) < 0 or max(fee, slip) >= 1:
        raise ValueError("invalid per-side costs")
    return ((1 - fee) / (1 + fee)) * ((1 - slip) / (1 + slip))


def independent_product(pairs, fee_bps, slippage_bps):
    """High-precision price-ratio product, independent of engine fill arithmetic."""
    with localcontext() as ctx:
        ctx.prec = 50
        value = Decimal(10000)
        friction = cost_factor(fee_bps, slippage_bps)
        for pair in pairs:
            value *= Decimal(str(pair["exit_reference"])) / Decimal(str(pair["entry_reference"])) * friction
        return float(value)


def cost_boundary(pairs):
    if not pairs:
        raise ValueError("no round trips for boundary")
    with localcontext() as ctx:
        ctx.prec = 50
        d = Decimal
        gross = d(1)
        for pair in pairs:
            gross *= d(str(pair["exit_reference"])) / d(str(pair["entry_reference"]))
        required = (-gross.ln() / len(pairs)).exp()
        fee = d(25) / 10000
        slip = d(15) / 10000
        fee_ratio = required / ((1 - slip) / (1 + slip))
        slip_ratio = required / ((1 - fee) / (1 + fee))
        break_fee = (1 - fee_ratio) / (1 + fee_ratio) * 10000
        break_slip = (1 - slip_ratio) / (1 + slip_ratio) * 10000
        effective = (1 - required) / (1 + required) * 10000
        stress_effective = (fee + slip) / (1 + fee * slip) * 10000
        return {"closed_positions": len(pairs), "gross_price_ratio_product": float(gross),
                "zero_cost_final_usdt": float(10000 * gross),
                "break_even_fee_bps_at_slippage_15bps": float(break_fee),
                "break_even_slippage_bps_at_fee_25bps": float(break_slip),
                "fee_headroom_bps_above_25": float(break_fee - 25),
                "slippage_headroom_bps_above_15": float(break_slip - 15),
                "break_even_effective_cost_bps_per_side": float(effective),
                "stress_effective_cost_bps_per_side": float(stress_effective),
                "effective_cost_definition": "c=(fee+slip)/(1+fee*slip), components in fractions"}


def write_csv(path, records):
    if not records:
        raise ValueError("empty output table")
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)


def load_inputs(root):
    manifest = json.loads(verified_file(root / "input_manifest.json", MANIFEST_SHA256))
    data = {rel: verified_file(root / rel, item["sha256"]) for rel, item in manifest["files"].items()}
    previous = json.loads(data["inputs/prepared_inputs.json"])
    extension = json.loads(data["inputs/october_input_extension.json"])
    candidate = json.loads(data["inputs/candidate_results.json"])
    october = json.loads(data["inputs/october_results.json"])
    check_digest(previous, "input_digest", OLD_INPUT)
    check_digest(extension, "digest", EXTENSION)
    check_digest(candidate, "result_digest", OLD_RESULT)
    check_digest(october, "result_digest", OCT_RESULT)
    if (len(previous["rows"]) != 8400 or len(extension["rows"]) != 114
            or extension["base_input_digest"] != OLD_INPUT
            or previous["rows"][-1][0] + STEP != extension["rows"][0][0]):
        raise ValueError("substituted price-frame boundary")
    rows = previous["rows"] + extension["rows"]
    if digest(rows) != october["combined_rows_digest"]:
        raise ValueError("changed follow-up prices")
    path = root / "inputs" / "nexus_mean_reversion_40_m2_retest_v1.py"
    spec = importlib.util.spec_from_file_location("mr40_robustness_frozen_engine", path)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    engine.validate_frame(rows)
    return manifest, rows, candidate, october, engine


def run(root, source_sha, protocol_sha):
    if (root / "results").exists():
        raise ValueError("refuse results overwrite")
    if (len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha)
            or protocol_sha != PROTOCOL_COMMIT):
        raise ValueError("exact committed source and protocol required")
    policy = json.loads(verified_file(root / "study_contract.json", PROTOCOL_SHA256))
    manifest, rows, candidate, october, engine = load_inputs(root)
    indices = {row[0]: i for i, row in enumerate(rows)}
    indices[rows[-1][0] + STEP] = len(rows)
    records, checks, boundaries = [], [], []
    summaries, fills, positions, curves, monthly = [], [], [], [], []

    def replay(cohort, scenario, profile, pairs, original, fee, slip, omitted=()):
        start = indices[engine.ms(original["start_utc"])]
        end = indices[engine.ms(original["end_exclusive_utc"])]
        if any(not start <= p["entry_index"] < p["exit_index"] < end for p in pairs):
            raise ValueError("position outside evaluation window")
        target = fixed_mask(len(rows), pairs)
        actual = engine.simulate(rows, target, start, end, fee, slip, lag=1)
        expected_times = [(p["entry_ms"], p["exit_ms"]) for p in pairs]
        if [(p["entry_ms"], p["exit_ms"]) for p in actual["positions"]] != expected_times:
            raise AssertionError("scenario changes retained trade times")
        oracle = engine.independent_accounting(rows, target, start, end, fee, slip, lag=1)
        decimal_error = max(abs(p["equity"] - q) for p, q in zip(actual["equity_curve"], oracle["equity"]))
        product = independent_product(pairs, fee, slip)
        product_error = abs(product - actual["metrics"]["final_usdt"])
        if (len(actual["equity_curve"]) != len(oracle["equity"])
                or decimal_error > 1e-7 or product_error > 1e-7
                or actual["metrics"]["fills"] != oracle["fill_count"]):
            raise AssertionError("independent account or product mismatch")
        label = {"cohort": cohort, "scenario": scenario, "profile": profile}
        stats = dict(actual["metrics"])
        stats["fill_count"] = stats.pop("fills")
        omitted_info = [{"position_index": p["position_index"], "entry_ms": p["entry_ms"],
                         "exit_ms": p["exit_ms"], "baseline_net_return_pct": p["net_return_pct"]} for p in omitted]
        record = {**label, "fee_bps_per_side": fee, "slippage_bps_per_side": slip,
                  "lag_bars": 1, "omitted_count": len(omitted), **stats,
                  "independent_product_final_usdt": product, "omitted_positions": omitted_info,
                  "positions": actual["positions"], "fills": actual["fills"]}
        check = {**label, "maximum_decimal_equity_error_usdt": decimal_error,
                 "independent_product_error_usdt": product_error,
                 "retained_timing_exact": True, "baseline_curve_exact": None,
                 "break_even_pnl_error_usdt": None}
        if scenario == "baseline_control":
            for key in ("final_usdt", "max_close_drawdown_pct", "closed_positions", "terminal_exits"):
                if abs(stats[key] - original[key]) > 1e-9:
                    raise AssertionError("frozen baseline metric differs: " + key)
            expected = manifest["control_curves"][cohort + "/" + profile]
            if len(actual["equity_curve"]) != expected["bars"] or digest(actual["equity_curve"]) != expected["canonical_sha256"]:
                raise AssertionError("frozen baseline equity differs")
            check["baseline_curve_exact"] = True
        if scenario.startswith("break_even_"):
            check["break_even_pnl_error_usdt"] = abs(stats["net_pnl_usdt"])
            if check["break_even_pnl_error_usdt"] > 1e-7:
                raise AssertionError("closed-form root does not break even")
        records.append(record)
        checks.append(check)
        summaries.append({k: v for k, v in record.items() if k not in ("positions", "fills", "omitted_positions")})
        for destination, values in ((fills, actual["fills"]), (positions, actual["positions"]),
                                    (curves, actual["equity_curve"]), (monthly, actual["monthly_attribution"])):
            destination.extend({**label, **item} for item in values)
        print(json.dumps({**label, "pnl_usdt": stats["net_pnl_usdt"],
                          "close_dd_pct": stats["max_close_drawdown_pct"],
                          "closed_positions": stats["closed_positions"]}), flush=True)

    for cohort in policy["cohorts"]:
        cohort_id = cohort["id"]
        source = candidate if cohort_id == "retrospective_42_months" else october
        profile_pairs = {}
        originals = {}
        for profile in policy["profiles"]:
            matching = [r for r in source["results"] if r["cohort"] == cohort_id
                        and r["profile"] == profile["id"] and r.get("strategy", "momentum30") == "momentum30"]
            if len(matching) != 1:
                raise ValueError("ambiguous frozen result")
            original = matching[0]
            pairs = closed_pairs(original, rows)
            profile_pairs[profile["id"]] = pairs
            originals[profile["id"]] = original
            replay(cohort_id, "baseline_control", profile["id"], pairs, original,
                   profile["fee_bps"], profile["slippage_bps"])
            for count in cohort["omitted_best_counts"]:
                omitted = best_positive(pairs, count)
                selected = {p["position_index"] for p in omitted}
                kept = [p for p in pairs if p["position_index"] not in selected]
                replay(cohort_id, "omit_best_" + str(count), profile["id"], kept, original,
                       profile["fee_bps"], profile["slippage_bps"], omitted)
        normal, stress = profile_pairs["normal"], profile_pairs["stress"]
        identity_keys = ("entry_ms", "exit_ms", "entry_reference", "exit_reference")
        if [[p[k] for k in identity_keys] for p in normal] != [[p[k] for k in identity_keys] for p in stress]:
            raise AssertionError("cost profile changes frozen trade path")
        boundary = {"cohort": cohort_id, **cost_boundary(normal)}
        boundaries.append(boundary)
        adverse = policy["cost_analysis"]["fixed_adverse_case"]
        replay(cohort_id, "fixed_extra_slippage", "fee25_slip20", normal, originals["normal"],
               adverse["fee_bps"], adverse["slippage_bps"])
        root_fee = boundary["break_even_fee_bps_at_slippage_15bps"]
        root_slip = boundary["break_even_slippage_bps_at_fee_25bps"]
        replay(cohort_id, "break_even_fee", "root_fee_fixed_slip15", normal, originals["normal"], root_fee, 15)
        replay(cohort_id, "break_even_slippage", "root_slip_fixed_fee25", normal, originals["normal"], 25, root_slip)

    result = {"schema": "nexus.mr40-fixed-path-robustness-results.v1", "code_commit": source_sha,
              "protocol_commit": protocol_sha, "created_utc": datetime.now(timezone.utc).isoformat(),
              "worker": platform.node(), "source_archive_sha256": manifest["source_archive_sha256"],
              "input_digest": OLD_INPUT, "extension_digest": EXTENSION,
              "candidate_result_digest": OLD_RESULT, "october_result_digest": OCT_RESULT,
              "classification": "FIXED_PATH_HISTORICAL_EX_POST_STRESS_NOT_INDEPENDENT_QUALIFICATION",
              "cost_model": "Constant per-side fee/slippage; all cash; frozen next-open times; no order-book or rounding model.",
              "omission_interpretation": policy["concentration_analysis"]["classification"],
              "parameter_search": False, "new_market_data": False, "source_strategy_changes": False,
              "research_only": True, "auto_demo": False, "live_enabled": False, "orders": 0,
              "cost_boundaries": boundaries, "results": records, "checks": checks,
              "source_files": {}}
    for rel, path in (("research/nexus_mr40_fixed_path_robustness_v1.py", Path(__file__)),
                      ("research/mean_reversion_40_m2_robustness_v1.json", root / "study_contract.json"),
                      ("tests/test_nexus_mr40_fixed_path_robustness_v1.py",
                       root / "tests" / "test_nexus_mr40_fixed_path_robustness_v1.py"),
                      ("input_manifest.json", root / "input_manifest.json")):
        raw = path.read_bytes()
        result["source_files"][rel] = {"sha256": hashlib.sha256(raw).hexdigest(),
                                      "git_blob": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest(),
                                      "bytes": len(raw)}
    result["result_digest"] = digest(result)
    output = root / "results"
    output.mkdir()
    (output / "results.json").write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n",
                                         encoding="utf-8", newline="\n")
    for name, values in (("summary.csv", summaries), ("cost_boundaries.csv", boundaries), ("fills.csv", fills),
                         ("closed_positions.csv", positions), ("equity_curve.csv", curves), ("monthly_attribution.csv", monthly)):
        write_csv(output / name, values)
    print(json.dumps({"result_digest": result["result_digest"], "account_paths": len(checks),
                      "baseline_curves_exact": sum(c["baseline_curve_exact"] is True for c in checks),
                      "max_decimal_error_usdt": max(c["maximum_decimal_equity_error_usdt"] for c in checks)}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--protocol-sha", required=True)
    args = parser.parse_args()
    run(args.root, args.source_sha, args.protocol_sha)
