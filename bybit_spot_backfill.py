from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

import bybit_spot_archive_audit as audit
import bybit_spot_archive_collector as collector

DEFAULT_START_DATE = "2022-11-10"
DEFAULT_END_DATE = "2026-07-31"
DEFAULT_STATE_ROOT = Path("build/bybit_backfill_state")
DEFAULT_CACHE_ROOT = Path("build/bybit_backfill_cache")
DEFAULT_MAX_ARCHIVES_PER_RUN = 2
CHECKPOINT_NAME = "_checkpoint.json"
PLAN_NAME = "_archive_plan.json"
REPORT_NAME = "_backfill_report.json"
SOURCE_MANIFEST_NAME = "_source_manifest.json"
STATUS_NAME = "_backfill_status.csv"
RETRYABLE_STATUS_CODES = {403, 408, 425, 429, 500, 502, 503, 504}


class BybitBackfillError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchiveUnit:
    unit_id: str
    kind: str
    start_date: str
    end_date: str
    filenames: dict[str, str]


@dataclass(frozen=True)
class ArchiveInventory:
    symbol: str
    monthly: dict[str, str]
    daily: dict[str, str]


def parse_archive_inventory(symbol: str, html: str) -> ArchiveInventory:
    normalized = symbol.upper()
    filenames = sorted(
        set(
            re.findall(
                rf"{re.escape(normalized)}(?:-\d{{4}}-\d{{2}}|_\d{{4}}-\d{{2}}-\d{{2}})\.csv\.gz",
                html,
            )
        )
    )
    monthly: dict[str, str] = {}
    daily: dict[str, str] = {}
    for filename in filenames:
        monthly_match = re.fullmatch(
            rf"{re.escape(normalized)}-(\d{{4}}-\d{{2}})\.csv\.gz",
            filename,
        )
        if monthly_match:
            monthly[monthly_match.group(1)] = filename
            continue
        daily_match = re.fullmatch(
            rf"{re.escape(normalized)}_(\d{{4}}-\d{{2}}-\d{{2}})\.csv\.gz",
            filename,
        )
        if daily_match:
            daily[daily_match.group(1)] = filename
    return ArchiveInventory(normalized, monthly, daily)


def fetch_archive_inventory(
    symbol: str,
    timeout_seconds: float = 60.0,
    max_attempts: int = 5,
    session: requests.Session | None = None,
) -> ArchiveInventory:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    normalized = symbol.upper()
    url = f"{audit.ARCHIVE_BASE_URL}/{normalized}/"
    client = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(
                url,
                timeout=timeout_seconds,
                allow_redirects=True,
                headers={"Accept": "text/html,*/*"},
            )
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                time.sleep(min(30.0, float(2 ** (attempt - 1))))
                continue
            response.raise_for_status()
            inventory = parse_archive_inventory(normalized, response.text)
            if not inventory.monthly and not inventory.daily:
                raise BybitBackfillError(
                    f"No archive filenames discovered for {normalized}"
                )
            return inventory
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(min(30.0, float(2 ** (attempt - 1))))
    assert last_error is not None
    raise last_error


def month_period_bounds(period: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Period(period, freq="M").start_time.normalize()
    end = pd.Period(period, freq="M").end_time.normalize()
    return start, end


def build_archive_plan(
    inventories: dict[str, ArchiveInventory],
    start_date: str,
    end_date: str,
    symbols: tuple[str, ...] = audit.SYMBOLS,
) -> dict[str, Any]:
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if end < start:
        raise BybitBackfillError("end_date cannot be before start_date")
    normalized_symbols = tuple(symbol.upper() for symbol in symbols)
    missing_inventories = sorted(set(normalized_symbols).difference(inventories))
    if missing_inventories:
        raise BybitBackfillError(
            f"Missing inventories for symbols: {missing_inventories}"
        )

    units: list[ArchiveUnit] = []
    unavailable_dates: list[str] = []
    cursor = start
    while cursor <= end:
        period = cursor.strftime("%Y-%m")
        month_start, month_end = month_period_bounds(period)
        scoped_start = max(cursor, month_start)
        scoped_end = min(end, month_end)
        is_full_month = scoped_start == month_start and scoped_end == month_end
        monthly_available = is_full_month and all(
            period in inventories[symbol].monthly for symbol in normalized_symbols
        )
        if monthly_available:
            units.append(
                ArchiveUnit(
                    unit_id=f"monthly:{period}",
                    kind="monthly",
                    start_date=month_start.strftime("%Y-%m-%d"),
                    end_date=month_end.strftime("%Y-%m-%d"),
                    filenames={
                        symbol: inventories[symbol].monthly[period]
                        for symbol in normalized_symbols
                    },
                )
            )
        else:
            for day in pd.date_range(scoped_start, scoped_end, freq="1D"):
                date = day.strftime("%Y-%m-%d")
                if all(
                    date in inventories[symbol].daily
                    for symbol in normalized_symbols
                ):
                    units.append(
                        ArchiveUnit(
                            unit_id=f"daily:{date}",
                            kind="daily",
                            start_date=date,
                            end_date=date,
                            filenames={
                                symbol: inventories[symbol].daily[date]
                                for symbol in normalized_symbols
                            },
                        )
                    )
                else:
                    unavailable_dates.append(date)
        cursor = month_end + pd.Timedelta(1, unit="D")

    units.sort(key=lambda unit: (unit.start_date, unit.kind, unit.unit_id))
    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "symbols": list(normalized_symbols),
        "total_units": len(units),
        "monthly_units": sum(unit.kind == "monthly" for unit in units),
        "daily_units": sum(unit.kind == "daily" for unit in units),
        "total_archives": len(units) * len(normalized_symbols),
        "unavailable_dates": unavailable_dates,
        "units": [asdict(unit) for unit in units],
    }


def load_checkpoint(state_root: Path) -> dict[str, Any]:
    path = state_root / CHECKPOINT_NAME
    if not path.exists():
        return {
            "schema_version": 1,
            "completed_units": [],
            "failed_units": [],
            "runs": [],
        }
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    if checkpoint.get("schema_version") != 1:
        raise BybitBackfillError("Unsupported checkpoint schema_version")
    return checkpoint


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def archive_url(symbol: str, filename: str) -> str:
    return f"{audit.ARCHIVE_BASE_URL}/{symbol.upper()}/{filename}"


def download_archive_file(
    symbol: str,
    filename: str,
    cache_root: Path,
    timeout_seconds: float = 180.0,
    max_attempts: int = 5,
    session: requests.Session | None = None,
) -> dict[str, Any]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    cache_root.mkdir(parents=True, exist_ok=True)
    path = cache_root / filename
    url = archive_url(symbol, filename)
    if path.exists() and path.stat().st_size > 0:
        content = path.read_bytes()
        return {
            "symbol": symbol.upper(),
            "filename": filename,
            "url": url,
            "path": path.as_posix(),
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "http_status": 200,
            "download_attempts": 0,
            "loaded_from_cache": True,
        }

    client = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.get(
                url,
                timeout=timeout_seconds,
                allow_redirects=True,
                headers={
                    "Accept": "application/gzip,application/octet-stream,*/*",
                    "Referer": f"{audit.ARCHIVE_BASE_URL}/{symbol.upper()}/",
                },
            )
            if response.status_code in RETRYABLE_STATUS_CODES and attempt < max_attempts:
                time.sleep(min(30.0, float(2 ** (attempt - 1))))
                continue
            response.raise_for_status()
            content = response.content
            if not content:
                raise BybitBackfillError(f"Downloaded empty archive: {url}")
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(content)
            temporary.replace(path)
            return {
                "symbol": symbol.upper(),
                "filename": filename,
                "url": url,
                "path": path.as_posix(),
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "http_status": int(response.status_code),
                "download_attempts": attempt,
                "loaded_from_cache": False,
            }
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(min(30.0, float(2 ** (attempt - 1))))
    assert last_error is not None
    raise last_error


def validate_trade_range(
    frame: pd.DataFrame,
    symbol: str,
    start_date: str,
    end_date: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    frame = frame.copy()
    if "symbol" not in frame.columns:
        frame["symbol"] = symbol.upper()
    start = pd.Timestamp(start_date, tz="UTC")
    end_exclusive = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(1, unit="D")

    invalid_numeric = frame[["timestamp", "size", "price"]].isna().any(axis=1)
    invalid_symbol = frame["symbol"].ne(symbol.upper())
    invalid_side = ~frame["side"].isin(["Buy", "Sell"])
    non_positive_price = frame["price"].le(0).fillna(True)
    negative_size = frame["size"].lt(0).fillna(True)
    outside_range = ~frame["timestamp"].ge(start) | ~frame["timestamp"].lt(
        end_exclusive
    )
    invalid_mask = (
        invalid_numeric
        | invalid_symbol
        | invalid_side
        | non_positive_price
        | negative_size
        | outside_range
    )
    valid = frame.loc[~invalid_mask].copy()
    valid = valid.sort_values("timestamp").reset_index(drop=True)

    duplicate_trade_id_count = 0
    if "trade_id" in valid.columns:
        ids = valid["trade_id"].dropna().astype("string")
        duplicate_trade_id_count = int(len(ids) - ids.nunique())
    quality = {
        "source_rows": int(len(frame)),
        "valid_trade_rows": int(len(valid)),
        "invalid_numeric_rows": int(invalid_numeric.sum()),
        "invalid_symbol_rows": int(invalid_symbol.sum()),
        "invalid_side_rows": int(invalid_side.sum()),
        "non_positive_price_rows": int(non_positive_price.sum()),
        "negative_size_rows": int(negative_size.sum()),
        "outside_range_rows": int(outside_range.sum()),
        "duplicate_trade_id_count": duplicate_trade_id_count,
    }
    failure_fields = [
        "invalid_numeric_rows",
        "invalid_symbol_rows",
        "invalid_side_rows",
        "non_positive_price_rows",
        "negative_size_rows",
        "outside_range_rows",
        "duplicate_trade_id_count",
    ]
    if quality["valid_trade_rows"] == 0 or any(
        quality[field] > 0 for field in failure_fields
    ):
        raise BybitBackfillError(
            f"Raw trade validation failed for {symbol} {start_date}..{end_date}: {quality}"
        )
    return valid, quality


def trades_to_range_candles(
    trades: pd.DataFrame,
    symbol: str,
    timeframe: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if timeframe not in audit.TIMEFRAME_RULES:
        raise BybitBackfillError(f"Unsupported timeframe: {timeframe}")
    indexed = trades.set_index("timestamp").sort_index()
    candles = indexed.resample(
        audit.TIMEFRAME_RULES[timeframe],
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
    start = pd.Timestamp(start_date, tz="UTC")
    end_exclusive = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(1, unit="D")
    candles = candles.loc[(candles.index >= start) & (candles.index < end_exclusive)]
    candles = candles.dropna(subset=["open", "high", "low", "close"]).reset_index()
    candles["symbol"] = collector.canonical_symbol(symbol)
    candles["timeframe"] = timeframe
    normalized, status = collector.evaluate_series(
        candles,
        symbol,
        timeframe,
        start_date,
        end_date,
    )
    if not status["integrity_ok"]:
        raise BybitBackfillError(
            f"Candle integrity failed for {symbol} {timeframe} "
            f"{start_date}..{end_date}: {status}"
        )
    return normalized


def load_existing_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=collector.CANONICAL_COLUMNS)
    frame = pd.read_parquet(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    return frame.loc[:, collector.CANONICAL_COLUMNS].sort_values("timestamp").reset_index(drop=True)


def merge_without_overlap(existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if existing.empty:
        return incoming.copy().reset_index(drop=True)
    existing_index = pd.DatetimeIndex(existing["timestamp"])
    incoming_index = pd.DatetimeIndex(incoming["timestamp"])
    overlap = existing_index.intersection(incoming_index)
    if not overlap.empty:
        raise BybitBackfillError(
            f"Incoming archive overlaps {len(overlap)} existing candle timestamp(s)"
        )
    return (
        pd.concat([existing, incoming], ignore_index=True)
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def stage_unit(
    unit: ArchiveUnit,
    state_root: Path,
    cache_root: Path,
    symbols: tuple[str, ...],
    downloader: Callable[..., dict[str, Any]],
) -> tuple[dict[tuple[str, str], pd.DataFrame], list[dict[str, Any]]]:
    staged: dict[tuple[str, str], pd.DataFrame] = {}
    sources: list[dict[str, Any]] = []
    for symbol in symbols:
        source = downloader(symbol, unit.filenames[symbol], cache_root)
        raw, schema = audit.read_trade_archive(Path(source["path"]))
        valid, quality = validate_trade_range(
            raw,
            symbol,
            unit.start_date,
            unit.end_date,
        )
        sources.append(
            {
                **source,
                **schema,
                **quality,
                "unit_id": unit.unit_id,
                "unit_kind": unit.kind,
                "start_date": unit.start_date,
                "end_date": unit.end_date,
            }
        )
        for timeframe in audit.TIMEFRAME_RULES:
            incoming = trades_to_range_candles(
                valid,
                symbol,
                timeframe,
                unit.start_date,
                unit.end_date,
            )
            path = (
                state_root
                / "bybit_market"
                / collector.canonical_symbol(symbol)
                / f"{timeframe}.parquet"
            )
            existing = load_existing_frame(path)
            staged[(symbol, timeframe)] = merge_without_overlap(existing, incoming)
    return staged, sources


def commit_staged_frames(
    staged: dict[tuple[str, str], pd.DataFrame],
    state_root: Path,
) -> None:
    temporary_paths: list[tuple[Path, Path]] = []
    for (symbol, timeframe), frame in staged.items():
        path = (
            state_root
            / "bybit_market"
            / collector.canonical_symbol(symbol)
            / f"{timeframe}.parquet"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        frame.to_parquet(temporary, index=False)
        temporary_paths.append((temporary, path))
    for temporary, path in temporary_paths:
        temporary.replace(path)


def compute_current_status(
    state_root: Path,
    completed_units: list[dict[str, Any]],
    symbols: tuple[str, ...],
) -> list[dict[str, Any]]:
    if not completed_units:
        return []
    start_date = min(unit["start_date"] for unit in completed_units)
    end_date = max(unit["end_date"] for unit in completed_units)
    statuses: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in audit.TIMEFRAME_RULES:
            path = (
                state_root
                / "bybit_market"
                / collector.canonical_symbol(symbol)
                / f"{timeframe}.parquet"
            )
            frame = load_existing_frame(path)
            _, status = collector.evaluate_series(
                frame,
                symbol,
                timeframe,
                start_date,
                end_date,
            )
            statuses.append(status)
    return statuses


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Bybit Spot Resumable Backfill",
        "",
        f"Generated at: {report['generated_at_utc']}",
        "",
        "## Progress",
        "",
        f"- Plan units: {summary['plan_units']}",
        f"- Completed units: {summary['completed_units']}",
        f"- Remaining units: {summary['remaining_units']}",
        f"- Units completed this run: {summary['units_completed_this_run']}",
        f"- Archives downloaded this run: {summary['archives_completed_this_run']}",
        f"- Backfill complete: **{summary['backfill_complete']}**",
        f"- Current dataset integrity OK: **{summary['current_dataset_integrity_ok']}**",
        "",
        "## Current series",
        "",
        "| Symbol | Timeframe | Rows | Expected | Missing | Duplicates | Off-grid | Status |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for status in report["statuses"]:
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {expected_rows} | "
            "{missing_candles} | {duplicate_count} | {off_grid_count} | {status} |".format(
                **status
            )
        )
    if report["run_failures"]:
        lines.extend(["", "## Run failures", ""])
        for failure in report["run_failures"]:
            lines.append(f"- `{failure['unit_id']}`: {failure['error']}")
    lines.append("")
    return "\n".join(lines)


def run_backfill(
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    state_root: Path = DEFAULT_STATE_ROOT,
    cache_root: Path = DEFAULT_CACHE_ROOT,
    max_archives_per_run: int = DEFAULT_MAX_ARCHIVES_PER_RUN,
    symbols: tuple[str, ...] = audit.SYMBOLS,
    inventory_fetcher: Callable[[str], ArchiveInventory] = fetch_archive_inventory,
    downloader: Callable[..., dict[str, Any]] = download_archive_file,
    clean: bool = False,
) -> dict[str, Any]:
    normalized_symbols = tuple(symbol.upper() for symbol in symbols)
    if max_archives_per_run < len(normalized_symbols):
        raise BybitBackfillError(
            f"max_archives_per_run must be at least {len(normalized_symbols)}"
        )
    if clean and state_root.exists():
        shutil.rmtree(state_root)
    state_root.mkdir(parents=True, exist_ok=True)

    inventories = {
        symbol: inventory_fetcher(symbol) for symbol in normalized_symbols
    }
    plan = build_archive_plan(
        inventories,
        start_date,
        end_date,
        symbols=normalized_symbols,
    )
    write_json(state_root / PLAN_NAME, plan)
    if plan["unavailable_dates"]:
        raise BybitBackfillError(
            f"Archive plan has unavailable dates: {plan['unavailable_dates'][:10]}"
        )

    checkpoint = load_checkpoint(state_root)
    completed_ids = {
        unit["unit_id"] for unit in checkpoint.get("completed_units", [])
    }
    units = [ArchiveUnit(**unit) for unit in plan["units"]]
    pending = [unit for unit in units if unit.unit_id not in completed_ids]
    max_units = max_archives_per_run // len(normalized_symbols)
    selected = pending[:max_units]

    source_manifest_path = state_root / SOURCE_MANIFEST_NAME
    source_manifest = (
        json.loads(source_manifest_path.read_text(encoding="utf-8"))
        if source_manifest_path.exists()
        else []
    )
    completed_this_run: list[dict[str, Any]] = []
    failures_this_run: list[dict[str, Any]] = []
    sources_this_run: list[dict[str, Any]] = []

    for unit in selected:
        try:
            staged, sources = stage_unit(
                unit,
                state_root,
                cache_root,
                normalized_symbols,
                downloader,
            )
            commit_staged_frames(staged, state_root)
            completed = asdict(unit)
            completed["completed_at_utc"] = pd.Timestamp.now(tz="UTC").isoformat()
            checkpoint["completed_units"].append(completed)
            completed_ids.add(unit.unit_id)
            completed_this_run.append(completed)
            sources_this_run.extend(sources)
            source_manifest.extend(sources)
            write_json(state_root / CHECKPOINT_NAME, checkpoint)
            write_json(source_manifest_path, source_manifest)
        except Exception as exc:
            failure = {
                "unit_id": unit.unit_id,
                "failed_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
                "error": f"{type(exc).__name__}: {exc}",
            }
            checkpoint["failed_units"].append(failure)
            failures_this_run.append(failure)
            write_json(state_root / CHECKPOINT_NAME, checkpoint)
            break

    statuses = compute_current_status(
        state_root,
        checkpoint.get("completed_units", []),
        normalized_symbols,
    )
    status_frame = pd.DataFrame(statuses)
    if not status_frame.empty:
        status_frame.to_csv(state_root / STATUS_NAME, index=False)
    remaining = len(units) - len(completed_ids)
    current_integrity_ok = bool(statuses) and all(
        bool(status["integrity_ok"]) for status in statuses
    )
    backfill_complete = remaining == 0 and not failures_this_run
    run_record = {
        "started_or_completed_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "max_archives_per_run": max_archives_per_run,
        "selected_unit_ids": [unit.unit_id for unit in selected],
        "completed_unit_ids": [unit["unit_id"] for unit in completed_this_run],
        "failed_unit_ids": [failure["unit_id"] for failure in failures_this_run],
    }
    checkpoint["runs"].append(run_record)
    write_json(state_root / CHECKPOINT_NAME, checkpoint)

    report = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "configuration": {
            "start_date": start_date,
            "end_date": end_date,
            "symbols": list(normalized_symbols),
            "max_archives_per_run": max_archives_per_run,
        },
        "summary": {
            "plan_units": len(units),
            "plan_archives": plan["total_archives"],
            "completed_units": len(completed_ids),
            "remaining_units": remaining,
            "units_completed_this_run": len(completed_this_run),
            "archives_completed_this_run": len(sources_this_run),
            "run_failures": len(failures_this_run),
            "backfill_complete": backfill_complete,
            "current_dataset_integrity_ok": current_integrity_ok,
        },
        "completed_this_run": completed_this_run,
        "sources_this_run": sources_this_run,
        "run_failures": failures_this_run,
        "statuses": statuses,
    }
    write_json(state_root / REPORT_NAME, report)
    (state_root / "_backfill_report.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a bounded resumable Bybit Spot archive backfill chunk."
    )
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument(
        "--max-archives-per-run",
        type=int,
        default=DEFAULT_MAX_ARCHIVES_PER_RUN,
    )
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_backfill(
        start_date=args.start_date,
        end_date=args.end_date,
        state_root=args.state_root,
        cache_root=args.cache_root,
        max_archives_per_run=args.max_archives_per_run,
        clean=args.clean,
    )
    print(json.dumps(report["summary"], sort_keys=True))
    return 0 if not report["run_failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
