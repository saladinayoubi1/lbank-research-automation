from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import warnings
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

ARCHIVE_BASE_URL = "https://public.bybit.com/spot"
DEFAULT_AUDIT_DATE = "2026-08-01"
DEFAULT_OUTPUT_ROOT = Path("build/bybit_spot_archive_audit")
DEFAULT_CACHE_ROOT = Path("build/bybit_spot_archive_cache")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
TIMEFRAME_RULES = {
    "minute15": "15min",
    "hour1": "1h",
    "hour4": "4h",
}
TIMEFRAME_DELTAS = {
    "minute15": pd.Timedelta(15, unit="min"),
    "hour1": pd.Timedelta(1, unit="h"),
    "hour4": pd.Timedelta(4, unit="h"),
}
REQUIRED_TRADE_COLUMNS = ("timestamp", "side", "size", "price")
OFFICIAL_POSITIONAL_COLUMNS = (
    "trade_id",
    "timestamp",
    "price",
    "size",
    "side",
    "rpi",
)
PARSER_LINE_SAMPLE_LIMIT = 5


class BybitArchiveAuditError(RuntimeError):
    pass


def archive_filename(symbol: str, audit_date: str) -> str:
    pd.Timestamp(audit_date)
    return f"{symbol}_{audit_date}.csv.gz"


def archive_url(symbol: str, audit_date: str) -> str:
    filename = archive_filename(symbol, audit_date)
    return f"{ARCHIVE_BASE_URL}/{symbol}/{filename}"


def download_archive(
    symbol: str,
    audit_date: str,
    cache_root: Path,
    timeout_seconds: float = 120.0,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    cache_root.mkdir(parents=True, exist_ok=True)
    filename = archive_filename(symbol, audit_date)
    path = cache_root / filename
    url = archive_url(symbol, audit_date)

    client = session or requests.Session()
    response = client.get(
        url,
        stream=True,
        timeout=timeout_seconds,
        headers={"User-Agent": "lbank-research-automation/1.0 archive-audit"},
    )
    response.raise_for_status()

    digest = hashlib.sha256()
    size_bytes = 0
    with path.open("wb") as handle:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            handle.write(chunk)
            digest.update(chunk)
            size_bytes += len(chunk)

    if size_bytes == 0:
        raise BybitArchiveAuditError(f"Downloaded empty archive: {url}")
    return {
        "symbol": symbol,
        "audit_date": audit_date,
        "url": url,
        "path": path.as_posix(),
        "size_bytes": size_bytes,
        "sha256": digest.hexdigest(),
        "http_status": int(response.status_code),
    }


def normalize_column_name(value: Any) -> str:
    return "".join(
        character
        for character in str(value).strip().lower()
        if character.isalnum()
    )


def normalize_named_columns(frame: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        "id": "trade_id",
        "tradeid": "trade_id",
        "trdmatchid": "trade_id",
        "execid": "trade_id",
        "timestamp": "timestamp",
        "time": "timestamp",
        "trdtime": "timestamp",
        "symbol": "symbol",
        "side": "side",
        "size": "size",
        "volume": "size",
        "qty": "size",
        "quantity": "size",
        "price": "price",
        "execprice": "price",
        "rpi": "rpi",
        "tickdirection": "tick_direction",
        "grossvalue": "gross_value",
        "homenotional": "home_notional",
        "foreignnotional": "foreign_notional",
    }
    rename = {
        column: aliases[normalized]
        for column in frame.columns
        if (normalized := normalize_column_name(column)) in aliases
    }
    return frame.rename(columns=rename)


def _count_nonempty_archive_lines(path: Path) -> int:
    with gzip.open(path, "rb") as handle:
        return sum(bool(line.strip()) for line in handle)


def _parser_line_samples(messages: list[str]) -> list[int]:
    samples = [
        int(value)
        for message in messages
        for value in re.findall(r"line\s+(\d+)", message, flags=re.IGNORECASE)
    ]
    return list(dict.fromkeys(samples))[:PARSER_LINE_SAMPLE_LIMIT]


def _read_csv_with_malformed_audit(
    path: Path,
    *,
    header: str | int | None = "infer",
    names: tuple[str, ...] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    options: dict[str, Any] = {
        "compression": "gzip",
        "header": header,
        "dtype": "string",
        "low_memory": False,
        "on_bad_lines": "warn",
    }
    if names is not None:
        options["names"] = list(names)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.ParserWarning)
        frame = pd.read_csv(path, **options)
    parser_messages = [
        str(item.message)
        for item in caught
        if issubclass(item.category, pd.errors.ParserWarning)
    ]
    if not parser_messages:
        return frame, {
            "parser_engine": "c",
            "malformed_csv_rows": 0,
            "malformed_csv_line_samples": [],
            "source_rows_parsed": int(len(frame)),
            "source_rows_skipped": 0,
        }

    nonempty_lines = _count_nonempty_archive_lines(path)
    header_rows = 0 if header is None else 1
    expected_rows = max(0, nonempty_lines - header_rows)
    skipped_rows = max(0, expected_rows - len(frame))
    if skipped_rows == 0:
        raise BybitArchiveAuditError(
            "CSV parser rejected rows but the skipped-row count could not be audited"
        )
    return frame, {
        "parser_engine": "c-skip-bad-lines",
        "malformed_csv_rows": int(skipped_rows),
        "malformed_csv_line_samples": _parser_line_samples(parser_messages),
        "source_rows_parsed": int(len(frame)),
        "source_rows_skipped": int(skipped_rows),
    }


def read_trade_archive(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    named_raw, parser_metadata = _read_csv_with_malformed_audit(path)
    named = normalize_named_columns(named_raw)
    used_positional_schema = not set(REQUIRED_TRADE_COLUMNS).issubset(named.columns)
    if used_positional_schema:
        raw, parser_metadata = _read_csv_with_malformed_audit(
            path,
            header=None,
            names=OFFICIAL_POSITIONAL_COLUMNS,
        )
        frame = raw
    else:
        frame = named.copy()

    frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    missing = sorted(set(REQUIRED_TRADE_COLUMNS).difference(frame.columns))
    if missing:
        raise BybitArchiveAuditError(f"Missing trade columns: {missing}")

    timestamp_numeric = pd.to_numeric(frame["timestamp"], errors="coerce")
    finite_timestamp = timestamp_numeric.dropna().abs()
    timestamp_unit = (
        "ms"
        if not finite_timestamp.empty and finite_timestamp.median() >= 1e11
        else "s"
    )
    frame["timestamp"] = pd.to_datetime(
        timestamp_numeric,
        unit=timestamp_unit,
        utc=True,
        errors="coerce",
    )
    if "symbol" in frame.columns:
        frame["symbol"] = (
            frame["symbol"].astype("string").str.strip().str.upper()
        )
    frame["side"] = frame["side"].astype("string").str.strip().str.title()
    frame["size"] = pd.to_numeric(frame["size"], errors="coerce")
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    if "trade_id" in frame.columns:
        frame["trade_id"] = frame["trade_id"].astype("string").str.strip()

    return frame, {
        "used_positional_schema": used_positional_schema,
        "source_columns": [str(column) for column in frame.columns],
        "timestamp_unit": timestamp_unit,
        **parser_metadata,
    }


def validate_trades(
    frame: pd.DataFrame,
    symbol: str,
    audit_date: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    frame = frame.copy()
    if "symbol" not in frame.columns:
        frame["symbol"] = symbol

    day_start = pd.Timestamp(audit_date, tz="UTC")
    day_end = day_start + pd.Timedelta(1, unit="D")

    invalid_numeric = frame[["timestamp", "size", "price"]].isna().any(axis=1)
    invalid_symbol = frame["symbol"].ne(symbol)
    invalid_side = ~frame["side"].isin(["Buy", "Sell"])
    non_positive_price = frame["price"].le(0).fillna(True)
    negative_size = frame["size"].lt(0).fillna(True)
    outside_day = ~frame["timestamp"].ge(day_start) | ~frame["timestamp"].lt(day_end)

    invalid_mask = (
        invalid_numeric
        | invalid_symbol
        | invalid_side
        | non_positive_price
        | negative_size
        | outside_day
    )
    valid = frame.loc[~invalid_mask].copy()
    valid = valid.sort_values("timestamp").reset_index(drop=True)

    duplicate_trade_id_count = 0
    if "trade_id" in valid.columns:
        ids = valid["trade_id"].dropna().astype("string")
        duplicate_trade_id_count = int(len(ids) - ids.nunique())

    return valid, {
        "source_rows": int(len(frame)),
        "valid_trade_rows": int(len(valid)),
        "invalid_numeric_rows": int(invalid_numeric.sum()),
        "invalid_symbol_rows": int(invalid_symbol.sum()),
        "invalid_side_rows": int(invalid_side.sum()),
        "non_positive_price_rows": int(non_positive_price.sum()),
        "negative_size_rows": int(negative_size.sum()),
        "outside_audit_day_rows": int(outside_day.sum()),
        "duplicate_trade_id_count": duplicate_trade_id_count,
    }


def trades_to_candles(
    trades: pd.DataFrame,
    symbol: str,
    timeframe: str,
    audit_date: str,
) -> pd.DataFrame:
    if timeframe not in TIMEFRAME_RULES:
        raise BybitArchiveAuditError(f"Unsupported timeframe: {timeframe}")
    if trades.empty:
        return pd.DataFrame(
            columns=[
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "symbol",
                "timeframe",
            ]
        )

    rule = TIMEFRAME_RULES[timeframe]
    indexed = trades.set_index("timestamp").sort_index()
    candles = indexed.resample(
        rule,
        origin="start_day",
        label="left",
        closed="left",
    ).agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("size", "sum"),
    )
    day_start = pd.Timestamp(audit_date, tz="UTC")
    day_end = day_start + pd.Timedelta(1, unit="D")
    candles = candles.loc[(candles.index >= day_start) & (candles.index < day_end)]
    candles = candles.dropna(subset=["open", "high", "low", "close"]).reset_index()
    candles["symbol"] = symbol.lower()
    candles["timeframe"] = timeframe
    return candles


def count_gap_groups(
    missing: pd.DatetimeIndex,
    step: pd.Timedelta,
) -> int:
    if missing.empty:
        return 0
    if len(missing) == 1:
        return 1
    differences = missing[1:] - missing[:-1]
    return 1 + int((differences != step).sum())


def count_off_grid_timestamps(
    timestamps: pd.DatetimeIndex,
    step: pd.Timedelta,
) -> int:
    step_seconds = int(step.total_seconds())
    return sum(
        int(timestamp.timestamp()) % step_seconds != 0
        or timestamp.microsecond != 0
        for timestamp in timestamps
    )


def audit_candles(
    candles: pd.DataFrame,
    symbol: str,
    timeframe: str,
    audit_date: str,
) -> dict[str, Any]:
    if timeframe not in TIMEFRAME_DELTAS:
        raise BybitArchiveAuditError(f"Unsupported timeframe: {timeframe}")

    step = TIMEFRAME_DELTAS[timeframe]
    day_start = pd.Timestamp(audit_date, tz="UTC")
    day_end = day_start + pd.Timedelta(1, unit="D")
    expected_index = pd.date_range(
        day_start,
        day_end,
        freq=step,
        inclusive="left",
    )

    if candles.empty:
        raw_index = pd.DatetimeIndex([], tz="UTC")
        actual_index = raw_index
        duplicate_count = 0
        off_grid_count = 0
        invalid_ohlc_count = 0
        negative_volume_count = 0
    else:
        raw_index = pd.DatetimeIndex(
            pd.to_datetime(candles["timestamp"], utc=True, errors="raise")
        ).sort_values()
        actual_index = raw_index.drop_duplicates()
        duplicate_count = int(len(raw_index) - len(actual_index))
        off_grid_count = count_off_grid_timestamps(actual_index, step)
        required_high = candles[["open", "close", "low"]].max(axis=1)
        required_low = candles[["open", "close", "high"]].min(axis=1)
        invalid_ohlc_count = int(
            (
                (candles["high"] < required_high)
                | (candles["low"] > required_low)
            ).sum()
        )
        negative_volume_count = int((candles["volume"] < 0).sum())

    missing = expected_index.difference(actual_index)
    unexpected = actual_index.difference(expected_index)
    missing_candles = int(len(missing))
    gap_count = count_gap_groups(missing, step)
    complete_day = (
        len(actual_index) == len(expected_index)
        and missing_candles == 0
        and unexpected.empty
    )
    integrity_ok = (
        complete_day
        and duplicate_count == 0
        and off_grid_count == 0
    )
    passed = (
        integrity_ok
        and invalid_ohlc_count == 0
        and negative_volume_count == 0
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "audit_date": audit_date,
        "rows": int(len(candles)),
        "expected_day_rows": int(len(expected_index)),
        "expected_rows": int(len(expected_index)),
        "missing_candles": missing_candles,
        "gap_count": gap_count,
        "duplicate_count": duplicate_count,
        "off_grid_count": off_grid_count,
        "unexpected_timestamp_count": int(len(unexpected)),
        "first_candle_utc": (
            None if actual_index.empty else actual_index[0].isoformat()
        ),
        "last_candle_utc": (
            None if actual_index.empty else actual_index[-1].isoformat()
        ),
        "complete_utc_day": complete_day,
        "invalid_ohlc_count": invalid_ohlc_count,
        "negative_volume_count": negative_volume_count,
        "integrity_ok": integrity_ok,
        "audit_passed": passed,
    }


def build_archive_audit_report(
    audit_date: str = DEFAULT_AUDIT_DATE,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    downloader: Callable[..., dict[str, Any]] = download_archive,
) -> dict[str, Any]:
    pd.Timestamp(audit_date)
    archives: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for symbol in SYMBOLS:
        try:
            archive = downloader(symbol, audit_date, cache_root)
            frame, schema = read_trade_archive(Path(archive["path"]))
            valid, trade_quality = validate_trades(frame, symbol, audit_date)
            archive.update(schema)
            archive.update(trade_quality)
            archive["archive_passed"] = (
                trade_quality["source_rows"] > 0
                and trade_quality["valid_trade_rows"] > 0
                and sum(
                    trade_quality[key]
                    for key in [
                        "invalid_numeric_rows",
                        "invalid_symbol_rows",
                        "invalid_side_rows",
                        "non_positive_price_rows",
                        "negative_size_rows",
                        "outside_audit_day_rows",
                        "duplicate_trade_id_count",
                    ]
                )
                == 0
            )
            archives.append(archive)
            for timeframe in TIMEFRAME_RULES:
                candles = trades_to_candles(valid, symbol, timeframe, audit_date)
                series.append(
                    audit_candles(candles, symbol, timeframe, audit_date)
                )
        except Exception as exc:
            errors.append(
                {
                    "symbol": symbol,
                    "audit_date": audit_date,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    expected_series = len(SYMBOLS) * len(TIMEFRAME_RULES)
    passed_series = sum(bool(item["audit_passed"]) for item in series)
    passed_archives = sum(bool(item.get("archive_passed")) for item in archives)
    candidate = (
        len(archives) == len(SYMBOLS)
        and passed_archives == len(SYMBOLS)
        and len(series) == expected_series
        and passed_series == expected_series
        and not errors
    )
    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "venue": "bybit",
        "source": "official_public_spot_trade_archive",
        "scope": {
            "audit_date": audit_date,
            "symbols": list(SYMBOLS),
            "timeframes": list(TIMEFRAME_RULES),
            "archive_base_url": ARCHIVE_BASE_URL,
        },
        "summary": {
            "archives_expected": len(SYMBOLS),
            "archives_completed": len(archives),
            "archives_passed": int(passed_archives),
            "series_expected": expected_series,
            "series_completed": len(series),
            "series_passed": int(passed_series),
            "download_or_parse_errors": len(errors),
            "candidate_for_full_spot_archive_backfill": candidate,
        },
        "archives": archives,
        "series": series,
        "errors": errors,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Bybit Official Spot Archive Audit",
        "",
        f"Generated at: {report['generated_at_utc']}",
        f"Audit date: {report['scope']['audit_date']}",
        "",
        "This audit downloads official public Spot trade archives, validates the raw trades, and deterministically aggregates them into UTC candles.",
        "",
        "## Decision",
        "",
        f"- Candidate for full Spot archive backfill: **{summary['candidate_for_full_spot_archive_backfill']}**",
        f"- Archives passed: {summary['archives_passed']} / {summary['archives_expected']}",
        f"- Candle series passed: {summary['series_passed']} / {summary['series_expected']}",
        f"- Download or parse errors: {summary['download_or_parse_errors']}",
        "",
        "| Symbol | Timeframe | Rows | Expected | Missing | Gaps | Duplicates | Off-grid | Invalid OHLC | Passed |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["series"]:
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {expected_day_rows} | {missing_candles} | {gap_count} | {duplicate_count} | {off_grid_count} | {invalid_ohlc_count} | {audit_passed} |".format(
                **item
            )
        )
    if report["errors"]:
        lines.extend(["", "## Errors", ""])
        for error in report["errors"]:
            lines.append(f"- `{error['symbol']}`: {error['error']}")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict[str, Any], output_root: Path, clean: bool) -> None:
    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_bybit_spot_archive_audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output_root / "_bybit_spot_archive_audit.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    pd.DataFrame(report["series"]).to_csv(
        output_root / "_bybit_spot_archive_series.csv",
        index=False,
    )
    pd.DataFrame(report["archives"]).to_csv(
        output_root / "_bybit_spot_archive_sources.csv",
        index=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit one fixed day of official Bybit Spot trade archives and aggregate clean UTC candles."
    )
    parser.add_argument("--audit-date", default=DEFAULT_AUDIT_DATE)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_archive_audit_report(
        audit_date=args.audit_date,
        cache_root=args.cache_root,
    )
    write_report(report, args.output_root, args.clean)
    print(json.dumps(report["summary"], sort_keys=True))
    return (
        0
        if report["summary"]["candidate_for_full_spot_archive_backfill"]
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
