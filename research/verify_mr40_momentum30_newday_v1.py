"""Independent legacy Decimal account replay of the fixed latest-day result."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


RESULT = "2c531b10d6081ce8ec15d2bb35f8f7c7136f8c96cae46de4aad3671243d79158"
POLICY = "ec755a2e31407f5a183d869be5d15a62a37a385fa1cc8bd7b1e6203e713ca4b3"
COMMIT = "8d4415fbd4750243e0d1c9e07d07019224733357"


def verify(source, evidence, prefix, october):
    path = source / "research/nexus_mr40_momentum30_newday_v1.py"
    if hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != "33946cefdef3a5ad87d8b131edfc82ba34d66118c159406f916443839cfd0fbf":
        raise ValueError("new-day driver substitution")
    spec = importlib.util.spec_from_file_location("newday_verifier_support", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    report = helper.verified_json(evidence / "results.json", "result_digest", RESULT)
    execution = json.loads((evidence / "execution.json").read_text(encoding="utf-8"))
    if helper.digest({k: v for k, v in execution.items() if k != "digest"}) != execution["digest"]:
        raise ValueError("execution digest mismatch")
    if (report["source_commit"] != COMMIT or execution["source_commit"] != COMMIT
            or report["protocol_sha256"] != POLICY or execution["exit_code"] != 0
            or report["actual_demo_started"] is not False or report["live_enabled"] is not False
            or report["exchange_orders"] != 0 or report["auto_demo"] is not False
            or report["independent_economic_qualification"] is not False):
        raise ValueError("source/authority drift")
    modules = helper.modules(source)
    core, gate = modules["core"], modules["gate"]
    old = helper.verified_json(prefix, "input_digest", helper.INPUT)
    ext = helper.verified_json(october, "digest", helper.EXTENSION)
    rows = old["rows"] + ext["rows"] + report["new_rows"]
    core.validate_frame(rows)
    if len(rows) != 8520 or helper.digest(rows) != report["combined_rows_sha256"]:
        raise ValueError("source rows mismatch")
    start = len(rows) - 180
    if (rows[start][0] != core.ms("2026-09-21T00:00:00")
            or rows[-6][0] != core.ms("2026-10-20T00:00:00")
            or rows[-1][0] + helper.STEP != core.ms("2026-10-21T00:00:00")):
        raise ValueError("fixed boundaries mismatch")
    raw = core.decimal_targets(rows)
    target = gate.independent_admission(rows, raw, start - 1, len(rows) - 1)
    checks = []
    if len(report["results"]) != 4:
        raise ValueError("missing case")
    expected_cases = {(name, profile) for name in ("original", "momentum30") for profile in ("normal", "stress")}
    if {(r["strategy"], r["profile"]) for r in report["results"]} != expected_cases:
        raise ValueError("case substitution")
    for case in report["results"]:
        fee, slip = (10, 5) if case["profile"] == "normal" else (25, 15)
        signal = raw if case["strategy"] == "original" else target
        account = core.independent_accounting(rows, signal, start, len(rows), fee, slip)
        marks = [v / 20 for v in account["equity"]]
        error = max(abs(a - b) for a, b in zip(marks, case["normalized_500_equity"]))
        if error > 1e-8 or account["fill_count"] != case["fills"]:
            raise AssertionError("independent curve/fill mismatch")
        exact = core.simulate(rows, signal, start, len(rows), fee, slip)
        if exact != case["unmodified_10000_engine_result"]:
            raise AssertionError("full ledger mismatch")
        expected_pnl = marks[-1] - 500
        if abs(expected_pnl - case["net_pnl_usdt"]) > 1e-8:
            raise AssertionError("PnL mismatch")
        m = exact["metrics"]
        for key in ("max_close_drawdown_pct", "closed_positions", "terminal_exits", "net_return_pct"):
            if case[key] != m[key]:
                raise AssertionError("summary mismatch: " + key)
        if abs(case["added_day_marked_pnl_usdt"] - (marks[-1] - marks[-7])) > 1e-8:
            raise AssertionError("new-day attribution mismatch")
        count = sum(f["fill_ms"] >= rows[-6][0] for f in exact["fills"])
        if count != case["added_day_fills"]:
            raise AssertionError("new-day fill mismatch")
        checks.append({"strategy": case["strategy"], "profile": case["profile"], "bars": len(marks),
                       "maximum_decimal_equity_error_usdt": error, "full_ledger_exact": True})
    result = {"schema": "nexus.mr40-newday-independent-account-qa.v1", "result_digest": RESULT,
              "source_commit": COMMIT, "checks": checks, "research_only": True,
              "raw_trade_stream_reprocessed": False, "provider_source_independently_attested": False,
              "actual_demo_started": False, "economic_qualification": False, "exchange_orders": 0,
              "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()}
    result["digest"] = helper.digest(result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("source", "evidence", "prefix", "october", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    value = verify(args.source, args.evidence, args.prefix, args.october)
    with args.output.open("x", encoding="utf-8", newline="\n") as out:
        json.dump(value, out, sort_keys=True, separators=(",", ":"), allow_nan=False)
        out.write("\n")
    print(json.dumps(value))
