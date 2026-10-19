"""Join approved historical warmup to the fixed engine's context, never P/L.

Rechecks existing source bytes and consumes the already completed Decimal QA;
does not repeat tick aggregation, fetch data or dispatch any financial task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as engine
from scripts import nexus_bybit_official_spot_warmup_qa as source_qa

ROOT = Path(__file__).resolve().parents[1]
PLAN = "research/portfolio_v3_warmup_context_v1.json"
HANDOFF = "research/portfolio_v3_fixed_source_handoff_20261019.json"
PLAN_DIGEST = "a246e384ada17ac538bbf06ea016b2c41862a1321fcd86f6a8e880880e09b90b"
HANDOFF_SHA = "8547412a0c6c4500848ca5773bec2f0226094ea075fa4f87dfc4dc3e24bc872e"
QA_CODE_SHA = "5b9a2c5261d2ca844cd11807c7e518a65ce211cec7401cd5e828e7f6dbf1b5f0"
SYMBOLS = ["btc_usdt", "eth_usdt"]
EXCHANGE = ["BTCUSDT", "ETHUSDT"]
ANCHOR = pd.Timestamp("2022-12-01T00:00:00Z")
SEAM = pd.Timestamp("2026-08-01T00:00:00Z")
CUTOFF = pd.Timestamp("2026-10-19T00:00:00Z")
PRICE_KEYS = ("open", "high", "low", "close")


class ContextError(ValueError):
    pass


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def regular_file(path, limit):
    path = Path(path)
    if (path.is_symlink() or any(p.is_symlink() for p in path.parents)
            or not path.is_file() or not 0 < path.stat().st_size <= limit):
        raise ContextError("Missing, linked or oversized context input: " + str(path))
    return path


def sha_file(path, limit=200_000_000, *, lf=False):
    path = regular_file(path, limit)
    if lf:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path, limit=1_000_000):
    return json.loads(regular_file(path, limit).read_text(encoding="utf-8-sig"))


def checked_contract(root):
    plan = read_json(root / PLAN, 16384)
    spec = read_json(root / HANDOFF, 16384)
    if digest(plan) != PLAN_DIGEST or sha_file(root / HANDOFF, lf=True) != HANDOFF_SHA:
        raise ContextError("Reviewed context plan or fixed handoff changed")
    for relative, expected in spec["code_and_contract_sha256_lf_normalized"].items():
        if sha_file(root / relative, lf=True) != expected:
            raise ContextError("Original engine/contract changed: " + relative)
    if (sha_file(Path(engine.__file__), lf=True)
            != spec["code_and_contract_sha256_lf_normalized"]["bybit_portfolio_search_v3.py"]
            or sha_file(Path(source_qa.__file__), lf=True) != QA_CODE_SHA):
        raise ContextError("Loaded engine or original source verifier mismatch")
    return plan, spec


def checked_receipt(path, expected):
    obj = read_json(path)
    core = {k: v for k, v in obj.items() if k != "digest"}
    if obj.get("digest") != expected or digest(core) != expected:
        raise ContextError("Approved receipt digest mismatch")
    return obj


def attest_sources(capture_root, archive_root, plan):
    summary = checked_receipt(capture_root / "capture-summary.json", plan["capture_digest"])
    qa = checked_receipt(capture_root / "independent-source-qa.json",
                         plan["independent_warmup_qa_digest"])
    if qa["capture_digest"] != summary["digest"]:
        raise ContextError("QA detached from approved capture")
    original = {}
    for relative, expected in source_qa.ORIGINAL_SHA256.items():
        actual = sha_file(archive_root / relative, 20_000_000)
        if actual != expected or qa["original_archive_six_sha256_rechecked"][relative] != expected:
            raise ContextError("Original six-file source bytes changed")
        original[relative] = actual
    for item in summary["files"]:
        stem = item["symbol"] + "_" + item["date"]
        raw = capture_root / "raw" / (stem + ".csv.gz")
        receipt = capture_root / "receipts" / (stem + ".json")
        if (sha_file(raw) != item["raw_file_sha256"]
                or sha_file(receipt, 32768) != item["receipt_sha256"]):
            raise ContextError("Previously verified raw day or receipt changed: " + stem)
    return qa, {"original_archive_six_sha256": original,
                "raw_days_rehashed": len(summary["files"]),
                "day_receipts_rehashed": len(summary["files"]),
                "capture_digest": summary["digest"], "independent_qa_digest": qa["digest"]}


def validate_market(market, end):
    ts = market["timestamps"]
    expected = pd.date_range(ANCHOR, end, freq="4h", inclusive="left")
    if (market["symbols"] != SYMBOLS or not isinstance(ts, pd.Series)
            or str(ts.dtype) != "datetime64[ns, UTC]"
            or not pd.DatetimeIndex(ts).equals(expected)):
        raise ContextError("Source context must retain the complete original UTC 4h grid")
    for key in PRICE_KEYS:
        values = market[key]
        if values.shape != (len(ts), 2) or not np.isfinite(values).all() or (values <= 0).any():
            raise ContextError("Invalid context prices")
    if ((market["high"] < np.maximum(market["open"], market["close"])).any()
            or (market["low"] > np.minimum(market["open"], market["close"])).any()
            or (market["low"] > market["high"]).any()):
        raise ContextError("Invalid context OHLC envelope")


def join_warmup(original, warmup_bars):
    validate_market(original, SEAM)
    frames = []
    expected = pd.date_range(SEAM, CUTOFF, freq="4h", inclusive="left")
    for symbol in EXCHANGE:
        frame = pd.DataFrame(warmup_bars[symbol])
        raw_times = frame["timestamp"]
        if not all(isinstance(t, str) and (t.endswith("+00:00") or t.endswith("Z"))
                   for t in raw_times):
            raise ContextError("Warmup timestamps must be explicitly UTC")
        times = pd.to_datetime(raw_times, utc=True)
        values = frame[[*PRICE_KEYS, "volume"]].to_numpy(float)
        if (not pd.DatetimeIndex(times).equals(expected) or not np.isfinite(values).all()
                or (values <= 0).any()):
            raise ContextError("Warmup has missing/duplicate/future bars or invalid physical values")
        frames.append(frame)
    joined = {"symbols": list(SYMBOLS), "timestamps": pd.concat([
        original["timestamps"], pd.Series(expected)], ignore_index=True)}
    for key in PRICE_KEYS:
        joined[key] = np.vstack([original[key], np.column_stack([
            f[key].to_numpy(float) for f in frames])])
    validate_market(joined, CUTOFF)
    return joined


def array_digest(values):
    values = np.asarray(values, dtype="<f8").copy()
    values[np.isnan(values)] = np.nan
    return hashlib.sha256(str(values.shape).encode() + values.tobytes()).hexdigest()


def compute_context(original, joined, spec):
    validate_market(original, SEAM)
    validate_market(joined, CUTOFF)
    n = len(original["timestamps"])
    if any(not np.array_equal(original[k], joined[k][:n]) for k in PRICE_KEYS):
        raise ContextError("Original source prefix changed during join")
    candidate = spec["candidate"]
    if engine.candidate_id(candidate["family"], candidate["params"]) != "b4e4a2c33304aec1":
        raise ContextError("Original candidate changed")
    features = []
    for market in (original, joined):
        score, eligible = engine.build_structural_state(market, candidate)
        vol = engine.realized_vol(market["close"], 30)
        weights = engine.construct_weights((score, eligible), vol, candidate)
        features.append({"score": score, "eligible": eligible, "volatility": vol, "target": weights})
    if any(not np.array_equal(values, features[1][key][:n], equal_nan=True)
           for key, values in features[0].items()):
        raise ContextError("Appending warmup changed original feature/target prefix")
    schedule = engine._candidate_rebalance_mask(len(joined["timestamps"]), candidate)
    last = int(np.flatnonzero(schedule)[-1])
    next_review = ANCHOR + pd.Timedelta(hours=4 * (last + 42))
    latest = features[1]
    return {"original_feature_target_prefix_rows_preserved": n,
            "original_price_prefix_preserved": True,
            "feature_array_sha256": {k: array_digest(v) for k, v in latest.items()},
            "global_review_mask_sha256": array_digest(schedule),
            "last_review_source_open_utc": joined["timestamps"].iloc[last].isoformat(),
            "next_review_source_open_utc": next_review.isoformat(),
            "next_review_observed_at_utc": (next_review + pd.Timedelta(hours=4)).isoformat(),
            "last_completed_source_open_utc": joined["timestamps"].iloc[-1].isoformat(),
            "last_completed_bar_closed_at_utc": CUTOFF.isoformat(),
            "last_closed_context_not_order_intent": {
                key: value[-1].tolist() for key, value in latest.items()}}


def load_market_bundle(path, expected_sha):
    if sha_file(path, 5_000_000) != expected_sha:
        raise ContextError("Prepared market bundle changed")
    with np.load(path, allow_pickle=False) as data:
        if set(data.files) != {"timestamps_ns", *PRICE_KEYS}:
            raise ContextError("Unexpected prepared bundle schema")
        market = {key: data[key].copy() for key in PRICE_KEYS}
        market["timestamps"] = pd.Series(pd.to_datetime(data["timestamps_ns"], utc=True))
    market["symbols"] = list(SYMBOLS)
    validate_market(market, CUTOFF)
    return market


def prepare(capture_root, archive_root, output, root=ROOT):
    if output.exists() or output.is_symlink() or any(p.is_symlink() for p in output.parents):
        raise ContextError("A new unlinked write-once context directory is required")
    plan, spec = checked_contract(root)
    qa, sources = attest_sources(capture_root, archive_root, plan)
    original = engine.load_market(archive_root, SYMBOLS)
    joined = join_warmup(original, qa["bars"])
    context = compute_context(original, joined, spec)
    output.mkdir(parents=True)
    bundle = output / "joined-market-4h.npz"
    np.savez_compressed(bundle, timestamps_ns=joined["timestamps"].astype("int64").to_numpy(),
                        **{k: joined[k] for k in PRICE_KEYS})
    bundle_sha = sha_file(bundle, 5_000_000)
    restored = load_market_bundle(bundle, bundle_sha)
    if any(not np.array_equal(restored[k], joined[k]) for k in PRICE_KEYS):
        raise ContextError("Prepared market round-trip mismatch")
    report = {"schema": "nexus.portfolio-v3-verified-warmup-context.v1",
              "plan_digest": PLAN_DIGEST, "fixed_handoff_sha256_lf": HANDOFF_SHA,
              "script_sha256_lf": sha_file(Path(__file__), lf=True),
              "source_bindings": sources, "context": context,
              "symbols": EXCHANGE, "original_rows_per_asset": len(original["timestamps"]),
              "warmup_rows_per_asset": len(joined["timestamps"]) - len(original["timestamps"]),
              "joined_rows_per_asset": len(joined["timestamps"]),
              "joined_market_bundle_sha256": bundle_sha,
              "engine_bundle_round_trip_verified": True,
              "status": "HISTORICAL_CONTEXT_PREPARED_FINANCIAL_DISPATCH_BLOCKED",
              "future_source_policy_still_required": True, "future_source_prices_read": False,
              "source_provider_exchange_signature_verified": False,
              "formal_independent_signal_or_financial_qa_complete": False,
              "strategy_backtest_performed": False, "financial_dispatch_authorized": False,
              "paper_eligible": False, "live_enabled": False, "orders": 0}
    report["digest"] = digest(report)
    with (output / "context.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--capture-root", type=Path, required=True)
    ap.add_argument("--archive-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(prepare(args.capture_root, args.archive_root, args.output), allow_nan=False))


if __name__ == "__main__":
    main()
