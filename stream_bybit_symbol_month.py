from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

import bybit_spot_archive_audit as audit
import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill

CHUNK_SIZE = 250_000


class StreamMonthError(RuntimeError):
    pass


def _reader(path: Path) -> tuple[Any, dict[str, Any]]:
    first_row = audit._first_nonempty_archive_row(path)
    canonical_header = audit._canonical_header_columns(first_row)
    positional = not set(audit.REQUIRED_TRADE_COLUMNS).issubset(canonical_header)
    options: dict[str, Any] = {
        "compression": "gzip",
        "dtype": "string",
        "low_memory": False,
        "chunksize": CHUNK_SIZE,
        "on_bad_lines": "error",
    }
    if positional:
        options.update(header=None, names=list(audit.OFFICIAL_POSITIONAL_COLUMNS))
        source_header: list[str] = []
        extended = 0
    else:
        names = audit._extended_named_header(first_row)
        options.update(header=None, names=list(names), skiprows=1)
        source_header = first_row
        extended = len(names) - len(first_row)
    return pd.read_csv(path, **options), {
        "used_positional_schema": positional,
        "source_header_columns": source_header,
        "extended_named_schema_columns": extended,
    }


def _normalize_chunk(
    frame: pd.DataFrame,
    *,
    positional: bool,
    symbol: str,
    start: pd.Timestamp,
    end_exclusive: pd.Timestamp,
    timestamp_unit: str | None,
) -> tuple[pd.DataFrame, str, dict[str, int]]:
    if not positional:
        frame = audit.normalize_named_columns(frame)
    frame = frame.loc[:, ~frame.columns.duplicated()].copy()
    missing = sorted(set(audit.REQUIRED_TRADE_COLUMNS).difference(frame.columns))
    if missing:
        raise StreamMonthError(f"Missing trade columns: {missing}")

    timestamp_numeric = pd.to_numeric(frame["timestamp"], errors="coerce")
    if timestamp_unit is None:
        finite = timestamp_numeric.dropna().abs()
        timestamp_unit = (
            "ms" if not finite.empty and finite.median() >= 1e11 else "s"
        )
    frame["timestamp"] = pd.to_datetime(
        timestamp_numeric,
        unit=timestamp_unit,
        utc=True,
        errors="coerce",
    )
    if "symbol" not in frame.columns:
        frame["symbol"] = symbol
    else:
        frame["symbol"] = frame["symbol"].astype("string").str.strip().str.upper()
    frame["side"] = frame["side"].astype("string").str.strip().str.title()
    frame["size"] = pd.to_numeric(frame["size"], errors="coerce")
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    if "trade_id" in frame.columns:
        frame["trade_id"] = frame["trade_id"].astype("string").str.strip()

    invalid_numeric = frame[["timestamp", "size", "price"]].isna().any(axis=1)
    invalid_symbol = frame["symbol"].ne(symbol)
    invalid_side = ~frame["side"].isin(["Buy", "Sell"])
    non_positive_price = frame["price"].le(0).fillna(True)
    negative_size = frame["size"].lt(0).fillna(True)
    outside_range = ~frame["timestamp"].ge(start) | ~frame["timestamp"].lt(
        end_exclusive
    )
    invalid = (
        invalid_numeric
        | invalid_symbol
        | invalid_side
        | non_positive_price
        | negative_size
        | outside_range
    )
    quality = {
        "source_rows": int(len(frame)),
        "valid_trade_rows": int((~invalid).sum()),
        "invalid_numeric_rows": int(invalid_numeric.sum()),
        "invalid_symbol_rows": int(invalid_symbol.sum()),
        "invalid_side_rows": int(invalid_side.sum()),
        "non_positive_price_rows": int(non_positive_price.sum()),
        "negative_size_rows": int(negative_size.sum()),
        "outside_range_rows": int(outside_range.sum()),
    }
    failure_fields = [
        "invalid_numeric_rows",
        "invalid_symbol_rows",
        "invalid_side_rows",
        "non_positive_price_rows",
        "negative_size_rows",
        "outside_range_rows",
    ]
    if any(quality[name] for name in failure_fields):
        raise StreamMonthError(f"Trade validation failed: {quality}")
    return frame.loc[~invalid].copy(), timestamp_unit, quality


def _merge_candles(current: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    if current is None:
        return incoming
    combined = pd.concat([current, incoming])
    return combined.groupby(level=0, sort=True).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )


def _resample_from_15m(frame: pd.DataFrame, rule: str) -> pd.DataFrame:
    indexed = frame.set_index("timestamp").sort_index()
    return (
        indexed.resample(rule, origin="start_day", label="left", closed="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .dropna(subset=["open", "high", "low", "close"])
        .reset_index()
    )


def build_symbol_month(
    symbol: str,
    start_date: str,
    end_date: str,
    output_root: Path,
    cache_root: Path,
) -> dict[str, Any]:
    symbol = symbol.upper()
    start = pd.Timestamp(start_date, tz="UTC")
    end_exclusive = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(1, unit="D")
    period = pd.Period(pd.Timestamp(start_date), freq="M")
    if start_date != period.start_time.strftime("%Y-%m-%d") or end_date != period.end_time.strftime("%Y-%m-%d"):
        raise StreamMonthError("Streaming builder requires one complete calendar month")

    inventory = backfill.fetch_archive_inventory(symbol)
    period_key = period.strftime("%Y-%m")
    filename = inventory.monthly.get(period_key)
    if not filename:
        raise StreamMonthError(f"Monthly archive unavailable for {symbol} {period_key}")
    source = backfill.download_archive_file(symbol, filename, cache_root)
    path = Path(source["path"])
    reader, schema = _reader(path)

    aggregate_15m: pd.DataFrame | None = None
    timestamp_unit: str | None = None
    source_rows = 0
    valid_rows = 0
    duplicate_trade_ids = 0
    seen_trade_hashes: set[int] = set()
    source_columns: list[str] = []

    for raw in reader:
        normalized, timestamp_unit, quality = _normalize_chunk(
            raw,
            positional=bool(schema["used_positional_schema"]),
            symbol=symbol,
            start=start,
            end_exclusive=end_exclusive,
            timestamp_unit=timestamp_unit,
        )
        source_rows += quality["source_rows"]
        valid_rows += quality["valid_trade_rows"]
        source_columns = [str(column) for column in normalized.columns]
        if "trade_id" in normalized.columns:
            ids = normalized["trade_id"].dropna()
            hashes = pd.util.hash_pandas_object(ids, index=False).astype("uint64")
            for value in hashes:
                integer = int(value)
                if integer in seen_trade_hashes:
                    duplicate_trade_ids += 1
                else:
                    seen_trade_hashes.add(integer)
            if duplicate_trade_ids:
                raise StreamMonthError(
                    f"Duplicate trade IDs detected: {duplicate_trade_ids}"
                )

        indexed = normalized.set_index("timestamp").sort_index()
        candles = indexed.resample(
            "15min", origin="start_day", label="left", closed="left"
        ).agg(
            open=("price", "first"),
            high=("price", "max"),
            low=("price", "min"),
            close=("price", "last"),
            volume=("size", "sum"),
        )
        candles = candles.dropna(subset=["open", "high", "low", "close"])
        aggregate_15m = _merge_candles(aggregate_15m, candles)
        del raw, normalized, indexed, candles

    if aggregate_15m is None or aggregate_15m.empty:
        raise StreamMonthError("Archive produced no candles")

    canonical = collector.canonical_symbol(symbol)
    frames: dict[str, pd.DataFrame] = {}
    minute15 = aggregate_15m.reset_index()
    minute15["symbol"] = canonical
    minute15["timeframe"] = "minute15"
    frames["minute15"] = minute15
    frames["hour1"] = _resample_from_15m(minute15, "1h")
    frames["hour4"] = _resample_from_15m(minute15, "4h")

    statuses: list[dict[str, Any]] = []
    destination = output_root / "bybit_market" / canonical
    destination.mkdir(parents=True, exist_ok=True)
    for timeframe, frame in frames.items():
        frame["symbol"] = canonical
        frame["timeframe"] = timeframe
        normalized, status = collector.evaluate_series(
            frame,
            symbol,
            timeframe,
            start_date,
            end_date,
        )
        if not status["integrity_ok"] or status["status"] != "ready":
            raise StreamMonthError(f"Integrity failed for {timeframe}: {status}")
        normalized.to_parquet(destination / f"{timeframe}.parquet", index=False)
        statuses.append(status)

    unit = {
        "unit_id": f"monthly:{period_key}",
        "kind": "monthly",
        "start_date": start_date,
        "end_date": end_date,
        "filenames": {symbol: filename},
        "completed_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
    }
    source_record = {
        **source,
        **schema,
        "source_columns": source_columns,
        "timestamp_unit": timestamp_unit,
        "parser_engine": "c-chunked",
        "malformed_csv_rows": 0,
        "malformed_csv_line_samples": [],
        "source_rows_parsed": source_rows,
        "source_rows_skipped": 0,
        "source_rows": source_rows,
        "valid_trade_rows": valid_rows,
        "invalid_numeric_rows": 0,
        "invalid_symbol_rows": 0,
        "invalid_side_rows": 0,
        "non_positive_price_rows": 0,
        "negative_size_rows": 0,
        "outside_range_rows": 0,
        "duplicate_trade_id_count": duplicate_trade_ids,
        "unit_id": unit["unit_id"],
        "unit_kind": "monthly",
        "start_date": start_date,
        "end_date": end_date,
    }
    checkpoint = {
        "schema_version": 1,
        "completed_units": [unit],
        "failed_units": [],
        "runs": [{
            "started_or_completed_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "max_archives_per_run": 1,
            "selected_unit_ids": [unit["unit_id"]],
            "completed_unit_ids": [unit["unit_id"]],
            "failed_unit_ids": [],
        }],
    }
    report = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "configuration": {
            "start_date": start_date,
            "end_date": end_date,
            "symbols": [symbol],
            "max_archives_per_run": 1,
        },
        "summary": {
            "plan_units": 1,
            "plan_archives": 1,
            "completed_units": 1,
            "remaining_units": 0,
            "units_completed_this_run": 1,
            "archives_completed_this_run": 1,
            "run_failures": 0,
            "backfill_complete": True,
            "current_dataset_integrity_ok": True,
        },
        "completed_this_run": [unit],
        "sources_this_run": [source_record],
        "run_failures": [],
        "statuses": statuses,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    backfill.write_json(output_root / "_checkpoint.json", checkpoint)
    backfill.write_json(output_root / "_source_manifest.json", [source_record])
    backfill.write_json(output_root / "_backfill_report.json", report)
    pd.DataFrame([source_record]).to_csv(output_root / "_source_manifest.csv", index=False)
    pd.DataFrame(statuses).to_csv(output_root / "_backfill_status.csv", index=False)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_symbol_month(
        args.symbol,
        args.start_date,
        args.end_date,
        args.output_root,
        args.cache_root,
    )
    print(json.dumps(report["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
