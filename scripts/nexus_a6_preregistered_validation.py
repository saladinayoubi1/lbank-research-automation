"""Execute frozen A6 data QA; never admit a strategy or modify an owner account."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PLAN_SHA = "6ecc03c438560b02a1410f07cef7c86df1fb2665749d184b1a4d45248f33c7cb"
LIVE_SHA = "bbe1e3170cb29d7c7c6c2b3692119e00f931c1dfd97aa6823b58741bdfdbc583"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def pinned_json(path, field, expected):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 250_000:
        raise ValueError("frozen evidence unavailable, linked, or oversized")
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate frozen evidence key")
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if not isinstance(value, dict):
        raise ValueError("frozen evidence must be an object")
    core = {k: v for k, v in value.items() if k != field}
    if value.get(field) != expected or digest(core) != expected:
        raise ValueError("preregistered evidence digest changed")
    return value


def utc(value):
    at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise ValueError("explicit UTC required")
    return at


def future_due(plan, now):
    start = utc(plan["start_date"] + "T00:00:00Z")
    end = utc(plan["end_date"] + "T00:00:00Z") + timedelta(days=1)
    if utc(plan["registered_at_utc"]) >= start or end - start != timedelta(days=30):
        raise ValueError("registration must precede the entire 30-day future window")
    if any(plan.get(k) is not False for k in ("automatic_strategy_promotion", "live_trading_authority")):
        raise ValueError("research authority widened")
    return now >= end


def trade_commitment(symbol, trade_id, time_ms, side, price, size):
    if symbol not in ("BTCUSDT", "ETHUSDT") or side not in ("Buy", "Sell"):
        raise ValueError("unsupported Spot trade identity or side")
    p, v = Decimal(price), Decimal(size)
    if not p.is_finite() or not v.is_finite() or p <= 0 or v <= 0:
        raise ValueError("invalid exact trade price or size")
    at = Decimal(time_ms)
    if not at.is_finite() or at != at.to_integral_value():
        raise ValueError("exact millisecond timestamp required")
    key = hashlib.sha256((symbol + ":" + trade_id).encode()).hexdigest()
    value = {"symbol": symbol, "time_ms": int(at), "side": side,
             "price": str(p.normalize()), "size": str(v.normalize())}
    return key, digest(value)


def match_archive(archive, symbol, expected, archive_date):
    """Independent CSV/Decimal matching, bounded to the committed trade IDs."""
    found = set()
    start_ms = int(utc(archive_date + "T00:00:00Z").timestamp()) * 1000
    with gzip.open(archive, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        first = next(reader)
        aliases = {"id": "id", "tradeid": "id", "trdmatchid": "id", "execid": "id",
                   "timestamp": "time", "time": "time", "trdtime": "time",
                   "price": "price", "size": "size", "qty": "size", "side": "side",
                   "symbol": "symbol"}
        names = [aliases.get("".join(c for c in x.lower() if c.isalnum())) for x in first]
        named = all(k in names for k in ("id", "time", "price", "size", "side"))
        indexes = ({k: names.index(k) for k in names if k} if named
                   else {"id": 0, "time": 1, "price": 2, "size": 3, "side": 4})
        def inspect(row):
            if len(row) <= max(indexes.values()):
                raise ValueError("short archive trade row")
            key = hashlib.sha256((symbol + ":" + row[indexes["id"]].strip()).encode()).hexdigest()
            if key not in expected:
                return
            if key in found:
                raise ValueError("duplicate captured trade in archive")
            if "symbol" in indexes and row[indexes["symbol"]].strip().upper() != symbol:
                raise ValueError("archive symbol mismatch")
            at = Decimal(row[indexes["time"]])
            time_ms = at if abs(at) >= Decimal("1e11") else at * 1000
            if not start_ms <= time_ms < start_ms + 86_400_000:
                raise ValueError("archive trade outside committed UTC day")
            actual_key, actual = trade_commitment(
                symbol, row[indexes["id"]].strip(), time_ms,
                row[indexes["side"]].strip().title(), row[indexes["price"]], row[indexes["size"]])
            if actual_key != key or actual != expected[key]:
                raise ValueError("same-trade live/archive side, price, size, or time mismatch")
            found.add(key)
        if not named:
            inspect(first)
        for row in reader:
            if row:
                inspect(row)
    if found != set(expected):
        raise ValueError(f"missing committed trades: {len(expected) - len(found)}")
    return len(found)


def live_side(out, now):
    evidence = pinned_json(ROOT / "config/a6-live-side-commitments-20261009.json",
                           "commitments_sha256", LIVE_SHA)
    day = evidence["archive_date"]
    if now < utc(day + "T00:00:00Z") + timedelta(days=1):
        return {"status": "WAITING_OFFICIAL_DAY_ARCHIVE", "archive_date": day,
                "archive_same_trade_crosscheck_complete": False}
    checks = []
    for symbol, targets in sorted(evidence["trade_commitments"].items()):
        url = f"https://public.bybit.com/spot/{symbol}/{symbol}_{day}.csv.gz"
        archive = out / f"{symbol}_{day}.csv.gz"
        sha = hashlib.sha256()
        size = 0
        with urlopen(url, timeout=30) as response, archive.open("wb") as handle:
            for block in iter(lambda: response.read(1024 * 1024), b""):
                size += len(block)
                if size > 256_000_000:
                    raise ValueError("official day archive exceeds QA size bound")
                handle.write(block)
                sha.update(block)
        matched = match_archive(archive, symbol, targets, day)
        checks.append({"symbol": symbol, "url": url, "archive_sha256": sha.hexdigest(),
                       "committed_trades": len(targets), "matched_trades": matched})
    return {"status": "PASS_CAPTURED_SPOT_TRADE_SIDE_CROSSCHECK", "archive_date": day,
            "commitments_sha256": LIVE_SHA, "archive_same_trade_crosscheck_complete": True,
            "scope": "1175_captured_BTC_ETH_Spot_trades_on_2026_10_09_not_all_July_trades",
            "sources": checks}


def future(out, now, model_root):
    plan = pinned_json(ROOT / "config/a6-future-holdout-20261010.json", "plan_sha256", PLAN_SHA)
    if not future_due(plan, now):
        return {"status": "WAITING_FULL_PREREGISTERED_FUTURE_WINDOW", "plan_sha256": PLAN_SHA,
                "start_date": plan["start_date"], "end_date": plan["end_date"],
                "pristine_future_holdout_complete": False}
    sha = subprocess.run(["git", "-C", str(model_root), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    if sha != plan["model_source_sha"]:
        raise ValueError("frozen model checkout changed")
    dirty = subprocess.run(["git", "-C", str(model_root), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        raise ValueError("tracked frozen model source changed")
    module = model_root / "nexus_signed_flow_price_response_research.py"
    if hashlib.sha256(module.read_bytes()).hexdigest() != plan["model_sha256"]:
        raise ValueError("frozen strategy module changed")
    market = out / "market"
    subprocess.run([sys.executable, str(model_root / "bybit_spot_archive_collector.py"),
                    "--start-date", plan["start_date"], "--end-date", plan["end_date"],
                    "--cache-root", str(out / "cache"), "--output-root", str(market)], check=True)
    sys.path.insert(0, str(model_root))
    import pandas as pd
    import nexus_signed_flow_price_response_research as a6
    loaded = a6._load_all(market)
    proof = loaded["proof"]
    if proof["start_date"] != plan["start_date"] or proof["end_date"] != plan["end_date"]:
        raise ValueError("future input dates differ from preregistration")
    rows = []
    for symbol in a6.SYMBOLS:
        frame = a6.prepare_symbol(market, symbol, loaded["flows"][symbol])
        expected = pd.date_range(plan["start_date"], periods=30 * 96, freq="15min", tz="UTC")
        if not frame["timestamp"].equals(pd.Series(expected)):
            raise ValueError("future UTC grid differs from preregistration")
        threshold = plan["thresholds"][symbol]
        signals = a6.build_signal(frame, threshold)
        for profile, (fee, slip) in plan["cost_profiles"].items():
            rows.append({"symbol": symbol, "profile": profile, "part": "preregistered_future_holdout",
                         "threshold_frozen": threshold, "bars": len(frame),
                         **a6.simulate(frame, signals, fee_bps=fee, slip_bps=slip)})
    return {"status": "FUTURE_RESEARCH_REPLAY_COMPLETE_INDEPENDENT_QA_REQUIRED",
            "plan_sha256": PLAN_SHA, "model_source_sha": sha,
            "input_proof_sha256": proof["proof_sha256"], "rows": rows,
            "pristine_future_holdout_complete": True, "independent_numeric_qa_complete": False,
            "execution_eligible": False, "historical_rejection_preserved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("live-side", "future", "both"), default="both")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model-root", type=Path, default=ROOT)
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=False)
    now = datetime.now(timezone.utc)
    report = {"schema": "nexus.a6-preregistered-validation-progress.v1",
              "checked_at_utc": now.isoformat(), "research_only": True,
              "automatic_strategy_promotion": False, "live_trading_authority": False}
    for mode in ("live-side", "future"):
        if args.mode not in (mode, "both"):
            continue
        try:
            report[mode] = live_side(args.output_root, now) if mode == "live-side" else future(args.output_root, now, args.model_root)
        except Exception as exc:
            report[mode] = {"status": "REJECTED_VALIDATION_ERROR", "reason": str(exc), "execution_eligible": False}
    report["report_sha256"] = digest(report)
    (args.output_root / "preregistered-validation-progress.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return int(any(v.get("status") == "REJECTED_VALIDATION_ERROR" for v in report.values() if isinstance(v, dict)))


if __name__ == "__main__":
    raise SystemExit(main())
