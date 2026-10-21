"""Bounded LBank history intake and frozen MR40 replay; no execution API."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import time
import urllib.parse
import urllib.request

STEP = 14_400_000
PINNED = {
    "core": ("research/nexus_mean_reversion_40_m2_retest_v1.py", "e9b898040d4680f128da330177df84e2fcc4ba1e2f70f467cf5455d685247b27"),
    "gate": ("research/nexus_mean_reversion_40_m2_momentum30_entry_v1.py", "d899e9dd991695959c230426b50ebdb4bab2eca8c5f413ea3c471d957c1f69bb"),
    "account": ("research/nexus_mr40_momentum30_newday_v1.py", "33946cefdef3a5ad87d8b131edfc82ba34d66118c159406f916443839cfd0fbf"),
    "validator": ("product_alternative_market.py", "8864a3ea04991dc0a7a7ec427c6aefd779e842905ac1390c37e6b0df2b9596bd"),
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def load_sources(source):
    loaded = {}
    for name, (relative, expected) in PINNED.items():
        path = source / relative
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("frozen source substitution: " + name)
        if name in ("core", "gate"):
            spec = importlib.util.spec_from_file_location("lbank_mr40_" + name, path)
            loaded[name] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(loaded[name])
        else:
            # Extract exact trusted, hash-pinned pure helpers; importing the full
            # product module would unnecessarily import the product dashboard.
            function = "decimal_500" if name == "account" else "_lbank_rows"
            tree = ast.parse(raw.decode())
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == function)
            namespace = {"Decimal": Decimal, "InvalidOperation": InvalidOperation,
                         "localcontext": localcontext, "STEP": STEP, "AlternativeMarketError": ValueError}
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
            loaded[name] = namespace[function]
    return loaded


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("public_redirect_rejected")


def unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_json_key")
        value[key] = item
    return value


def acquire(root, policy):
    core_start = int(datetime.fromisoformat(policy["history_start_utc"]).timestamp())
    end = int(datetime.fromisoformat(policy["window_end_exclusive_utc"]).timestamp())
    params = {"symbol": "btc_usdt", "type": "hour4", "time": str(core_start),
              "size": str((end-core_start)//14_400+1)}
    url = "https://api.lbank.info/v2/kline.do?" + urllib.parse.urlencode(params)
    receipt = {"provider": "LBank", "market": "spot", "symbol": "btc_usdt",
               "timeframe": "hour4", "url": url, "started_utc": datetime.now(timezone.utc).isoformat()}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "NEXUS-LBank-research/1"})
    with opener.open(req, timeout=12) as response:
        receipt.update(http_status=response.status, response_date=response.headers.get("Date"))
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("response_oversized")
    receipt.update(body_bytes=len(raw), body_sha256=hashlib.sha256(raw).hexdigest(),
                   finished_utc=datetime.now(timezone.utc).isoformat())
    (root / "lbank_kline_response.json").write_bytes(raw)
    (root / "source_receipt.json").write_bytes(canonical(receipt) + b"\n")
    body = json.loads(raw, parse_float=str, object_pairs_hook=unique_keys)
    if (not isinstance(body, dict) or body.get("result") not in (True, "true")
            or type(body.get("error_code")) is not int or body["error_code"] != 0
            or type(body.get("ts")) is not int or not -10 <= time.time()-body["ts"]/1000 <= 120):
        raise ValueError("public_provider_schema_or_freshness_failure")
    return body, receipt


def replay(rows, policy, code):
    core, gate = code["core"], code["gate"]
    core.validate_frame(rows)
    history = core.ms(policy["history_start_utc"])
    start_ms, end_ms = core.ms(policy["window_start_utc"]), core.ms(policy["window_end_exclusive_utc"])
    if [r[0] for r in rows] != list(range(history, end_ms, STEP)):
        raise ValueError("requested_history_gap_or_substitution")
    start = next(i for i, row in enumerate(rows) if row[0] == start_ms)
    if len(rows)-start != 180 or start < 221:
        raise ValueError("wrong_window_or_insufficient_warmup")
    # Any prior entry/exit threshold synchronizes the two-state MR40 machine,
    # proving the evaluation does not depend on an unknown pre-July position.
    close = [float(r[4]) for r in rows]
    resets = []
    for i in range(40, start-1):
        past = close[i-40:i]
        std = statistics.pstdev(past)
        z = (close[i]-statistics.mean(past))/std if std else None
        if z is not None and (z <= -2 or z >= 0):
            resets.append(i)
    if not resets:
        raise ValueError("unknown_prehistory_state_not_synchronized")
    raw, independent_raw = core.targets(rows), core.decimal_targets(rows)
    if raw != independent_raw:
        raise AssertionError("independent_signal_mismatch")
    target, admissions = gate.admit_episodes(rows, raw, start-1, len(rows)-1)
    independent_target = gate.independent_admission(rows, independent_raw, start-1, len(rows)-1)
    if target != independent_target:
        raise AssertionError("independent_admission_mismatch")
    for cut in (start+1, start+37, start+91):
        prefix = core.targets(rows[:cut])
        if prefix != raw[:cut] or gate.admit_episodes(rows[:cut], prefix, start-1, cut-1)[0][:cut-1] != target[:cut-1]:
            raise AssertionError("future_dependent_signal")
    records = []
    for profile in policy["profiles"]:
        fee, slip = profile["fee_bps"], profile["slippage_bps"]
        for name, signals, oracle_signals in (("original", raw, independent_raw), ("momentum30", target, independent_target)):
            out = core.simulate(rows, signals, start, len(rows), fee, slip)
            oracle = core.independent_accounting(rows, oracle_signals, start, len(rows), fee, slip)
            marks, fills = code["account"](rows, oracle_signals, start, fee, slip)
            error_10000 = max(abs(a["equity"]-b) for a,b in zip(out["equity_curve"], oracle["equity"]))
            error_500 = max(abs(a["equity"]/20-b) for a,b in zip(out["equity_curve"], marks))
            if (error_10000 > 1e-7 or error_500 > 1e-8 or oracle["fill_count"] != len(out["fills"])
                    or fills != [(f["fill_ms"],f["side"]) for f in out["fills"]]):
                raise AssertionError("independent_accounting_mismatch")
            metrics = out["metrics"]
            records.append({"strategy": name, "profile": profile["id"],
                "fee_bps_per_side": fee, "slippage_bps_per_side": slip,
                "initial_usdt": 10000, "net_pnl_usdt": metrics["net_pnl_usdt"],
                "initial_reference_usdt": 500, "reference_net_pnl_usdt": marks[-1]-500,
                "mean_position_pnl_usdt": metrics["average_closed_position_pnl_usdt"],
                "reference_mean_position_pnl_usdt": (marks[-1]-500)/metrics["closed_positions"] if metrics["closed_positions"] else None,
                "closed_positions": metrics["closed_positions"], "terminal_exits": metrics["terminal_exits"],
                "max_close_drawdown_pct": metrics["max_close_drawdown_pct"],
                "maximum_decimal_error_10000_usdt": error_10000, "maximum_decimal_error_500_usdt": error_500,
                "engine_result": out})
    return {"history_bars": len(rows), "warmup_bars": start, "window_bars": len(rows)-start,
            "history_rows_sha256": digest(rows), "independent_signal_checks": len(rows),
            "prefix_checks": 3, "synchronizing_thresholds_before_window": len(resets),
            "entry_admissions": admissions, "results": records}


def run(source, output, replay_from=None):
    if output.exists():
        raise ValueError("refuse output overwrite")
    code = load_sources(source)
    policy_raw = (source / "research/mean_reversion_40_m2_lbank_exact30_v1.json").read_bytes().replace(b"\r\n",b"\n")
    policy = json.loads(policy_raw)
    output.mkdir(parents=True)
    if replay_from is None:
        body, receipt = acquire(output, policy)
    else:
        raw = (replay_from / "lbank_kline_response.json").read_bytes()
        receipt = json.loads((replay_from / "source_receipt.json").read_bytes())
        if hashlib.sha256(raw).hexdigest() != receipt["body_sha256"]:
            raise ValueError("recorded_response_digest_mismatch")
        body = json.loads(raw, parse_float=str, object_pairs_hook=unique_keys)
    native = code["validator"](body["data"])
    end = int(datetime.fromisoformat(policy["window_end_exclusive_utc"]).timestamp())
    rows = sorted(([r[0]*1000, *r[1:]] for r in native if r[0] < end), key=lambda r:r[0])
    report = {"schema": "nexus.mr40-lbank-exact30-result.v1", "policy": policy,
              "policy_sha256": hashlib.sha256(policy_raw).hexdigest(), "source_files": PINNED,
              "driver_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
              "source_receipt": receipt, "rows_excluded_at_or_after_fixed_endpoint": len(native)-len(rows),
              "actual_demo_started": False, "exchange_orders": 0, "live_enabled": False,
              **replay(rows, policy, code)}
    report["result_digest"] = digest(report)
    (output / "results.json").write_bytes(canonical(report)+b"\n")
    (output / "study_contract.json").write_bytes(policy_raw)
    print(json.dumps({"result_digest": report["result_digest"], "history_bars": len(rows),
        "results": [{k:v for k,v in r.items() if k != "engine_result"} for r in report["results"]]}), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--replay-from", type=Path)
    run(**vars(parser.parse_args()))
