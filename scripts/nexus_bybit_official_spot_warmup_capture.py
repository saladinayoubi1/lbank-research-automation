"""Bounded, resumable historical warmup capture; never scores a strategy.

Uses the existing official Spot raw-trade adapter. The only permitted days are
2026-08-01 through 2026-10-18. Every file gets a separate acquisition/parse receipt.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

import requests

from scripts.nexus_bybit_official_spot_raw_4h_adapter import (
    aggregate_gzip_day, _digest, _sha256_file, URL_PATTERN, SYMBOLS,
)

START = date(2026, 8, 1)
END = date(2026, 10, 19)
MAX_FILE = 200_000_000
MAX_TOTAL = 1_500_000_000
SCHEMA = "nexus.bybit-official-spot-historical-warmup-capture.v1"
ADAPTER_SHA256 = "978294ba83531f817de916fc6bf21cfb6145ac3191eb1a26e9803efa3e1628e2"


class CaptureError(ValueError):
    pass


def jobs():
    for offset in range((END - START).days):
        day = (START + timedelta(days=offset)).isoformat()
        for symbol in SYMBOLS:
            yield symbol, day


def checked_day(symbol, day):
    try:
        parsed = date.fromisoformat(day)
    except (TypeError, ValueError) as exc:
        raise CaptureError("invalid historical warmup day") from exc
    if symbol not in SYMBOLS or parsed.isoformat() != day or not START <= parsed < END:
        raise CaptureError("outside fixed historical warmup; future prices forbidden")


def atomic_json(path, obj):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(obj, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
    temporary.replace(path)


def fetch_file(session, symbol, day, destination):
    checked_day(symbol, day)
    url = URL_PATTERN.format(symbol=symbol, date=day)
    temporary = destination.with_suffix(destination.suffix + ".part")
    if destination.exists() or temporary.exists():
        raise CaptureError("do not overwrite existing raw file or partial download")
    started = datetime.now(timezone.utc).isoformat()
    with session.get(url, stream=True, timeout=(10, 30), allow_redirects=False) as response:
        if response.status_code != 200 or response.url != url:
            raise CaptureError(f"official source GET failed: {response.status_code} {url}")
        length = response.headers.get("Content-Length")
        expected = int(length) if length is not None else None
        if expected is not None and not 100 < expected < MAX_FILE:
            raise CaptureError("unexpected official raw file size")
        count = 0
        with temporary.open("xb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                count += len(chunk)
                if count >= MAX_FILE:
                    raise CaptureError("raw file byte budget exceeded")
                handle.write(chunk)
        if count <= 100 or (expected is not None and count != expected):
            raise CaptureError("incomplete HTTP body")
        receipt = {
            "kind": "direct_official_https_GET", "requested_url": url,
            "final_url": response.url, "status_code": response.status_code,
            "tls_verification_required": True, "redirects_allowed": False,
            "started_utc": started, "completed_utc": datetime.now(timezone.utc).isoformat(),
            "received_bytes": count, "content_length": expected,
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "server_date": response.headers.get("Date"),
        }
    temporary.replace(destination)
    return receipt


def capture(root, sample_root, sample_manifest):
    root = root.absolute()
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise CaptureError("linked capture directory")
    root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(root).free < 2 * MAX_TOTAL:
        raise CaptureError("insufficient free space for bounded capture")
    raw_root, receipt_root = root / "raw", root / "receipts"
    raw_root.mkdir(exist_ok=True); receipt_root.mkdir(exist_ok=True)
    adapter = Path(__file__).with_name("nexus_bybit_official_spot_raw_4h_adapter.py")
    if _sha256_file(adapter) != ADAPTER_SHA256:
        raise CaptureError("existing adapter source changed")
    sample = json.loads(sample_manifest.read_text(encoding="utf-8"))
    sample_sha = _sha256_file(sample_manifest)
    known = {(s["symbol"], s["date"]): s["raw_sha256"] for s in sample["samples"]}
    identity = {"schema": SCHEMA, "start_utc": "2026-08-01T00:00:00Z",
                "end_exclusive_utc": "2026-10-19T00:00:00Z", "symbols": list(SYMBOLS),
                "purpose": "historical_warmup_only_no_strategy_scoring",
                "expected_files": 158, "expected_4h_bars_per_symbol": 474,
                "existing_adapter_sha256": ADAPTER_SHA256,
                "capture_code_sha256": _sha256_file(Path(__file__)),
                "prior_sample_manifest_sha256": sample_sha,
                "max_total_raw_gzip_bytes": MAX_TOTAL,
                "future_source_authorized": False, "paper_eligible": False,
                "live_enabled": False, "orders": 0}
    request = root / "capture-request.json"
    if request.exists():
        if json.loads(request.read_text(encoding="utf-8")) != identity:
            raise CaptureError("resume request/source identity changed")
    else:
        atomic_json(request, identity)
    summaries, total = [], 0
    with requests.Session() as session:
        session.headers["User-Agent"] = "NEXUS-Research-Warmup/1.0"
        for symbol, day in jobs():
            stem = f"{symbol}_{day}"
            raw, saved = raw_root / (stem + ".csv.gz"), receipt_root / (stem + ".json")
            if saved.exists():
                cell = json.loads(saved.read_text(encoding="utf-8"))
                core = {k: v for k, v in cell.items() if k != "digest"}
                if (cell.get("digest") != _digest(core) or cell.get("request_digest") != _digest(identity)
                    or cell.get("symbol") != symbol or cell.get("date") != day
                    or raw.is_symlink() or not raw.is_file()
                    or cell["raw_file_sha256"] != _sha256_file(raw)):
                    raise CaptureError("resume checkpoint or raw bytes changed")
            else:
                if raw.exists():
                    raise CaptureError("unreceipted raw source requires explicit recovery")
                previous = sample_root / raw.name
                if (symbol, day) in known and previous.is_file() and not previous.is_symlink():
                    if _sha256_file(previous) != known[(symbol, day)]:
                        raise CaptureError("previously frozen sample SHA mismatch")
                    shutil.copyfile(previous, raw)
                    acquisition = {"kind": "previously_pinned_official_sample",
                                   "prior_manifest_sha256": sample_sha,
                                   "requested_url": URL_PATTERN.format(symbol=symbol, date=day)}
                else:
                    acquisition = fetch_file(session, symbol, day, raw)
                sha = _sha256_file(raw)
                cell = {**aggregate_gzip_day(raw, symbol, day, sha),
                        "request_digest": _digest(identity), "acquisition": acquisition,
                        "historical_warmup_only": True}
                cell["digest"] = _digest(cell)
                atomic_json(saved, cell)
                print(json.dumps({"completed": len(summaries) + 1, "expected": 158,
                                  "symbol": symbol, "day": day,
                                  "raw_trade_rows": cell["total_raw_trade_rows"]}), flush=True)
            total += cell["raw_gzip_bytes"]
            if total >= MAX_TOTAL:
                raise CaptureError("total historical capture byte budget exceeded")
            summaries.append({"symbol": symbol, "date": day,
                              "receipt_sha256": _sha256_file(saved),
                              "raw_file_sha256": cell["raw_file_sha256"],
                              "raw_gzip_bytes": cell["raw_gzip_bytes"],
                              "raw_trade_rows": cell["total_raw_trade_rows"],
                              "acquisition_kind": cell["acquisition"]["kind"]})
    assert len(summaries) == identity["expected_files"]
    complete = {**identity, "request_digest": _digest(identity), "files": summaries,
                "completed_files": len(summaries), "raw_gzip_bytes": total,
                "raw_trade_rows": sum(s["raw_trade_rows"] for s in summaries),
                "continuous_historical_warmup_captured": True,
                "independent_full_capture_qa_complete": False,
                "provider_payload_exchange_signed": False,
                "strategy_backtest_performed": False}
    complete["digest"] = _digest(complete)
    path = root / "capture-summary.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != complete:
            raise CaptureError("completed summary changed")
    else:
        atomic_json(path, complete)
    return complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-sample-root", type=Path, required=True)
    parser.add_argument("--prior-sample-manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = capture(args.output, args.prior_sample_root, args.prior_sample_manifest)
    except Exception as exc:
        print(json.dumps({"capture_complete": False, "error": type(exc).__name__,
                          "message": str(exc), "retry_performed": False}), file=sys.stderr, flush=True)
        raise
    print(json.dumps({"capture_complete": True, "files": result["completed_files"],
                      "trades": result["raw_trade_rows"], "digest": result["digest"]}), flush=True)


if __name__ == "__main__":
    main()
