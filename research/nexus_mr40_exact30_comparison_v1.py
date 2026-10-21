"""Calendar-fixed fresh-account comparison using already-seen, pinned MR40 data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import tempfile
import zipfile
from pathlib import Path

STEP = 14_400_000
START = 1789862400000  # 2026-09-20 00:00 UTC
END = 1792454400000    # 2026-10-20 00:00 UTC, exclusive
OCTOBER_START = 1790812800000
ARCHIVE_SHA = "836c57c0704cfc319973beb5868758ae2416deaacdfa1ec8edc91a0973e7788b"
PARENT_RESULT = "dee122e30911d815f426cef84bb9fa6f5a870291b94240a8265733e57c151bba"
OCTOBER_RESULT = "3209320f841a694f7711a365e93a0fd1e6777f31b1dd250c0c44f3ab630ca7ac"
CORE_SHA = "e9b898040d4680f128da330177df84e2fcc4ba1e2f70f467cf5455d685247b27"
GATE_SHA = "d899e9dd991695959c230426b50ebdb4bab2eca8c5f413ea3c471d957c1f69bb"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def checked(value, key, expected):
    if value.get(key) != expected or digest({k: v for k, v in value.items() if k != key}) != expected:
        raise ValueError("substituted " + key)
    return value


def load_module(name, path, raw, expected):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("frozen module substitution")
    path.write_bytes(raw)
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def run(archive, output, source_sha):
    if output.exists():
        raise ValueError("refuse output overwrite")
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise ValueError("exact committed comparison source required")
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA:
        raise ValueError("parent archive substitution")
    records, checks, summary, fills, positions, curves = [], [], [], [], [], []
    with zipfile.ZipFile(io.BytesIO(raw)) as bundle, tempfile.TemporaryDirectory(prefix="mr40-exact30-") as directory:
        work = Path(directory)
        core = load_module("mr40_exact30_core", work / "core.py", bundle.read("frozen/nexus_mean_reversion_40_m2_retest_v1.py"), CORE_SHA)
        gate = load_module("mr40_exact30_gate", work / "gate.py", bundle.read("frozen/nexus_mean_reversion_40_m2_momentum30_entry_v1.py"), GATE_SHA)
        parent = checked(json.loads(bundle.read("recorded_results/results.json")), "result_digest", PARENT_RESULT)
        old = checked(json.loads(bundle.read("frozen/prepared_inputs.json")), "input_digest",
                      "fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe")
        extension = checked(json.loads(bundle.read("frozen/october_input_extension.json")), "digest",
                            "17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c")
        october = checked(json.loads(bundle.read("frozen/october_results.json")), "result_digest", OCTOBER_RESULT)
        policy = json.loads(bundle.read("study_contract.json"))
        rows = old["rows"] + extension["rows"]
        core.validate_frame(rows)
        if len(rows) != 8514 or digest(rows) != parent["combined_rows_digest"]:
            raise ValueError("changed accepted frame")
        start = next(i for i, row in enumerate(rows) if row[0] == START)
        end = next((i for i, row in enumerate(rows) if row[0] == END), len(rows))
        if end - start != 180 or rows[end - 1][0] + STEP != END or (END - START) / STEP != 180:
            raise ValueError("not exactly 30 complete UTC days")
        raw_target, decimal_target = core.targets(rows), core.decimal_targets(rows)
        if raw_target != decimal_target:
            raise AssertionError("independent target mismatch")
        for profile in policy["profiles"]:
            lag, fee, slip = profile["lag_bars"], profile["fee_bps"], profile["slippage_bps"]
            filtered, decisions = gate.admit_episodes(rows, raw_target, start - lag, end - lag)
            independent_filtered = gate.independent_admission(rows, decimal_target, start - lag, end - lag)
            if filtered != independent_filtered:
                raise AssertionError("independent fresh-account gate mismatch")
            for strategy, target, independent_target in (("original", raw_target, decimal_target),
                                                        ("momentum30", filtered, independent_filtered)):
                out = core.simulate(rows, target, start, end, fee, slip, lag=lag)
                oracle = core.independent_accounting(rows, independent_target, start, end, fee, slip, lag=lag)
                error = max(abs(row["equity"] - value) for row, value in zip(out["equity_curve"], oracle["equity"]))
                if (len(out["equity_curve"]) != len(oracle["equity"]) or error > 1e-7
                        or out["metrics"]["fills"] != oracle["fill_count"]):
                    raise AssertionError("independent fresh-account accounting mismatch")
                old_october = [r for r in october["results"] if r["cohort"] == "october_01_19"
                               and r["strategy"] == strategy and r["profile"] == profile["id"]]
                if len(old_october) != 1:
                    raise ValueError("ambiguous prior October control")
                prior = old_october[0]
                extra = [r for r in out["equity_curve"] if r["bar_open_ms"] < OCTOBER_START]
                same_ledger = out["fills"] == prior["fills"] and out["positions"] == prior["positions"]
                labels = {"strategy": strategy, "profile": profile["id"]}
                metrics = dict(out["metrics"]);metrics["fill_count"] = metrics.pop("fills")
                records.append({**labels, "fee_bps_per_side": fee, "slippage_bps_per_side": slip,
                                "lag_bars": lag, **metrics, "fills": out["fills"], "positions": out["positions"],
                                "admission_decisions": decisions if strategy == "momentum30" else None})
                checks.append({**labels, "maximum_decimal_equity_error_usdt": error,
                               "additional_days_before_october": len(extra) / 6,
                               "additional_days_all_cash": all(r["equity"] == 10000 and not r["in_market"] for r in extra),
                               "fills_before_october": sum(f["fill_ms"] < OCTOBER_START for f in out["fills"]),
                               "same_fills_and_positions_as_prior_19day_october": same_ledger,
                               "pnl_difference_from_prior_19day_october_usdt": metrics["net_pnl_usdt"] - prior["net_pnl_usdt"]})
                summary.append({**labels, "fee_bps_per_side": fee, "slippage_bps_per_side": slip, "lag_bars": lag, **metrics})
                for destination, values in ((fills, out["fills"]), (positions, out["positions"]), (curves, out["equity_curve"])):
                    destination.extend({**labels, **value} for value in values)
    result = {"schema": "nexus.mr40-exact30-comparison.v1", "source_commit": source_sha,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "parent_archive_sha256": ARCHIVE_SHA, "parent_result_digest": PARENT_RESULT,
              "prior_october_result_digest": OCTOBER_RESULT,
              "window": {"start_utc": core.iso(START), "end_exclusive_utc": core.iso(END),
                         "bars": 180, "days": 30, "initial_usdt_per_account": 10000,
                         "warmup": "All verified previous closed history; fresh cash and gate once at window start."},
              "classification": "ALREADY_SEEN_FIXED_CALENDAR_WINDOW_NOT_INDEPENDENT_QUALIFICATION",
              "new_market_data": False, "parameter_search": False, "source_strategy_changes": False,
              "research_only": True, "auto_demo": False, "live_enabled": False, "orders": 0,
              "results": records, "checks": checks}
    result["result_digest"] = digest(result)
    output.mkdir(parents=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name, values in (("summary.csv", summary), ("fills.csv", fills), ("closed_positions.csv", positions), ("equity_curve.csv", curves)):
        with (output / name).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(values[0]), lineterminator="\n")
            writer.writeheader();writer.writerows(values)
    print(json.dumps({"result_digest": result["result_digest"], "accounts": len(records),
                      "days": 30, "bars_per_account": 180,
                      "maximum_decimal_equity_error_usdt": max(c["maximum_decimal_equity_error_usdt"] for c in checks),
                      "same_october_ledgers": sum(c["same_fills_and_positions_as_prior_19day_october"] for c in checks)}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    run(args.archive, args.output, args.source_sha)
