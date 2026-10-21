"""Reconstruct one already-reported July frame; no strategy or window search.

The old reader parsed CSV columns as strings, then used pd.to_numeric. This
bounded adapter applies those conversions per chunk, verifies the entire raw
stream, and passes the concatenated numeric trade columns to the unmodified
historical trades_to_range_candles function. It avoids retaining all raw text.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import platform
import sys
from decimal import Decimal
from pathlib import Path

SOURCE_COMMIT = "d60c063a2a79d2359538d48dd6088133c704eb8f"
RAW_SHA = "72612fea915ecc542c8d2683d957588e4dc5e097138d1af3cafc08a1509675db"
OLD_FRAME_SHA = "c75ca7e7a74c0ff3a4d51f5a12a9ac27232563a03a1a87b61b5d65851fe47cc9"
CACHE_FRAME_SHA = "e510acb8cf58369880445d2c1ff6d7764234f3718e99902c31b7cf9b239dfa9e"
INPUT_DIGEST = "fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
START, END, STEP = 1782864000000, 1785542400000, 14400000
FILES = {
    "bybit_spot_archive_audit.py": "81398de7cee4020b303355e77ce4657247f6c26736d03037cc0d9100e477338c",
    "bybit_spot_backfill.py": "4d370f4a468689cda5718ffa65696571af7c31066e8494255a16c01f264f966d",
    "bybit_spot_archive_collector.py": "4851839b4eba2646189d17a5a1cd4e0106e47511f37274ee74af2115b25b23a5",
    "run_bybit_spot_archive_audit.py": "6fb08e27068d8d4aa161e2a2d89d4c16349aee14a6c5fd628914f1ef329b8a9d",
    "nexus_multitimeframe_strategy_discovery.py": "aa9d335900226ce671a543ed256b9069d6870a71c06f0cf4a6cfebb9490bd664",
    "nexus_monthly_four_pair_pre_demo.py": "282a6e4e736191cae5f317a87c074e790bdb02bc0b62cd43fc2fcde634fc0de2",
    "nexus_monthly_ten_variant_pre_demo.py": "703153b5259ae75093db1c6b010e49efa73ae230b78424271c66a8803bd00f70",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_bytes(path):
    # Git source is LF. A host checkout may materialize only CRLF line endings.
    raw = Path(path).read_bytes()
    return raw.replace(b"\r\n", b"\n")


def run(raw_path, legacy_root, prepared_path, output, chunk_rows=250000):
    import numpy as np
    import pandas as pd

    output, legacy_root, raw_path = Path(output), Path(legacy_root), Path(raw_path)
    require(not output.exists(), "refuse to overwrite a prior audit")
    sources = {}
    for name, expected in FILES.items():
        b = source_bytes(legacy_root / name)
        require(hashlib.sha256(b).hexdigest() == expected, "historical source changed: " + name)
        sources[name] = {"sha256_lf": expected, "git_blob": hashlib.sha1(
            f"blob {len(b)}\0".encode() + b).hexdigest()}
    require(raw_path.stat().st_size == 101492248 and file_sha(raw_path) == RAW_SHA,
            "raw July archive does not match original workbook bytes/hash")
    prepared = json.loads(Path(prepared_path).read_text(encoding="utf-8"))
    require(prepared["input_digest"] == INPUT_DIGEST == digest(
        {k: v for k, v in prepared.items() if k != "input_digest"}), "prepared input changed")
    cached = [r for r in prepared["rows"] if START <= r[0] < END]
    require(len(cached) == 186 and digest(cached) == CACHE_FRAME_SHA, "accepted July frame changed")
    sys.path.insert(0, str(legacy_root.resolve()))
    audit = importlib.import_module("bybit_spot_archive_audit")
    backfill = importlib.import_module("bybit_spot_backfill")
    sim = importlib.import_module("nexus_multitimeframe_strategy_discovery")
    for module in [audit, backfill, sim]:
        require(Path(module.__file__).resolve().parent == legacy_root.resolve(), "wrong import root")
    header = audit._first_nonempty_archive_row(raw_path)
    require(header == ["id", "timestamp", "price", "volume", "side"], "unexpected raw schema")
    names = audit._extended_named_header(header)
    require(len(names) == 6, "expected known optional RPI column")
    parts, rows, last_id, last_time, chunks = [], 0, -1, -1, 0
    for raw in pd.read_csv(raw_path, compression="gzip", header=None, names=list(names),
                           skiprows=1, dtype="string", low_memory=False,
                           chunksize=chunk_rows, on_bad_lines="error"):
        frame = audit.normalize_named_columns(raw)
        require(not frame[["trade_id", "timestamp", "price", "size", "side"]].isna().any().any(),
                "missing mandatory raw field")
        ids = pd.to_numeric(frame["trade_id"], errors="raise").to_numpy(dtype="int64")
        times = pd.to_numeric(frame["timestamp"], errors="raise")
        ms = times.to_numpy(dtype="int64")
        require(ids[0] > last_id and bool((np.diff(ids) > 0).all()), "raw IDs not unique/increasing")
        require(ms[0] >= last_time and bool((np.diff(ms) >= 0).all()), "raw time is not ordered")
        require(bool(((ms >= START) & (ms < END)).all()), "raw timestamp outside July")
        require(bool(frame["side"].str.strip().str.title().isin(["Buy", "Sell"]).all()), "raw side")
        require(bool((frame["rpi"].isna() | frame["rpi"].isin(["0", "1"])).all()), "raw RPI")
        # Exact conversions from the historical read_trade_archive reader.
        frame["timestamp"] = pd.to_datetime(times, unit="ms", utc=True, errors="raise")
        frame["size"] = pd.to_numeric(frame["size"], errors="raise")
        frame["price"] = pd.to_numeric(frame["price"], errors="raise")
        vals = frame[["size", "price"]].to_numpy(dtype=float)
        require(bool(np.isfinite(vals).all()) and bool((vals[:, 0] >= 0).all())
                and bool((vals[:, 1] > 0).all()), "invalid raw numeric field")
        parts.append(frame[["timestamp", "size", "price"]].copy())
        rows += len(frame)
        chunks += 1
        last_id, last_time = int(ids[-1]), int(ms[-1])
        if chunks % 16 == 0:
            print(json.dumps({"stage": "legacy_string_parse", "rows": rows}), flush=True)
    require(rows == 15348822, "historical full raw row count mismatch")
    trades = pd.concat(parts, ignore_index=True)
    del parts
    require(trades["timestamp"].is_monotonic_increasing, "concatenated raw order")
    # The original aggregation and its full-month candle integrity gates run unchanged.
    full = backfill.trades_to_range_candles(trades, "BTCUSDT", "hour4", "2026-07-01", "2026-07-31")
    del trades
    historical = [[int(r.timestamp.value // 1000000), str(r.open), str(r.high), str(r.low),
                   str(r.close), str(r.volume)] for r in full.itertuples(index=False)]
    require(len(historical) == 186 and all(r[0] == START + i * STEP
                for i, r in enumerate(historical)), "original candle cadence/coverage")
    h = digest(historical)
    print(json.dumps({"stage": "original_aggregation", "frame_sha256": h,
                      "matches_original_workbook": h == OLD_FRAME_SHA}), flush=True)
    differences = []
    fields = ["timestamp", "open", "high", "low", "close", "volume"]
    for old, cache in zip(historical, cached):
        for i, field in enumerate(fields):
            if old[i] != cache[i]:
                differences.append({"timestamp_ms": old[0], "field": field,
                    "historical_value": old[i], "retest_cached_value": cache[i],
                    "absolute_numeric_difference": str(abs(Decimal(str(old[i])) - Decimal(str(cache[i]))))})
    params = {"lookback": 40, "entry_z": -2, "exit_z": 0}
    signal = sim.generate_targets(full, "mean_reversion", params)
    cache_frame = pd.DataFrame(cached, columns=fields)
    for field in fields[1:]:
        cache_frame[field] = cache_frame[field].astype(float)
    cache_signal = sim.generate_targets(cache_frame, "mean_reversion", params)
    require(signal.tolist() == cache_signal.tolist(), "historical/cached MR40 target mismatch")
    metrics = []
    for label, start, fee, slip in [("full_normal", 0, 10, 5), ("holdout_normal", 130, 10, 5),
                                     ("holdout_stress", 130, 25, 15)]:
        m = sim._simulate(full, signal, start, 186, {"fee_bps": fee, "slippage_bps": slip},
                          bars_per_year=sim.TIMEFRAME_BARS_PER_YEAR["hour4"])
        c = sim._simulate(cache_frame, cache_signal, start, 186,
                          {"fee_bps": fee, "slippage_bps": slip},
                          bars_per_year=sim.TIMEFRAME_BARS_PER_YEAR["hour4"])
        require(m == c, "historical/cached exact engine metric mismatch")
        metrics.append({"control": label, "net_pnl_usdt": m["total_return"] * 10000,
                        "net_return_pct": m["total_return"] * 100,
                        "max_close_drawdown_pct": m["max_drawdown"] * 100,
                        "fills": m["fill_count"], "metrics_exactly_equal_to_cached_frame": True})
    expected = [(195.4101, 1.9541, 1.5075, 4), (195.4101, 1.9541, 1.5075, 4),
                (93.9639, 0.9396, 1.5075, 4)]
    for m, e in zip(metrics, expected):
        require(tuple(round(m[f], 4) for f in ["net_pnl_usdt", "net_return_pct",
                "max_close_drawdown_pct"]) + (m["fills"],) == e, "original reported metric changed")
    result = {"schema": "nexus.mr40-july-frame-identity.v1", "source_commit": SOURCE_COMMIT,
        "audit_driver_sha256_lf": hashlib.sha256(source_bytes(__file__)).hexdigest(),
        "historical_source_files": sources, "raw_archive_sha256": RAW_SHA,
        "raw_archive_bytes": 101492248, "raw_rows": rows, "parser_chunks": chunks,
        "chunk_rows": chunk_rows, "raw_stream_checked_through_gzip_eof": True,
        "raw_ids_strictly_increasing": True, "raw_times_nondecreasing": True,
        "historical_parser_adapter": "chunked string reader, exact original numeric conversions; concatenated numeric trades; unchanged original full-month aggregation and candle integrity gates",
        "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
        "prepared_input_digest": INPUT_DIGEST, "original_workbook_frame_sha256": OLD_FRAME_SHA,
        "reconstructed_historical_frame_sha256": h, "accepted_cached_frame_sha256": CACHE_FRAME_SHA,
        "original_workbook_frame_reconstructed": h == OLD_FRAME_SHA,
        "cached_frame_has_original_full_identity": digest(cached) == OLD_FRAME_SHA,
        "historical_and_cached_numeric_ohlc_exactly_equal": all(
            [Decimal(v) for v in a[1:5]] == [Decimal(v) for v in b[1:5]]
            for a, b in zip(historical, cached)),
        "differing_string_cells_by_column": {f: sum(d["field"] == f for d in differences) for f in fields},
        "maximum_absolute_volume_difference_btc": str(max(
            [Decimal(d["absolute_numeric_difference"]) for d in differences if d["field"] == "volume"] or [Decimal(0)])),
        "all_186_targets_equal": True, "historical_metric_controls": metrics,
        "same_hash_serialization_schema": True, "new_market_window": False,
        "parameter_search": False, "independent_qualification": False,
        "research_only": True, "live_enabled": False, "orders": 0, "auto_demo": False}
    result["audit_digest"] = digest(result)
    output.mkdir(parents=True, exist_ok=False)
    (output / "audit.json").write_bytes(canonical(result) + b"\n")
    (output / "historical_july_frame.json").write_bytes(canonical(historical) + b"\n")
    with (output / "frame_differences.csv").open("w", encoding="utf-8", newline="") as stream:
        keys = ["timestamp_ms", "field", "historical_value", "retest_cached_value", "absolute_numeric_difference"]
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(differences)
    print(json.dumps({"audit_digest": result["audit_digest"], "reconstructed": h == OLD_FRAME_SHA,
                      "different_cells": result["differing_string_cells_by_column"]}), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw", required=True, type=Path)
    p.add_argument("--legacy-root", required=True, type=Path)
    p.add_argument("--prepared-inputs", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--chunk-rows", type=int, default=250000)
    a = p.parse_args()
    require(10000 <= a.chunk_rows <= 1000000, "chunk size outside bounded range")
    run(a.raw, a.legacy_root, a.prepared_inputs, a.output, a.chunk_rows)


if __name__ == "__main__":
    main()
