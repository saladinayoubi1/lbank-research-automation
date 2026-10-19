"""One-shot fixed future-source capture and independent QA, never trading.

Both operations stop before source I/O until the entire frozen horizon closes.
The original V5-only preflight and historical warmup are deliberately untouched.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil

from scripts import nexus_bybit_official_spot_raw_4h_adapter as producer
from scripts import nexus_bybit_official_spot_warmup_qa as independent

ROOT = Path(__file__).resolve().parents[1]
POLICY = "research/portfolio_v3_forward_raw_source_policy_v1.json"
POLICY_DIGEST = "b9023729d4c1a06755d8699b896376b90489ac8f132f5a2b2e59b6b7c776e075"
START = datetime(2026, 10, 19, tzinfo=timezone.utc)
END = datetime(2027, 1, 17, tzinfo=timezone.utc)
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MAX_FILE = 200_000_000
MAX_TOTAL = 1_500_000_000
CAPTURE_SCHEMA = "nexus.portfolio-v3-forward-official-raw-capture.v1"


class FutureRawSourceError(ValueError):
    pass


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def now_utc():
    return datetime.now(timezone.utc)


def closed_horizon():
    now = now_utc()
    if now.tzinfo is None or now.utcoffset() != timedelta(0) or now < END:
        raise FutureRawSourceError("Full frozen horizon incomplete; no source I/O permitted")
    return now


def unlinked(path):
    path = Path(path).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise FutureRawSourceError("Linked source/evidence path")
    return path


def regular(path, limit):
    path = unlinked(path)
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise FutureRawSourceError("Missing or oversized source/evidence file")
    return path


def sha_file(path, limit=MAX_FILE, *, lf=False):
    path = regular(path, limit)
    if lf:
        return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path, limit=2_000_000):
    def pairs(items):
        obj = {}
        for key, value in items:
            if key in obj:
                raise FutureRawSourceError("Duplicate receipt key")
            obj[key] = value
        return obj

    def constant(value):
        raise FutureRawSourceError("Nonfinite receipt number: " + value)

    obj = json.loads(regular(path, limit).read_text(encoding="utf-8"),
                     object_pairs_hook=pairs, parse_constant=constant)
    if type(obj) is not dict:
        raise FutureRawSourceError("Receipt must be an object")
    return obj


def write_once(path, obj):
    path = unlinked(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(obj, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def checked_policy(root=ROOT):
    policy = read_json(root / POLICY, 16384)
    if digest(policy) != POLICY_DIGEST:
        raise FutureRawSourceError("Reviewed raw-source policy changed")
    pins = policy["required_source_and_contract_sha256_lf"]
    for relative, expected in pins.items():
        if sha_file(root / relative, lf=True) != expected:
            raise FutureRawSourceError("Pinned source/contract changed: " + relative)
    for module, relative in (
        (producer, "scripts/nexus_bybit_official_spot_raw_4h_adapter.py"),
        (independent, "scripts/nexus_bybit_official_spot_warmup_qa.py"),
    ):
        if sha_file(Path(module.__file__), lf=True) != pins[relative]:
            raise FutureRawSourceError("Loaded source implementation differs from reviewed bytes")
    return policy


def jobs():
    for offset in range((END - START).days):
        day = (START + timedelta(days=offset)).date().isoformat()
        for symbol in SYMBOLS:
            yield symbol, day


def official_url(symbol, day):
    if (symbol, day) not in jobs():
        raise FutureRawSourceError("Outside fixed paired prospective source interval")
    return producer.URL_PATTERN.format(symbol=symbol, date=day)


def request_identity():
    return {"schema": CAPTURE_SCHEMA, "policy_digest": POLICY_DIGEST,
            "collector_sha256_lf": sha_file(Path(__file__), lf=True),
            "source_route": "OFFICIAL_SPOT_RAW_TRADES_UTC4H_NOT_V5_KLINES",
            "start_utc": "2026-10-19T00:00:00Z",
            "end_exclusive_utc": "2027-01-17T00:00:00Z",
            "symbols": list(SYMBOLS), "expected_daily_files": 180,
            "expected_4h_bars_per_asset": 540,
            "financial_dispatch_authorized": False, "paper_eligible": False,
            "live_enabled": False, "orders": 0}


def checked_digest(path, limit=2_000_000):
    obj = read_json(path, limit)
    if obj.get("digest") != digest({k: v for k, v in obj.items() if k != "digest"}):
        raise FutureRawSourceError("Receipt digest mismatch")
    return obj


def stamp(value):
    if not isinstance(value, str) or not value.endswith(("Z", "+00:00")):
        raise FutureRawSourceError("Acquisition time must be explicit UTC")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() != timedelta(0):
        raise FutureRawSourceError("Acquisition time must be UTC")
    return parsed


def check_cell(root, symbol, day, identity, now):
    stem = symbol + "_" + day
    raw = root / "raw" / (stem + ".csv.gz")
    receipt = root / "receipts" / (stem + ".json")
    cell = checked_digest(receipt, 32768)
    acquisition = cell.get("acquisition", {})
    url = official_url(symbol, day)
    size = regular(raw, MAX_FILE).stat().st_size
    if (cell.get("symbol") != symbol or cell.get("date") != day
            or cell.get("raw_file_name") != raw.name
            or cell.get("claimed_official_url") != url
            or cell.get("request_digest") != digest(identity)
            or cell.get("raw_file_sha256") != sha_file(raw)
            or not 100 < size < MAX_FILE or cell.get("raw_gzip_bytes") != size
            or acquisition.get("kind") != "direct_official_https_GET"
            or acquisition.get("requested_url") != url or acquisition.get("final_url") != url
            or acquisition.get("status_code") != 200
            or acquisition.get("tls_verification_required") is not True
            or acquisition.get("redirects_allowed") is not False
            or acquisition.get("received_bytes") != size
            or acquisition.get("content_length") not in (None, size)
            or cell.get("provider_origin_cryptographically_signed") is not False
            or cell.get("ready_to_score_prospective_strategy") is not False
            or cell.get("paper_eligible") is not False or cell.get("live_enabled") is not False
            or type(cell.get("orders")) is not int or cell["orders"] != 0):
        raise FutureRawSourceError("Unapproved source/acquisition binding: " + stem)
    started, completed = stamp(acquisition.get("started_utc")), stamp(acquisition.get("completed_utc"))
    if not END <= started <= completed <= now:
        raise FutureRawSourceError("Acquisition outside full closed horizon or observation time")
    return cell, {"symbol": symbol, "date": day, "receipt_sha256": sha_file(receipt, 32768),
                  "raw_file_sha256": cell["raw_file_sha256"], "raw_gzip_bytes": size,
                  "raw_trade_rows": cell["total_raw_trade_rows"]}


def download(session, symbol, day, destination, remaining_budget=MAX_FILE):
    closed_horizon()
    url = official_url(symbol, day)
    destination = unlinked(destination)
    if destination.name != symbol + "_" + day + ".csv.gz":
        raise FutureRawSourceError("Wrong raw filename")
    temporary = destination.with_suffix(destination.suffix + ".part")
    if destination.exists() or temporary.exists():
        raise FutureRawSourceError("Existing raw/partial source requires explicit recovery")
    byte_limit = min(MAX_FILE - 1, remaining_budget)
    if byte_limit <= 100:
        raise FutureRawSourceError("Remaining total raw source byte budget exhausted")
    started = now_utc().isoformat()
    with session.get(url, stream=True, timeout=(10, 30), allow_redirects=False,
                     verify=True) as response:
        if response.status_code != 200 or response.url != url or response.history:
            raise FutureRawSourceError("Official HTTPS GET denied, redirected or substituted")
        length = response.headers.get("Content-Length")
        expected = int(length) if length is not None else None
        if expected is not None and not 100 < expected <= byte_limit:
            raise FutureRawSourceError("Unapproved raw response size")
        count = 0
        with temporary.open("xb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                count += len(chunk)
                if count > byte_limit:
                    raise FutureRawSourceError("Raw download byte budget exceeded")
                handle.write(chunk)
        if count <= 100 or expected is not None and count != expected:
            raise FutureRawSourceError("Incomplete official raw response")
        acquisition = {"kind": "direct_official_https_GET", "requested_url": url,
                       "final_url": response.url, "status_code": 200,
                       "tls_verification_required": True, "redirects_allowed": False,
                       "started_utc": started, "completed_utc": now_utc().isoformat(),
                       "received_bytes": count, "content_length": expected,
                       "etag": response.headers.get("ETag"),
                       "last_modified": response.headers.get("Last-Modified")}
    temporary.replace(destination)
    return acquisition


def make_session():
    # Offline QA and the closed-horizon status path need no HTTP dependency.
    import requests
    return requests.Session()


def capture(output, root=ROOT):
    closed_horizon()
    checked_policy(root)
    output = unlinked(output)
    output.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output).free < 2 * MAX_TOTAL:
        raise FutureRawSourceError("Insufficient space for bounded raw capture")
    (output / "raw").mkdir(exist_ok=True)
    (output / "receipts").mkdir(exist_ok=True)
    identity = request_identity()
    request = output / "capture-request.json"
    if request.exists():
        if read_json(request, 16384) != identity:
            raise FutureRawSourceError("Resume request/code/policy changed")
    else:
        write_once(request, identity)
    files, total, trades = [], 0, 0
    with make_session() as session:
        session.trust_env = False
        session.headers["User-Agent"] = "NEXUS-Fixed-Forward-Source/1.0"
        for symbol, day in jobs():
            stem = symbol + "_" + day
            raw = output / "raw" / (stem + ".csv.gz")
            saved = output / "receipts" / (stem + ".json")
            unlinked(raw); unlinked(saved)
            if not saved.exists():
                acquisition = download(session, symbol, day, raw, MAX_TOTAL - total)
                cell = {**producer.aggregate_gzip_day(raw, symbol, day, sha_file(raw)),
                        "request_digest": digest(identity), "acquisition": acquisition}
                cell["digest"] = digest(cell)
                write_once(saved, cell)
            cell, item = check_cell(output, symbol, day, identity, closed_horizon())
            files.append(item)
            total += item["raw_gzip_bytes"]
            trades += item["raw_trade_rows"]
            if total > MAX_TOTAL:
                raise FutureRawSourceError("Total raw source byte budget exceeded")
            print(json.dumps({"completed_files": len(files), "expected": 180}), flush=True)
    summary = {**identity, "request_digest": digest(identity), "files": files,
               "completed_files": len(files), "raw_gzip_bytes": total, "raw_trade_rows": trades,
               "independent_full_tick_qa_complete": False,
               "provider_payload_exchange_signed": False,
               "external_host_attestation_verified": False}
    summary["digest"] = digest(summary)
    path = output / "capture-summary.json"
    if path.exists():
        if read_json(path) != summary:
            raise FutureRawSourceError("Completed source summary changed")
    else:
        write_once(path, summary)
    return summary


def verify(capture_root, output, root=ROOT):
    now = closed_horizon()
    if not __debug__:
        raise FutureRawSourceError("Independent Decimal QA requires assertions enabled")
    policy = checked_policy(root)
    output = unlinked(output)
    if output.exists():
        raise FutureRawSourceError("Independent source QA is write-once")
    identity = request_identity()
    if read_json(capture_root / "capture-request.json", 16384) != identity:
        raise FutureRawSourceError("Captured request differs from reviewed implementation")
    summary = checked_digest(capture_root / "capture-summary.json")
    if (any(summary.get(k) != v for k, v in identity.items())
            or summary.get("request_digest") != digest(identity)
            or summary.get("completed_files") != 180
            or summary.get("independent_full_tick_qa_complete") is not False
            or summary.get("provider_payload_exchange_signed") is not False
            or summary.get("external_host_attestation_verified") is not False
            or [(r["symbol"], r["date"]) for r in summary.get("files", [])] != list(jobs())):
        raise FutureRawSourceError("Incomplete or substituted full-horizon source manifest")
    coverage = {symbol: [] for symbol in SYMBOLS}
    total, trades, maximum_delta = 0, 0, Decimal(0)
    for item, (symbol, day) in zip(summary["files"], jobs()):
        cell, expected_item = check_cell(capture_root, symbol, day, identity, now)
        if item != expected_item:
            raise FutureRawSourceError("Summary detached from retained daily source receipt")
        raw = capture_root / "raw" / (symbol + "_" + day + ".csv.gz")
        reconstructed, count = independent.decimal_day(raw, day)
        if (count != item["raw_trade_rows"] or not 0 < count <= 12_000_000
                or len(cell["fully_observed_4h_bars"]) != 6):
            raise FutureRawSourceError("Independent tick count or six-bucket coverage mismatch")
        midnight = datetime.combine(date.fromisoformat(day), datetime.min.time(), timezone.utc)
        for number, (b, produced) in enumerate(zip(reconstructed, cell["fully_observed_4h_bars"])):
            stamp_utc = midnight + timedelta(hours=4 * number)
            if stamp(produced["timestamp"]) != stamp_utc:
                raise FutureRawSourceError("Source bucket time/grid mismatch")
            for field in ("open", "high", "low", "close"):
                delta = abs(b[field] - Decimal(str(produced[field])))
                if not delta.is_finite() or delta > Decimal("0.00000001"):
                    raise FutureRawSourceError("Independent price reconstruction mismatch")
            delta = abs(b["volume"] - Decimal(str(produced["volume"])))
            if not delta.is_finite() or delta > max(Decimal("0.000001"), abs(b["volume"]) * Decimal("0.0000000001")):
                raise FutureRawSourceError("Independent volume reconstruction mismatch")
            maximum_delta = max(maximum_delta, delta)
            if any(b[k] != produced[k] for k in ("trades", "first_trade_ms", "last_trade_ms")):
                raise FutureRawSourceError("Independent source chronology/count mismatch")
            coverage[symbol].append({"timestamp": stamp_utc.isoformat(),
                                     **{k: str(b[k]) for k in ("open", "high", "low", "close", "volume")},
                                     "raw_file_sha256": item["raw_file_sha256"],
                                     "receipt_sha256": item["receipt_sha256"]})
        if sha_file(raw) != item["raw_file_sha256"]:
            raise FutureRawSourceError("Raw source changed during independent QA")
        total += item["raw_gzip_bytes"]
        trades += count
        if total > MAX_TOTAL:
            raise FutureRawSourceError("Total raw source byte budget exceeded")
    if (summary.get("raw_gzip_bytes") != total or summary.get("raw_trade_rows") != trades
            or any(len(bars) != 540 for bars in coverage.values())):
        raise FutureRawSourceError("Full paired source totals mismatch")
    result = {"schema": "nexus.portfolio-v3-forward-official-raw-independent-qa.v1",
              "policy_digest": POLICY_DIGEST, "capture_digest": summary["digest"],
              "collector_and_qa_wrapper_sha256_lf": identity["collector_sha256_lf"],
              "independent_decimal_code_sha256_lf": sha_file(Path(independent.__file__), lf=True),
              "candidate_id": policy["candidate_id"], "source_route": identity["source_route"],
              "start_utc": identity["start_utc"], "end_exclusive_utc": identity["end_exclusive_utc"],
              "verified_files": 180, "verified_4h_bars_per_asset": 540,
              "raw_gzip_bytes": total, "raw_trade_rows": trades,
              "max_absolute_volume_difference": str(maximum_delta),
              "all_ticks_independently_reconstructed": True,
              "source_eligible_for_separate_research_handoff": True,
              "provider_payload_exchange_signed": False,
              "external_host_attestation_verified": False,
              "financial_executor_handoff_still_required": True,
              "strategy_backtest_performed": False, "financial_dispatch_authorized": False,
              "ready_for_strategy_result_or_paper": False,
              "paper_eligible": False, "live_enabled": False, "orders": 0,
              "files": summary["files"], "bars": coverage}
    result["digest"] = digest(result)
    write_once(output, result)
    return result


def status():
    closed = now_utc() >= END
    return {"status": "HORIZON_ELAPSED_SOURCE_STILL_REQUIRED" if closed else "BLOCKED_FULL_HORIZON_INCOMPLETE",
            "policy_digest": POLICY_DIGEST, "full_horizon_elapsed": closed,
            "source_prices_read": False, "ready_for_strategy_result_or_paper": False,
            "financial_dispatch_authorized": False, "paper_eligible": False,
            "live_enabled": False, "orders": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "capture", "qa"))
    parser.add_argument("--capture-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.action == "status":
        result = status()
    elif args.action == "capture":
        if args.output is None:
            parser.error("capture requires --output")
        result = capture(args.output)
    else:
        if args.capture_root is None or args.output is None:
            parser.error("qa requires --capture-root and --output")
        result = verify(args.capture_root, args.output)
    print(json.dumps({k: v for k, v in result.items() if k not in ("files", "bars")}, allow_nan=False))


if __name__ == "__main__":
    main()
