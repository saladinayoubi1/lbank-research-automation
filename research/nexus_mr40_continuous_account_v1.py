"""One uninterrupted frozen MR40 account, January 2023 through October 19, 2026."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path

STEP = 14_400_000
PROTOCOL = "b71e99fc4c4a5a8e98aea37ab15d5719c3729b62"
POLICY_SHA = "2beaf7ae15937570b904adcf0b86aadc93c40857bb95942df1efd82107b8f033"
MANIFEST_SHA = "dbd54010d2ecbc3de8d3910e4350b77f39f070062ac6f2c2bb957ed2bdb14f37"
INPUT = "fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
BASE = "44ea00e4528ccbe3e420bd999152a36b58450565f8a45bb9489a3c79fe4b4514"
CANDIDATE = "959832aa111ba6bbab7a899547a7d4e031a0f3cd0a283de30397635f1ba5f118"
EXTENSION = "17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c"
OCTOBER = "3209320f841a694f7711a365e93a0fd1e6777f31b1dd250c0c44f3ab630ca7ac"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def check_digest(value, key, expected):
    if value.get(key) != expected or digest({k: v for k, v in value.items() if k != key}) != expected:
        raise ValueError("substituted " + key)


def file_info(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()}


def verified(path, expected):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("file substitution: " + path.name)
    return raw


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def load(root):
    manifest = json.loads(verified(root / "input_manifest.json", MANIFEST_SHA))
    blobs = {p: verified(root / p, item["sha256"]) for p, item in manifest["files"].items()}
    old = json.loads(blobs["frozen/prepared_inputs.json"])
    extension = json.loads(blobs["frozen/october_input_extension.json"])
    original = json.loads(blobs["frozen/original_results.json"])
    candidate = json.loads(blobs["frozen/candidate_results.json"])
    october = json.loads(blobs["frozen/october_results.json"])
    for obj, key, expected in ((old, "input_digest", INPUT), (extension, "digest", EXTENSION),
                               (original, "result_digest", BASE), (candidate, "result_digest", CANDIDATE),
                               (october, "result_digest", OCTOBER)):
        check_digest(obj, key, expected)
    rows = old["rows"] + extension["rows"]
    if (len(old["rows"]) != 8400 or len(extension["rows"]) != 114 or len(rows) != 8514
            or extension["base_input_digest"] != INPUT or digest(rows) != october["combined_rows_digest"]):
        raise ValueError("frozen data extension changed")
    core = module("continuous_frozen_core", root / "frozen/nexus_mean_reversion_40_m2_retest_v1.py")
    gate = module("continuous_frozen_gate", root / "frozen/nexus_mean_reversion_40_m2_momentum30_entry_v1.py")
    risk = module("continuous_frozen_risk", root / "frozen/nexus_mr40_underwater_diagnostic_v1.py")
    core.validate_frame(rows)
    return manifest, rows, original, candidate, core, gate, risk


def check_prefix(actual, prior, control):
    """Keep the old pre-terminal mark; extending a sample removes its old forced exit."""
    size = control["bars"]
    prefix = actual["equity_curve"][:size]
    if len(prefix) != size or digest(prefix) != control["equity_sha256_without_old_terminal_liquidation"]:
        raise AssertionError("historical prefix equity changed")
    cutoff = prefix[-1]["bar_open_ms"] + STEP
    expected = [f for f in prior["fills"] if f["reason"] != "terminal_close"]
    observed = [f for f in actual["fills"] if f["fill_ms"] < cutoff]
    if observed != expected:
        raise AssertionError("historical natural fills changed")
    if prior["terminal_exits"] != control["old_terminal_exits"]:
        raise AssertionError("old terminal count changed")
    return {"prefix_bars": size, "prefix_curve_exact": True, "prefix_natural_fills_exact": True,
            "old_forced_terminal_exits_removed_for_extension": prior["terminal_exits"],
            "cutoff_utc": datetime.fromtimestamp(cutoff / 1000, timezone.utc).isoformat(),
            "cutoff_pre_terminal_mark_equity": prefix[-1]["equity"],
            "position_carried_at_cutoff": prefix[-1]["in_market"]}


def exit_month(position):
    stamp = position["exit_ms"] - int(position["exit_reason"] == "terminal_close")
    return datetime.fromtimestamp(stamp / 1000, timezone.utc).strftime("%Y-%m")


def monthly_with_positions(out):
    values = []
    for row in out["monthly_attribution"]:
        closed = [p for p in out["positions"] if exit_month(p) == row["month"]]
        pnl = math.fsum(p["net_pnl_usdt"] for p in closed)
        values.append({**row, "positions_closed": len(closed), "closed_position_pnl_sum_usdt": pnl,
                       "average_closed_position_pnl_usdt": pnl / len(closed) if closed else None})
    if abs(math.fsum(m["pnl_usdt"] for m in values) - out["metrics"]["net_pnl_usdt"]) > 1e-7:
        raise AssertionError("marked monthly PnL does not reconcile")
    if sum(m["positions_closed"] for m in values) != len(out["positions"]):
        raise AssertionError("monthly closed position count does not reconcile")
    if abs(math.fsum(m["closed_position_pnl_sum_usdt"] for m in values)
           - math.fsum(p["net_pnl_usdt"] for p in out["positions"])) > 1e-7:
        raise AssertionError("monthly closed PnL does not reconcile")
    return values


def write_csv(path, rows):
    if not rows:
        raise ValueError("empty table")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(root, source_sha, protocol_sha):
    if (root / "results").exists():
        raise ValueError("refuse result overwrite")
    if (len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha)
            or protocol_sha != PROTOCOL):
        raise ValueError("exact committed source/protocol required")
    policy = json.loads(verified(root / "study_contract.json", POLICY_SHA))
    manifest, rows, original, candidate, core, gate, risk = load(root)
    start = next(i for i, r in enumerate(rows) if r[0] == core.ms(policy["window"]["start_utc"]))
    end = next((i for i, r in enumerate(rows) if r[0] == core.ms(policy["window"]["end_exclusive_utc"])), len(rows))
    if end - start != policy["window"]["expected_bars"] or rows[end - 1][0] + STEP != core.ms(policy["window"]["end_exclusive_utc"]):
        raise ValueError("continuous account boundary changed")
    raw, independent_raw = core.targets(rows), core.decimal_targets(rows)
    if raw != independent_raw:
        raise AssertionError("Decimal raw target disagreement")
    results, checks = [], []
    summaries, fills, positions, curves, monthly, admissions, episodes = [], [], [], [], [], [], []
    for profile in policy["profiles"]:
        fee, slip, lag = profile["fee_bps"], profile["slippage_bps"], profile["lag_bars"]
        target, decisions = gate.admit_episodes(rows, raw, start - lag, end - lag)
        oracle_target = gate.independent_admission(rows, independent_raw, start - lag, end - lag)
        if target != oracle_target:
            raise AssertionError("Decimal admission disagreement")
        for strategy, signal, oracle_signal, old in (("original", raw, independent_raw, original),
                                                     ("momentum30", target, oracle_target, candidate)):
            out = core.simulate(rows, signal, start, end, fee, slip, lag=lag)
            independent = core.independent_accounting(rows, oracle_signal, start, end, fee, slip, lag=lag)
            error = max(abs(a["equity"] - b) for a, b in zip(out["equity_curve"], independent["equity"]))
            if (len(out["equity_curve"]) != len(independent["equity"]) or error > 1e-7
                    or out["metrics"]["fills"] != independent["fill_count"]):
                raise AssertionError("independent continuous accounting mismatch")
            prior = [r for r in old["results"] if r["cohort"] == "retrospective_42_months" and r["profile"] == profile["id"]]
            if len(prior) != 1:
                raise ValueError("ambiguous prior control")
            prefix = check_prefix(out, prior[0], manifest["prefix_controls"][strategy + "/" + profile["id"]])
            recovery = risk.summarize(out["equity_curve"])
            risk_error = risk.assert_oracle(recovery["episodes"], risk.independent_episodes(out["equity_curve"]))
            attribution = monthly_with_positions(out)
            benchmark = core.benchmark(rows, start, end, fee, slip)
            labels = {"strategy": strategy, "profile": profile["id"]}
            stats = dict(out["metrics"])
            stats["fill_count"] = stats.pop("fills")
            stats["cagr_pct"] = 100 * ((stats["final_usdt"] / stats["initial_usdt"]) ** (365.25 / stats["days"]) - 1)
            record = {**labels, "fee_bps_per_side": fee, "slippage_bps_per_side": slip, "lag_bars": lag,
                      **stats, "buy_hold_first_open_net_pnl_usdt": benchmark["net_pnl_usdt"],
                      "buy_hold_max_close_drawdown_pct": benchmark["max_close_drawdown_pct"],
                      "admitted_episodes": sum(d["accepted"] for d in decisions) if strategy == "momentum30" else None,
                      "rejected_episodes": sum(not d["accepted"] for d in decisions) if strategy == "momentum30" else None,
                      "monthly_attribution": attribution,
                      "recovery": {k: v for k, v in recovery.items() if k != "episodes"}}
            results.append(record)
            summaries.append({k: v for k, v in record.items() if k not in ("monthly_attribution", "recovery")})
            checks.append({**labels, "maximum_decimal_equity_error_usdt": error,
                           "independent_drawdown_error_pct": risk_error, **prefix})
            for destination, source in ((fills, out["fills"]), (positions, out["positions"]),
                                        (curves, out["equity_curve"]), (monthly, attribution), (episodes, recovery["episodes"])):
                destination.extend({**labels, **item} for item in source)
            if strategy == "momentum30":
                admissions.extend({**labels, **d} for d in decisions)
            print(json.dumps({**labels, "net_pnl_usdt": stats["net_pnl_usdt"], "closed": stats["closed_positions"],
                              "terminal": stats["terminal_exits"], "close_dd_pct": stats["max_close_drawdown_pct"],
                              "ending_dd_pct": recovery["ending_drawdown_pct"],
                              "longest_observed_peak_to_end_days": recovery["longest_observed_peak_to_end_days"]}), flush=True)
    output = root / "results"
    output.mkdir()
    tables = {"summary.csv": summaries, "fills.csv": fills, "closed_positions.csv": positions,
              "equity_curve.csv": curves, "monthly_attribution.csv": monthly,
              "entry_admissions.csv": admissions, "drawdown_episodes.csv": episodes}
    for name, values in tables.items():
        write_csv(output / name, values)
    result = {"schema": "nexus.mr40-continuous-account-results.v1", "code_commit": source_sha,
              "protocol_commit": protocol_sha, "source_archive_sha256": manifest["source_archive_sha256"],
              "input_digest": INPUT, "extension_digest": EXTENSION, "original_result_digest": BASE,
              "candidate_result_digest": CANDIDATE, "combined_rows_digest": digest(rows),
              "independent_raw_signal_bars": len(rows),
              "classification": "CONTINUOUS_ALREADY_SEEN_HISTORY_NOT_INDEPENDENT_QUALIFICATION",
              "account_resets": 0, "parameter_search": False, "new_market_data": False,
              "source_strategy_changes": False, "research_only": True, "auto_demo": False,
              "live_enabled": False, "orders": 0, "results": results, "checks": checks,
              "output_files": {name: file_info(output / name) for name in tables},
              "source_files": {}}
    for name, path in (("research/nexus_mr40_continuous_account_v1.py", Path(__file__)),
                       ("tests/test_nexus_mr40_continuous_account_v1.py", root / "tests/test_nexus_mr40_continuous_account_v1.py"),
                       ("research/mean_reversion_40_m2_continuous_account_v1.json", root / "study_contract.json"),
                       ("input_manifest.json", root / "input_manifest.json")):
        result["source_files"][name] = file_info(path)
    result["result_digest"] = digest(result)
    (output / "results.json").write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"result_digest": result["result_digest"], "account_paths": len(results),
                      "exact_prefix_controls": len(checks), "rows": len(rows),
                      "maximum_decimal_error_usdt": max(c["maximum_decimal_equity_error_usdt"] for c in checks)}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--protocol-sha", required=True)
    args = parser.parse_args()
    run(args.root, args.source_sha, args.protocol_sha)
