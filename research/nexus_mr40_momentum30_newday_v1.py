"""One fixed latest-day research extension; no Paper writer or order API."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import platform

STEP = 14_400_000
PINNED = {
    "core": ("research/nexus_mean_reversion_40_m2_retest_v1.py", "e9b898040d4680f128da330177df84e2fcc4ba1e2f70f467cf5455d685247b27"),
    "gate": ("research/nexus_mean_reversion_40_m2_momentum30_entry_v1.py", "d899e9dd991695959c230426b50ebdb4bab2eca8c5f413ea3c471d957c1f69bb"),
    "intake": ("scripts/nexus_mr40_october_followup_intake_v1.py", "eb2a0d05729c54e057ea2eeecd2ff62a111f9fb500a70823d960cf68372c1a03"),
}
INPUT = "fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
EXTENSION = "17f3101579ebd301cda074174ed4154e772d15d6b2ef2e17513d73b1dc31798c"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def verified_json(path, key, expected):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get(key) != expected or digest({k: v for k, v in value.items() if k != key}) != expected:
        raise ValueError("frozen input substitution")
    return value


def modules(source):
    result = {}
    for name, (relative, expected) in PINNED.items():
        path = source / relative
        if hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != expected:
            raise ValueError("frozen source substitution: " + name)
        spec = importlib.util.spec_from_file_location("newday_" + name, path)
        result[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result[name])
    return result


def decimal_500(rows, signals, start, fee_bps, slip_bps):
    """Separate 500-unit account, using Decimal and decision t-1 only."""
    with localcontext() as ctx:
        ctx.prec = 50
        d = Decimal
        fee, slip = d(fee_bps) / 10000, d(slip_bps) / 10000
        cash, units = d(500), d(0)
        equity, fills = [], []
        for i in range(start, len(rows)):
            price = d(rows[i][1])
            side = None
            if signals[i - 1] and not units:
                units = cash / ((1 + fee) * price * (1 + slip))
                cash, side = d(0), "buy"
            elif not signals[i - 1] and units:
                cash, units = units * price * (1 - slip) * (1 - fee), d(0)
                side = "sell"
            if side:
                fills.append((rows[i][0], side))
            equity.append(cash + units * d(rows[i][4]))
        if units:
            cash = units * d(rows[-1][4]) * (1 - slip) * (1 - fee)
            equity[-1] = cash
            fills.append((rows[-1][0] + STEP, "sell"))
        return list(map(float, equity)), fills


def run(root, source, prefix, october, protocol_sha, source_commit):
    if root.exists() and (root / "results.json").exists():
        raise ValueError("refuse result overwrite")
    policy_path = root / "study_contract.json"
    policy_bytes = policy_path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(policy_bytes).hexdigest() != protocol_sha:
        raise ValueError("registered policy substitution")
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("exact preregistered source commit required")
    policy = json.loads(policy_bytes)
    code = modules(source)
    core, gate, intake = (code[k] for k in ("core", "gate", "intake"))
    old = verified_json(prefix, "input_digest", INPUT)
    ext = verified_json(october, "digest", EXTENSION)
    prior = old["rows"] + ext["rows"]
    core.validate_frame(prior)
    if len(prior) != 8514 or prior[-1][0] + STEP != core.ms("2026-10-20T00:00:00"):
        raise ValueError("wrong frozen prefix boundary")
    if policy["source_day"] != "2026-10-20" or policy["opening_research_cash_usdt"] != 500:
        raise ValueError("registered day/cash changed")
    if datetime.now(timezone.utc).timestamp() * 1000 < core.ms("2026-10-21T00:00:00"):
        raise ValueError("incomplete source day")
    item = intake.acquire(policy["source_day"], root)
    audit = intake.aggregate(Path(item["path"]), policy["source_day"], item["sha256"])
    added = audit.pop("rows")
    if len(added) != 6 or added[0][0] != prior[-1][0] + STEP:
        raise ValueError("new day gap/overlap")
    rows = prior + added
    core.validate_frame(rows)
    start = next(i for i, row in enumerate(rows) if row[0] == core.ms("2026-09-21T00:00:00"))
    if len(rows) - start != 180 or rows[-1][0] + STEP != core.ms("2026-10-21T00:00:00"):
        raise ValueError("not exactly latest 30 complete days")
    raw, oracle_raw = core.targets(rows), core.decimal_targets(rows)
    if raw != oracle_raw or raw[:len(prior)] != core.targets(prior):
        raise AssertionError("signal oracle or immutable prefix mismatch")
    target, admissions = gate.admit_episodes(rows, raw, start - 1, len(rows) - 1)
    oracle = gate.independent_admission(rows, oracle_raw, start - 1, len(rows) - 1)
    if target != oracle:
        raise AssertionError("admission oracle mismatch")
    results = []
    for profile in policy["profiles"]:
        for name, signal in (("original", raw), ("momentum30", target)):
            fee, slip = profile["fee_bps"], profile["slippage_bps"]
            out = core.simulate(rows, signal, start, len(rows), fee, slip)
            marks, fills = decimal_500(rows, oracle_raw if name == "original" else oracle, start, fee, slip)
            error = max(abs(a["equity"] / 20 - b) for a, b in zip(out["equity_curve"], marks))
            if error > 1e-8 or fills != [(f["fill_ms"], f["side"]) for f in out["fills"]]:
                raise AssertionError("independent 500-unit account mismatch")
            m = out["metrics"]
            new_fills = [f for f in out["fills"] if f["fill_ms"] >= added[0][0]]
            results.append({"profile": profile["id"], "strategy": name,
                "initial_usdt": 500, "final_usdt": marks[-1], "net_pnl_usdt": marks[-1] - 500,
                "net_return_pct": m["net_return_pct"], "max_close_drawdown_pct": m["max_close_drawdown_pct"],
                "closed_positions": m["closed_positions"], "fills": m["fills"], "terminal_exits": m["terminal_exits"],
                "mean_position_pnl_usdt": None if not m["closed_positions"] else m["net_pnl_usdt"] / 20 / m["closed_positions"],
                "added_day_fills": len(new_fills), "added_day_marked_pnl_usdt": marks[-1] - marks[-7],
                "maximum_decimal_equity_error_usdt": error, "normalized_500_equity": marks,
                "unmodified_10000_engine_result": out})
    report = {"schema": "nexus.mr40-momentum30-newday-result.v1", "source_commit": source_commit,
        "protocol_sha256": protocol_sha, "created_utc": datetime.now(timezone.utc).isoformat(),
        "physical_worker": platform.node(), "python": platform.python_version(),
        "source_files": PINNED, "driver_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "previous_input_digest": INPUT, "previous_extension_digest": EXTENSION,
        "source_receipt": item, "raw_day_audit": audit, "new_rows": added, "new_bars": 6,
        "combined_rows_sha256": digest(rows), "window_bars": 180,
        "window_start_utc": policy["window_start_utc"], "window_end_exclusive_utc": policy["window_end_exclusive_utc"],
        "classification": policy["classification"], "actual_demo_started": False,
        "exchange_orders": 0, "live_enabled": False, "auto_demo": False,
        "parameter_search": False, "independent_economic_qualification": False,
        "entry_admissions": admissions, "results": results}
    report["result_digest"] = digest(report)
    (root / "results.json").write_bytes(canonical(report) + b"\n")
    (root / "source_receipt.json").write_bytes(canonical(item) + b"\n")
    print(json.dumps({"result_digest": report["result_digest"], "new_trades_audited": audit["rows_validated"],
        "results": [{k: v for k, v in r.items() if k not in ("normalized_500_equity", "unmodified_10000_engine_result")} for r in results]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for field in ("root", "source", "prefix", "october"):
        parser.add_argument("--" + field, type=Path, required=True)
    parser.add_argument("--protocol-sha", required=True)
    parser.add_argument("--source-commit", required=True)
    run(**vars(parser.parse_args()))
