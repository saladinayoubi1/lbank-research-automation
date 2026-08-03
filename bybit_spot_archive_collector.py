from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import bybit_spot_archive_audit as audit
from run_bybit_spot_archive_audit import robust_download_archive

DEFAULT_OUTPUT_ROOT = Path("build/bybit_market")
DEFAULT_CACHE_ROOT = Path("build/bybit_spot_archive_cache")
DEFAULT_START_DATE = "2026-07-30"
DEFAULT_END_DATE = "2026-08-01"
CANONICAL_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "symbol",
    "timeframe",
]


class BybitCollectorError(RuntimeError):
    pass


def canonical_symbol(symbol: str) -> str:
    normalized = symbol.upper()
    if not normalized.endswith("USDT") or len(normalized) <= 4:
        raise BybitCollectorError(f"Unsupported Spot symbol: {symbol}")
    return f"{normalized[:-4].lower()}_usdt"


def inclusive_audit_dates(start_date: str, end_date: str) -> list[str]:
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if end < start:
        raise BybitCollectorError("end_date cannot be before start_date")
    return [
        timestamp.strftime("%Y-%m-%d")
        for timestamp in pd.date_range(start, end, freq="1D")
    ]


def expected_index(
    start_date: str,
    end_date: str,
    timeframe: str,
) -> pd.DatetimeIndex:
    if timeframe not in audit.TIMEFRAME_DELTAS:
        raise BybitCollectorError(f"Unsupported timeframe: {timeframe}")
    start = pd.Timestamp(start_date, tz="UTC")
    end_exclusive = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(1, unit="D")
    return pd.date_range(
        start,
        end_exclusive,
        freq=audit.TIMEFRAME_DELTAS[timeframe],
        inclusive="left",
    )


def validate_archive_quality(quality: dict[str, int]) -> tuple[bool, list[str]]:
    checks = [
        "invalid_numeric_rows",
        "invalid_symbol_rows",
        "invalid_side_rows",
        "non_positive_price_rows",
        "negative_size_rows",
        "outside_audit_day_rows",
        "duplicate_trade_id_count",
    ]
    failures = [name for name in checks if int(quality.get(name, 0)) > 0]
    if int(quality.get("valid_trade_rows", 0)) == 0:
        failures.append("no_valid_trade_rows")
    return not failures, failures


def evaluate_series(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    expected = expected_index(start_date, end_date, timeframe)
    canonical = canonical_symbol(symbol)

    if frame.empty:
        normalized = pd.DataFrame(columns=CANONICAL_COLUMNS)
        raw_index = pd.DatetimeIndex([], tz="UTC")
        invalid_ohlc_count = 0
        negative_volume_count = 0
        identity_error_count = 0
    else:
        normalized = frame.loc[:, CANONICAL_COLUMNS].copy()
        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"], utc=True, errors="raise"
        )
        for column in ["open", "high", "low", "close", "volume"]:
            normalized[column] = pd.to_numeric(normalized[column], errors="raise")
        normalized["symbol"] = canonical
        normalized["timeframe"] = timeframe
        normalized = normalized.sort_values("timestamp").reset_index(drop=True)

        raw_index = pd.DatetimeIndex(normalized["timestamp"])
        required_high = normalized[["open", "close", "low"]].max(axis=1)
        required_low = normalized[["open", "close", "high"]].min(axis=1)
        invalid_ohlc_count = int(
            (
                (normalized["high"] < required_high)
                | (normalized["low"] > required_low)
            ).sum()
        )
        negative_volume_count = int((normalized["volume"] < 0).sum())
        identity_error_count = int(
            normalized["symbol"].ne(canonical).sum()
            + normalized["timeframe"].ne(timeframe).sum()
        )

    unique_index = raw_index.drop_duplicates().sort_values()
    duplicate_count = int(len(raw_index) - len(unique_index))
    missing = expected.difference(unique_index)
    unexpected = unique_index.difference(expected)
    off_grid_count = audit.count_off_grid_timestamps(
        unique_index,
        audit.TIMEFRAME_DELTAS[timeframe],
    )
    missing_candles = int(len(missing))
    gap_count = audit.count_gap_groups(
        missing,
        audit.TIMEFRAME_DELTAS[timeframe],
    )
    integrity_ok = (
        len(unique_index) == len(expected)
        and missing_candles == 0
        and unexpected.empty
        and duplicate_count == 0
        and off_grid_count == 0
        and invalid_ohlc_count == 0
        and negative_volume_count == 0
        and identity_error_count == 0
    )

    status = {
        "venue": "bybit",
        "market": "spot",
        "symbol": canonical,
        "source_symbol": symbol,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "rows": int(len(normalized)),
        "unique_rows": int(len(unique_index)),
        "expected_rows": int(len(expected)),
        "missing_candles": missing_candles,
        "gap_count": gap_count,
        "duplicate_count": duplicate_count,
        "off_grid_count": off_grid_count,
        "unexpected_timestamp_count": int(len(unexpected)),
        "invalid_ohlc_count": invalid_ohlc_count,
        "negative_volume_count": negative_volume_count,
        "identity_error_count": identity_error_count,
        "first_candle_utc": (
            None if unique_index.empty else unique_index[0].isoformat()
        ),
        "last_candle_utc": (
            None if unique_index.empty else unique_index[-1].isoformat()
        ),
        "integrity_ok": integrity_ok,
        "status": "ready" if integrity_ok else "invalid",
    }
    return normalized, status


def build_collection(
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    clean: bool = False,
    symbols: tuple[str, ...] = audit.SYMBOLS,
    downloader: Callable[..., dict[str, Any]] = robust_download_archive,
) -> dict[str, Any]:
    dates = inclusive_audit_dates(start_date, end_date)
    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    archive_records: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    frames: defaultdict[tuple[str, str], list[pd.DataFrame]] = defaultdict(list)

    for audit_date in dates:
        for symbol in symbols:
            try:
                source = downloader(symbol, audit_date, cache_root)
                raw, schema = audit.read_trade_archive(Path(source["path"]))
                valid, quality = audit.validate_trades(raw, symbol, audit_date)
                archive_ok, failures = validate_archive_quality(quality)
                record = {
                    **source,
                    **schema,
                    **quality,
                    "archive_ok": archive_ok,
                    "failure_reasons": failures,
                }
                archive_records.append(record)
                if not archive_ok:
                    errors.append(
                        {
                            "symbol": symbol,
                            "date": audit_date,
                            "error": "archive_quality_failed: " + ",".join(failures),
                        }
                    )
                    continue

                for timeframe in audit.TIMEFRAME_RULES:
                    candle_frame = audit.trades_to_candles(
                        valid,
                        symbol,
                        timeframe,
                        audit_date,
                    )
                    candle_frame["symbol"] = canonical_symbol(symbol)
                    frames[(symbol, timeframe)].append(candle_frame)
            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "date": audit_date,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    statuses: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in audit.TIMEFRAME_RULES:
            parts = frames.get((symbol, timeframe), [])
            combined = (
                pd.concat(parts, ignore_index=True)
                if parts
                else pd.DataFrame(columns=CANONICAL_COLUMNS)
            )
            normalized, status = evaluate_series(
                combined,
                symbol,
                timeframe,
                start_date,
                end_date,
            )
            statuses.append(status)
            destination = output_root / canonical_symbol(symbol)
            destination.mkdir(parents=True, exist_ok=True)
            normalized.to_parquet(
                destination / f"{timeframe}.parquet",
                index=False,
            )

    status_frame = pd.DataFrame(statuses)
    archive_frame = pd.DataFrame(archive_records)
    expected_archives = len(dates) * len(symbols)
    expected_series = len(symbols) * len(audit.TIMEFRAME_RULES)
    ready_series = int(status_frame["integrity_ok"].sum())
    collector_ok = (
        len(archive_records) == expected_archives
        and all(bool(record["archive_ok"]) for record in archive_records)
        and ready_series == expected_series
        and not errors
    )

    report = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "venue": "bybit",
        "market": "spot",
        "source": "official_public_spot_trade_archive",
        "configuration": {
            "start_date": start_date,
            "end_date": end_date,
            "dates": dates,
            "symbols": list(symbols),
            "timeframes": list(audit.TIMEFRAME_RULES),
        },
        "summary": {
            "expected_archives": expected_archives,
            "completed_archives": len(archive_records),
            "passed_archives": sum(
                bool(record["archive_ok"]) for record in archive_records
            ),
            "expected_series": expected_series,
            "ready_series": ready_series,
            "invalid_series": expected_series - ready_series,
            "errors": len(errors),
            "collector_ok": collector_ok,
        },
        "statuses": statuses,
        "archives": archive_records,
        "errors": errors,
    }
    write_collection_reports(
        report,
        status_frame,
        archive_frame,
        output_root,
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    config = report["configuration"]
    lines = [
        "# Bybit Spot Archive Collection",
        "",
        f"Generated at: {report['generated_at_utc']}",
        f"Range: {config['start_date']} through {config['end_date']} UTC",
        "",
        "## Summary",
        "",
        f"- Collector OK: **{summary['collector_ok']}**",
        f"- Archives passed: {summary['passed_archives']} / {summary['expected_archives']}",
        f"- Candle series ready: {summary['ready_series']} / {summary['expected_series']}",
        f"- Errors: {summary['errors']}",
        "",
        "| Symbol | Timeframe | Rows | Expected | Missing | Gaps | Duplicates | Off-grid | Invalid OHLC | Status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["statuses"]:
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {expected_rows} | {missing_candles} | {gap_count} | {duplicate_count} | {off_grid_count} | {invalid_ohlc_count} | {status} |".format(
                **item
            )
        )
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        for error in report["errors"]:
            lines.append(
                f"- `{error['symbol']} / {error['date']}`: {error['error']}"
            )
    lines.append("")
    return "\n".join(lines)


def write_collection_reports(
    report: dict[str, Any],
    status_frame: pd.DataFrame,
    archive_frame: pd.DataFrame,
    output_root: Path,
) -> None:
    (output_root / "_collection_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output_root / "_collection_report.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    status_frame.to_csv(output_root / "_backfill_status.csv", index=False)
    archive_frame.to_csv(output_root / "_source_manifest.csv", index=False)
    (output_root / "_source_manifest.json").write_text(
        json.dumps(report["archives"], indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect and validate Bybit Spot candles from official daily trade archives."
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_collection(
        start_date=args.start_date,
        end_date=args.end_date,
        output_root=args.output_root,
        cache_root=args.cache_root,
        clean=args.clean,
    )
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["collector_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
