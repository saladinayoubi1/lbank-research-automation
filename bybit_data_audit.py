from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

from main import analyze_timestamp_integrity

BASE_URL = "https://api.bybit.com"
DEFAULT_OUTPUT_ROOT = Path("build/bybit_data_audit")
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVALS = {
    "15": ("minute15", pd.Timedelta(minutes=15)),
    "60": ("hour1", pd.Timedelta(hours=1)),
    "240": ("hour4", pd.Timedelta(hours=4)),
}
LIMIT = 1000


class BybitAuditError(RuntimeError):
    pass


def request_json(
    path: str,
    params: dict[str, Any],
    timeout_seconds: float = 20.0,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    client = session or requests.Session()
    response = client.get(f"{BASE_URL}{path}", params=params, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if payload.get("retCode") != 0:
        raise BybitAuditError(
            f"Bybit API error {payload.get('retCode')}: {payload.get('retMsg')}"
        )
    return payload


def verify_spot_instrument(
    symbol: str,
    fetch_json: Callable[..., dict[str, Any]] = request_json,
) -> dict[str, Any]:
    payload = fetch_json(
        "/v5/market/instruments-info",
        {"category": "spot", "symbol": symbol},
    )
    items = payload.get("result", {}).get("list", [])
    matches = [item for item in items if item.get("symbol") == symbol]
    if len(matches) != 1:
        return {
            "symbol": symbol,
            "found": False,
            "status": None,
            "base_coin": None,
            "quote_coin": None,
            "error": f"Expected one instrument, received {len(matches)}",
        }
    item = matches[0]
    return {
        "symbol": symbol,
        "found": True,
        "status": item.get("status"),
        "base_coin": item.get("baseCoin"),
        "quote_coin": item.get("quoteCoin"),
        "error": None,
    }


def closed_candle_end_ms(interval: str, now: pd.Timestamp | None = None) -> int:
    if interval not in INTERVALS:
        raise BybitAuditError(f"Unsupported interval: {interval}")
    current = now or pd.Timestamp.now(tz="UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    _, step = INTERVALS[interval]
    closed_start = current.floor(step) - step
    return int(closed_start.timestamp() * 1000)


def parse_kline_rows(
    rows: list[list[Any]],
    symbol: str,
    interval: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    records: list[dict[str, Any]] = []
    short_rows = 0
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            short_rows += 1
            continue
        records.append({
            "timestamp": row[0],
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "volume": row[5],
            "turnover": row[6],
        })

    frame = pd.DataFrame(records)
    if frame.empty:
        return frame, {
            "short_row_count": short_rows,
            "non_numeric_count": 0,
            "invalid_ohlc_count": 0,
            "negative_volume_count": 0,
        }

    frame["timestamp"] = pd.to_datetime(
        pd.to_numeric(frame["timestamp"], errors="coerce"),
        unit="ms",
        utc=True,
        errors="coerce",
    )
    numeric_columns = ["open", "high", "low", "close", "volume", "turnover"]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    non_numeric_mask = frame[["timestamp", *numeric_columns]].isna().any(axis=1)
    valid_numeric = frame.loc[~non_numeric_mask].copy()
    invalid_high = valid_numeric["high"] < valid_numeric[["open", "close", "low"]].max(axis=1)
    invalid_low = valid_numeric["low"] > valid_numeric[["open", "close", "high"]].min(axis=1)
    negative_volume = valid_numeric["volume"] < 0

    frame["symbol"] = symbol
    frame["timeframe"] = INTERVALS[interval][0]
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    return frame, {
        "short_row_count": short_rows,
        "non_numeric_count": int(non_numeric_mask.sum()),
        "invalid_ohlc_count": int((invalid_high | invalid_low).sum()),
        "negative_volume_count": int(negative_volume.sum()),
    }


def audit_kline_series(
    symbol: str,
    interval: str,
    fetch_json: Callable[..., dict[str, Any]] = request_json,
    now: pd.Timestamp | None = None,
) -> dict[str, Any]:
    timeframe, _ = INTERVALS[interval]
    payload = fetch_json(
        "/v5/market/kline",
        {
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "end": closed_candle_end_ms(interval, now=now),
            "limit": LIMIT,
        },
    )
    result = payload.get("result", {})
    if result.get("category") != "spot" or result.get("symbol") != symbol:
        raise BybitAuditError(
            f"Unexpected response identity: {result.get('category')} {result.get('symbol')}"
        )

    frame, quality = parse_kline_rows(result.get("list", []), symbol, interval)
    if frame.empty or frame["timestamp"].isna().all():
        integrity = {
            "expected_rows": 0,
            "missing_candles": 0,
            "gap_count": 0,
            "duplicate_count": 0,
            "off_grid_count": 0,
            "integrity_ok": False,
        }
    else:
        integrity = analyze_timestamp_integrity(frame["timestamp"].dropna(), timeframe)

    passed = (
        len(frame) == LIMIT
        and quality["short_row_count"] == 0
        and quality["non_numeric_count"] == 0
        and quality["invalid_ohlc_count"] == 0
        and quality["negative_volume_count"] == 0
        and bool(integrity["integrity_ok"])
    )
    return {
        "symbol": symbol,
        "category": "spot",
        "interval": interval,
        "timeframe": timeframe,
        "rows": int(len(frame)),
        "first_candle_utc": None if frame.empty else frame.iloc[0]["timestamp"].isoformat(),
        "last_candle_utc": None if frame.empty else frame.iloc[-1]["timestamp"].isoformat(),
        **quality,
        **integrity,
        "audit_passed": passed,
    }


def build_audit_report(
    request_pause_seconds: float = 0.1,
    fetch_json: Callable[..., dict[str, Any]] = request_json,
    now: pd.Timestamp | None = None,
) -> dict[str, Any]:
    instruments: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for symbol in SYMBOLS:
        try:
            instrument = verify_spot_instrument(symbol, fetch_json=fetch_json)
        except Exception as exc:
            instrument = {
                "symbol": symbol,
                "found": False,
                "status": None,
                "base_coin": None,
                "quote_coin": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
        instruments.append(instrument)
        if request_pause_seconds:
            time.sleep(request_pause_seconds)

    for symbol in SYMBOLS:
        for interval in INTERVALS:
            try:
                series.append(
                    audit_kline_series(
                        symbol,
                        interval,
                        fetch_json=fetch_json,
                        now=now,
                    )
                )
            except Exception as exc:
                errors.append({
                    "symbol": symbol,
                    "interval": interval,
                    "error": f"{type(exc).__name__}: {exc}",
                })
            if request_pause_seconds:
                time.sleep(request_pause_seconds)

    instruments_trading = sum(
        instrument["found"] and instrument["status"] == "Trading"
        for instrument in instruments
    )
    passed_series = sum(item["audit_passed"] for item in series)
    expected_series = len(SYMBOLS) * len(INTERVALS)
    candidate = (
        instruments_trading == len(SYMBOLS)
        and len(series) == expected_series
        and passed_series == expected_series
        and not errors
    )

    failure_counts = Counter()
    for item in series:
        if item["audit_passed"]:
            continue
        for key in [
            "short_row_count",
            "non_numeric_count",
            "invalid_ohlc_count",
            "negative_volume_count",
            "missing_candles",
            "duplicate_count",
            "off_grid_count",
        ]:
            if int(item.get(key, 0)) > 0:
                failure_counts[key] += 1
        if item["rows"] != LIMIT:
            failure_counts["row_limit_not_met"] += 1

    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "venue": "bybit",
        "scope": {
            "category": "spot",
            "symbols": SYMBOLS,
            "intervals": list(INTERVALS),
            "closed_candles_per_series": LIMIT,
            "public_requests_expected": len(SYMBOLS) + expected_series,
        },
        "summary": {
            "instruments_expected": len(SYMBOLS),
            "instruments_trading": int(instruments_trading),
            "series_expected": expected_series,
            "series_completed": len(series),
            "series_passed": int(passed_series),
            "request_errors": len(errors),
            "failure_counts": dict(sorted(failure_counts.items())),
            "candidate_for_full_backfill": candidate,
        },
        "instruments": instruments,
        "series": series,
        "errors": errors,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Bybit Public Spot Data Audit",
        "",
        f"Generated at: {report['generated_at_utc']}",
        "",
        "This is a bounded public-data audit. It does not write canonical data, use private APIs, or place orders.",
        "",
        "## Decision",
        "",
        f"- Candidate for full backfill: **{summary['candidate_for_full_backfill']}**",
        f"- Trading instruments: {summary['instruments_trading']} / {summary['instruments_expected']}",
        f"- Series passed: {summary['series_passed']} / {summary['series_expected']}",
        f"- Request errors: {summary['request_errors']}",
        "",
        "| Symbol | Timeframe | Rows | Missing | Gaps | Duplicates | Off-grid | Invalid OHLC | Passed |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["series"]:
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {missing_candles} | {gap_count} | {duplicate_count} | {off_grid_count} | {invalid_ohlc_count} | {audit_passed} |".format(**item)
        )
    if report["errors"]:
        lines.extend(["", "## Request errors", ""])
        for error in report["errors"]:
            lines.append(
                f"- `{error['symbol']} / {error['interval']}`: {error['error']}"
            )
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_root: Path, clean: bool) -> None:
    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_bybit_data_audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "_bybit_data_audit.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    pd.DataFrame(report["series"]).to_csv(
        output_root / "_bybit_data_audit.csv", index=False
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit recent closed Bybit spot candles through public V5 endpoints."
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--request-pause", type=float, default=0.1)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_audit_report(request_pause_seconds=args.request_pause)
    write_report(report, args.output_root, args.clean)
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["candidate_for_full_backfill"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
