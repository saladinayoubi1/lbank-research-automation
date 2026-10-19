"""Independent Decimal reconstruction of every captured historical raw day.

Does not import the producer, call a trading engine, or open future prices.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path


ORIGINAL_SHA256 = {
    "bybit_market/btc_usdt/hour1.parquet": "f8f2236785c036fe40808809397d47729b3add4c8f0b9e19c77d3b771f8e6847",
    "bybit_market/btc_usdt/hour4.parquet": "e0d019a76882a02dc463a34d1d9375841f81d412b9a3310d9e21c2d7b2738dc6",
    "bybit_market/btc_usdt/minute15.parquet": "c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
    "bybit_market/eth_usdt/hour1.parquet": "ba0743588c5089e6a6b250b4ebb029a43fea57d0a020df5ab1316c34efdcd88a",
    "bybit_market/eth_usdt/hour4.parquet": "292005e091d914fbb9d108c3d8d65e93785cc32b9c73e07ea02e0d44cf7da65b",
    "bybit_market/eth_usdt/minute15.parquet": "ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}


def sha_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def decimal_day(path, day):
    if not __debug__:
        raise RuntimeError("independent QA must run with assertions enabled")
    start = int(datetime.combine(date.fromisoformat(day), datetime.min.time(), timezone.utc).timestamp() * 1000)
    buckets = [None] * 6
    previous_id, previous_ms, count = 0, -1, 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        assert next(reader) == ["id", "timestamp", "price", "volume", "side", "rpi"]
        for fields in reader:
            assert len(fields) == 6
            ident, milliseconds = int(fields[0]), int(fields[1])
            price, volume = Decimal(fields[2]), Decimal(fields[3])
            assert ident > previous_id and milliseconds >= previous_ms
            assert start <= milliseconds < start + 86_400_000
            assert price.is_finite() and price > 0 and volume.is_finite() and volume > 0
            assert fields[4] in ("buy", "sell") and fields[5] in ("0", "1")
            number = (milliseconds - start) // 14_400_000
            b = buckets[number]
            if b is None:
                b = {"open": price, "high": price, "low": price, "close": price,
                     "volume": volume, "trades": 1, "first_trade_ms": milliseconds,
                     "last_trade_ms": milliseconds}
                buckets[number] = b
            else:
                b["high"] = max(b["high"], price)
                b["low"] = min(b["low"], price)
                b["close"] = price
                b["volume"] += volume
                b["last_trade_ms"] = milliseconds
                b["trades"] += 1
            previous_id, previous_ms = ident, milliseconds
            count += 1
    assert count > 0 and all(b is not None for b in buckets)
    return buckets, count


def verify(root, original_root, output):
    if not __debug__:
        raise RuntimeError("independent QA must run with assertions enabled")
    assert not output.exists(), "never overwrite an independent QA receipt"
    summary = json.loads((root / "capture-summary.json").read_text(encoding="utf-8"))
    assert summary["digest"] == digest({k: v for k, v in summary.items() if k != "digest"})
    assert summary["completed_files"] == 158 and len(summary["files"]) == 158
    assert summary["end_exclusive_utc"] == "2026-10-19T00:00:00Z"
    assert summary["purpose"] == "historical_warmup_only_no_strategy_scoring"
    assert summary["future_source_authorized"] is False and summary["live_enabled"] is False
    original = {}
    for relative, sha in ORIGINAL_SHA256.items():
        original[relative] = sha_file(original_root / relative)
        assert original[relative] == sha, relative
    expected = [(symbol, (date(2026, 8, 1) + timedelta(days=i)).isoformat())
                for i in range(79) for symbol in ("BTCUSDT", "ETHUSDT")]
    assert [(r["symbol"], r["date"]) for r in summary["files"]] == expected
    coverage, receipts, total, max_volume_delta = {"BTCUSDT": [], "ETHUSDT": []}, [], 0, Decimal(0)
    for item in summary["files"]:
        symbol, day = item["symbol"], item["date"]
        name = symbol + "_" + day
        receipt_path = root / "receipts" / (name + ".json")
        raw = root / "raw" / (name + ".csv.gz")
        assert not raw.is_symlink() and not receipt_path.is_symlink()
        assert sha_file(receipt_path) == item["receipt_sha256"]
        cell = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert cell["digest"] == digest({k: v for k, v in cell.items() if k != "digest"})
        assert cell["request_digest"] == summary["request_digest"]
        assert sha_file(raw) == item["raw_file_sha256"] == cell["raw_file_sha256"]
        official = f"https://public.bybit.com/spot/{symbol}/{name}.csv.gz"
        acquired = cell["acquisition"]
        assert acquired["requested_url"] == official
        if acquired["kind"] == "direct_official_https_GET":
            assert acquired["final_url"] == official and acquired["status_code"] == 200
            assert acquired["tls_verification_required"] is True
            assert acquired["redirects_allowed"] is False
            assert acquired["received_bytes"] == raw.stat().st_size
        else:
            assert acquired["kind"] == "previously_pinned_official_sample"
            assert acquired["prior_manifest_sha256"] == summary["prior_sample_manifest_sha256"]
            assert day in ("2026-08-01", "2026-10-17")
        reconstructed, count = decimal_day(raw, day)
        assert count == cell["total_raw_trade_rows"] == item["raw_trade_rows"]
        assert len(cell["fully_observed_4h_bars"]) == 6
        for i, (b, produced) in enumerate(zip(reconstructed, cell["fully_observed_4h_bars"])):
            stamp = datetime.combine(date.fromisoformat(day), datetime.min.time(), timezone.utc) + timedelta(hours=4 * i)
            assert datetime.fromisoformat(produced["timestamp"]) == stamp
            for field in ("open", "high", "low", "close"):
                assert abs(b[field] - Decimal(str(produced[field]))) <= Decimal("0.00000001")
            delta = abs(b["volume"] - Decimal(str(produced["volume"])))
            assert delta <= max(Decimal("0.000001"), abs(b["volume"]) * Decimal("0.0000000001"))
            max_volume_delta = max(max_volume_delta, delta)
            assert all(b[k] == produced[k] for k in ("trades", "first_trade_ms", "last_trade_ms"))
            coverage[symbol].append({"timestamp": stamp.isoformat(),
                                     **{k: str(b[k]) for k in ("open", "high", "low", "close", "volume")},
                                     "raw_file_sha256": item["raw_file_sha256"],
                                     "receipt_sha256": item["receipt_sha256"]})
        total += count
        receipts.append({**item, "independent_decimal_4h_match": True})
        print(json.dumps({"independently_verified_files": len(receipts), "expected": 158,
                          "symbol": symbol, "day": day}), flush=True)
    assert total == summary["raw_trade_rows"]
    assert len(coverage["BTCUSDT"]) == len(coverage["ETHUSDT"]) == 474
    assert [b["timestamp"] for b in coverage["BTCUSDT"]] == [b["timestamp"] for b in coverage["ETHUSDT"]]
    result = {"schema": "nexus.bybit-official-spot-historical-warmup-independent-qa.v1",
              "capture_digest": summary["digest"], "qa_code_sha256": sha_file(Path(__file__)),
              "original_archive_six_sha256_rechecked": original,
              "verified_files": 158, "verified_4h_bars": 948, "raw_trade_rows": total,
              "max_absolute_volume_difference": str(max_volume_delta),
              "all_daily_bars_independently_reconstructed": True,
              "capture_transport_receipts_checked": True,
              "provider_payload_exchange_signed": False,
              "independent_external_provider_attestation": False,
              "historical_warmup_only": True, "future_source_authorized": False,
              "strategy_backtest_performed": False, "paper_eligible": False,
              "live_enabled": False, "orders": 0, "files": receipts, "bars": coverage}
    result["digest"] = digest(result)
    output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"qa_complete": True, "files": 158, "bars": 948,
                      "raw_trade_rows": total, "digest": result["digest"]}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-root", required=True, type=Path)
    parser.add_argument("--original-archive-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    verify(args.capture_root, args.original_archive_root, args.output)
