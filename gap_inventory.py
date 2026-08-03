from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import pandas as pd

import gap_probe
from gap_repair import missing_timestamp_set
from main import SYMBOLS, TIMEFRAMES, get_klines

DEFAULT_INPUT_ROOT = Path("data/market")
DEFAULT_OUTPUT_ROOT = Path("build/gap_probe")


class CachedKlineFetcher:
    def __init__(self, fetcher: Callable[[str, str, int], list[list[Any]]] = get_klines):
        self.fetcher = fetcher
        self.responses: list[dict[str, Any]] = []

    def __call__(self, symbol: str, timeframe: str, start: int) -> list[list[Any]]:
        rows = self.fetcher(symbol, timeframe, start)
        self.responses.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "requested_time_utc": pd.to_datetime(start, unit="s", utc=True).isoformat(),
            "rows": rows,
        })
        return rows


def normalize_missing(values: set[pd.Timestamp]) -> set[pd.Timestamp]:
    return {gap_probe.utc_timestamp(value) for value in values}


def diagnose_raw_row(
    row: list[Any],
    missing: set[pd.Timestamp],
) -> dict[str, Any] | None:
    if not isinstance(row, (list, tuple)) or not row:
        return None

    raw_timestamp = pd.to_numeric(pd.Series([row[0]]), errors="coerce").iloc[0]
    if pd.isna(raw_timestamp):
        return None
    timestamp = pd.to_datetime(raw_timestamp, unit="s", utc=True, errors="coerce")
    if pd.isna(timestamp) or timestamp not in missing:
        return None

    reasons: list[str] = []
    values = list(row[:6])
    if len(values) < 6:
        reasons.append("short_row")
        values.extend([None] * (6 - len(values)))

    numeric = pd.to_numeric(pd.Series(values[1:6]), errors="coerce")
    if numeric.isna().any():
        reasons.append("non_numeric_or_missing_ohlcv")
    else:
        open_price, high, low, close, volume = numeric.tolist()
        if high < max(open_price, close, low):
            reasons.append("high_below_ohlc_max")
        if low > min(open_price, close, high):
            reasons.append("low_above_ohlc_min")
        if volume < 0:
            reasons.append("negative_volume")

    return {
        "timestamp_utc": timestamp.isoformat(),
        "open": values[1],
        "high": values[2],
        "low": values[3],
        "close": values[4],
        "volume": values[5],
        "validation_reasons": reasons,
        "canonical_valid": not reasons,
    }


def collect_missing_sets(
    input_root: Path,
    frame_reader: Callable[[Path], pd.DataFrame] = pd.read_parquet,
) -> tuple[dict[tuple[str, str], set[pd.Timestamp]], int]:
    missing_by_series: dict[tuple[str, str], set[pd.Timestamp]] = {}
    total_missing = 0
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            path = input_root / symbol / f"{timeframe}.parquet"
            if not path.exists():
                continue
            frame = frame_reader(path)
            missing = normalize_missing(
                missing_timestamp_set(frame["timestamp"], timeframe)
            )
            if missing:
                missing_by_series[(symbol, timeframe)] = missing
                total_missing += len(missing)
    return missing_by_series, total_missing


def build_inventory(
    responses: list[dict[str, Any]],
    missing_by_series: dict[tuple[str, str], set[pd.Timestamp]],
    total_source_missing: int,
) -> dict[str, Any]:
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    observed_requests: defaultdict[tuple[Any, ...], set[str]] = defaultdict(set)

    for response in responses:
        series = (response["symbol"], response["timeframe"])
        missing = missing_by_series.get(series, set())
        for raw_row in response["rows"]:
            diagnosed = diagnose_raw_row(raw_row, missing)
            if diagnosed is None:
                continue
            key = (
                response["symbol"],
                response["timeframe"],
                diagnosed["timestamp_utc"],
                str(diagnosed["open"]),
                str(diagnosed["high"]),
                str(diagnosed["low"]),
                str(diagnosed["close"]),
                str(diagnosed["volume"]),
            )
            unique[key] = {
                "symbol": response["symbol"],
                "timeframe": response["timeframe"],
                **diagnosed,
            }
            observed_requests[key].add(response["requested_time_utc"])

    rows = []
    for key, row in unique.items():
        rows.append({
            **row,
            "observed_request_times_utc": sorted(observed_requests[key]),
            "observation_count": len(observed_requests[key]),
        })
    rows.sort(key=lambda row: (row["symbol"], row["timeframe"], row["timestamp_utc"]))

    observed_timestamps = {
        (row["symbol"], row["timeframe"], row["timestamp_utc"])
        for row in rows
    }
    invalid_timestamps = {
        (row["symbol"], row["timeframe"], row["timestamp_utc"])
        for row in rows
        if not row["canonical_valid"]
    }
    valid_timestamps = observed_timestamps - invalid_timestamps
    coverage = (
        len(observed_timestamps) / total_source_missing * 100
        if total_source_missing else 0.0
    )

    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "summary": {
            "cached_api_responses": len(responses),
            "total_source_missing_candles": total_source_missing,
            "unique_missing_timestamps_observed_raw": len(observed_timestamps),
            "unique_missing_timestamps_invalid": len(invalid_timestamps),
            "unique_missing_timestamps_valid": len(valid_timestamps),
            "raw_missing_coverage_percent": coverage,
            "unique_raw_rows": len(rows),
        },
        "rows": rows,
    }


def render_markdown(inventory: dict[str, Any]) -> str:
    summary = inventory["summary"]
    lines = [
        "# LBank Cached Gap Quality Inventory",
        "",
        f"Generated at: {inventory['generated_at_utc']}",
        "",
        "This inventory reuses the exact API responses already fetched by the gap probe. "
        "It makes no additional public requests and never modifies canonical data.",
        "",
        "## Summary",
        "",
        f"- Cached API responses: {summary['cached_api_responses']}",
        f"- Total source missing candles: {summary['total_source_missing_candles']}",
        f"- Missing timestamps observed raw: {summary['unique_missing_timestamps_observed_raw']}",
        f"- Observed timestamps invalid: {summary['unique_missing_timestamps_invalid']}",
        f"- Observed timestamps valid: {summary['unique_missing_timestamps_valid']}",
        f"- Raw missing coverage: {summary['raw_missing_coverage_percent']:.2f}%",
        f"- Unique raw rows: {summary['unique_raw_rows']}",
        "",
        "## Rows",
        "",
        "| Symbol | Timeframe | Timestamp UTC | Canonical valid | Reasons | Observations |",
        "|---|---|---|---:|---|---:|",
    ]
    for row in inventory["rows"]:
        reasons = ", ".join(row["validation_reasons"]) or "none"
        lines.append(
            f"| {row['symbol']} | {row['timeframe']} | {row['timestamp_utc']} | "
            f"{row['canonical_valid']} | {reasons} | {row['observation_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_inventory(inventory: dict[str, Any], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "_gap_inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "_gap_inventory.md").write_text(
        render_markdown(inventory),
        encoding="utf-8",
    )
    csv_rows = [{
        **row,
        "validation_reasons": ",".join(row["validation_reasons"]),
        "observed_request_times_utc": ",".join(row["observed_request_times_utc"]),
    } for row in inventory["rows"]]
    pd.DataFrame(csv_rows).to_csv(output_root / "_gap_inventory.csv", index=False)


def run_cached_probe_and_inventory(
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    samples_per_series: int = 1,
    request_pause_seconds: float = 0.15,
    clean: bool = False,
    fetcher: Callable[[str, str, int], list[list[Any]]] = get_klines,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cache = CachedKlineFetcher(fetcher)

    def cached_probe(symbol, timeframe, target, request_pause_seconds):
        return gap_probe.probe_missing_timestamp(
            symbol,
            timeframe,
            target,
            request_pause_seconds=request_pause_seconds,
            fetch_rows=cache,
        )

    probe_report = gap_probe.build_probe_report(
        input_root=input_root,
        samples_per_series=samples_per_series,
        request_pause_seconds=request_pause_seconds,
        probe_fn=cached_probe,
    )
    gap_probe.write_probe_report(probe_report, output_root, clean=clean)

    missing_by_series, total_missing = collect_missing_sets(input_root)
    inventory = build_inventory(cache.responses, missing_by_series, total_missing)
    write_inventory(inventory, output_root)
    return probe_report, inventory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the public gap probe and inventory all missing rows seen in its cached responses."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--samples-per-series", type=int, default=1)
    parser.add_argument("--request-pause", type=float, default=0.15)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    probe, inventory = run_cached_probe_and_inventory(
        input_root=args.input_root,
        output_root=args.output_root,
        samples_per_series=args.samples_per_series,
        request_pause_seconds=args.request_pause,
        clean=args.clean,
    )
    print(json.dumps({
        "probe": probe["summary"],
        "inventory": inventory["summary"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
