from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from gap_repair import missing_timestamp_set
from main import (
    SYMBOLS,
    TIMEFRAMES,
    TIMEFRAME_SECONDS,
    get_klines,
    rows_to_frame,
)

LOGGER = logging.getLogger("lbank_gap_probe")
DEFAULT_INPUT_ROOT = Path("data/market")
DEFAULT_OUTPUT_ROOT = Path("build/gap_probe")
PROBE_ANCHORS = (
    ("before", -1),
    ("exact", 0),
    ("after", 1),
)


def utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def timestamps_from_raw_rows(rows: list[list[Any]]) -> pd.DatetimeIndex:
    """Extract unique UTC timestamps from raw API rows without OHLCV validation."""
    raw_values = [row[0] for row in rows if isinstance(row, (list, tuple)) and row]
    if not raw_values:
        return pd.DatetimeIndex([], tz="UTC")

    numeric = pd.to_numeric(pd.Series(raw_values), errors="coerce")
    timestamps = pd.to_datetime(numeric, unit="s", utc=True, errors="coerce")
    return pd.DatetimeIndex(timestamps.dropna()).drop_duplicates().sort_values()


def diagnose_exact_raw_rows(
    rows: list[list[Any]],
    target: pd.Timestamp,
) -> list[dict[str, Any]]:
    """Describe raw rows at the target and why canonical validation rejects them."""
    target = utc_timestamp(target)
    diagnosed: list[dict[str, Any]] = []

    for row in rows:
        if not isinstance(row, (list, tuple)) or not row:
            continue

        raw_timestamp = pd.to_numeric(pd.Series([row[0]]), errors="coerce").iloc[0]
        if pd.isna(raw_timestamp):
            continue
        timestamp = pd.to_datetime(raw_timestamp, unit="s", utc=True, errors="coerce")
        if pd.isna(timestamp) or timestamp != target:
            continue

        reasons: list[str] = []
        values = list(row[:6])
        if len(values) < 6:
            reasons.append("short_row")
            values.extend([None] * (6 - len(values)))

        numeric = pd.to_numeric(pd.Series(values[1:6]), errors="coerce")
        open_price, high, low, close, volume = numeric.tolist()
        if numeric.isna().any():
            reasons.append("non_numeric_or_missing_ohlcv")
        else:
            if high < max(open_price, close, low):
                reasons.append("high_below_ohlc_max")
            if low > min(open_price, close, high):
                reasons.append("low_above_ohlc_min")
            if volume < 0:
                reasons.append("negative_volume")

        diagnosed.append({
            "timestamp_utc": target.isoformat(),
            "open": values[1],
            "high": values[2],
            "low": values[3],
            "close": values[4],
            "volume": values[5],
            "validation_reasons": reasons,
        })

    return diagnosed


def sample_missing_timestamps(
    missing: set[pd.Timestamp] | list[pd.Timestamp],
    sample_count: int,
) -> list[pd.Timestamp]:
    """Select deterministic, spread-out missing timestamps."""
    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")

    ordered = sorted({utc_timestamp(timestamp) for timestamp in missing})
    if len(ordered) <= sample_count:
        return ordered
    if sample_count == 1:
        return [ordered[0]]

    indexes = [
        round(position * (len(ordered) - 1) / (sample_count - 1))
        for position in range(sample_count)
    ]
    return [ordered[index] for index in dict.fromkeys(indexes)]


def classify_observations(observations: list[dict[str, Any]]) -> tuple[str, bool]:
    """Classify raw-source presence separately from canonical validation."""
    if any(observation["validated_exact_present"] for observation in observations):
        return "recoverable_validated", True

    raw_exact = [
        observation for observation in observations
        if observation["raw_exact_present"]
    ]
    if raw_exact:
        if any(observation["validation_error"] is None for observation in raw_exact):
            return "present_but_rejected_by_validation", False
        return "present_but_validation_inconclusive", False

    successful = [
        observation
        for observation in observations
        if observation["request_error"] is None
    ]
    if not successful:
        return "inconclusive_api_failure", False

    returned_count = sum(
        observation["raw_returned_count"] for observation in successful
    )
    if returned_count == 0:
        return "inconclusive_empty_raw_response", False

    has_before = any(
        observation["raw_nearest_before_utc"] is not None
        for observation in successful
    )
    has_after = any(
        observation["raw_nearest_after_utc"] is not None
        for observation in successful
    )
    if has_before and has_after:
        return "absent_from_raw_public_kline_response", False
    return "inconclusive_unbracketed_raw_response", False


def probe_missing_timestamp(
    symbol: str,
    timeframe: str,
    missing_timestamp: pd.Timestamp,
    request_pause_seconds: float = 0.0,
    fetch_rows: Callable[[str, str, int], list[list[Any]]] | None = None,
    convert_rows: Callable[[list[list[Any]], str, str], pd.DataFrame] | None = None,
) -> dict[str, Any]:
    """Probe one missing candle from anchors immediately around its timestamp."""
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    if request_pause_seconds < 0:
        raise ValueError("request_pause_seconds cannot be negative")

    fetcher = fetch_rows or get_klines
    converter = convert_rows or rows_to_frame
    target = utc_timestamp(missing_timestamp)
    step = pd.Timedelta(TIMEFRAME_SECONDS[timeframe], unit="s")
    observations: list[dict[str, Any]] = []

    for anchor_name, offset in PROBE_ANCHORS:
        requested_at = target + (offset * step)
        observation: dict[str, Any] = {
            "anchor": anchor_name,
            "requested_time_utc": requested_at.isoformat(),
            "raw_returned_count": 0,
            "validated_returned_count": 0,
            "rejected_row_count": 0,
            "raw_first_returned_utc": None,
            "raw_last_returned_utc": None,
            "validated_first_returned_utc": None,
            "validated_last_returned_utc": None,
            "raw_exact_present": False,
            "validated_exact_present": False,
            "raw_nearest_before_utc": None,
            "raw_nearest_after_utc": None,
            "exact_raw_rows": [],
            "request_error": None,
            "validation_error": None,
        }

        try:
            rows = fetcher(symbol, timeframe, int(requested_at.timestamp()))
        except Exception as exc:  # Diagnostic output must survive API failure.
            observation["request_error"] = f"{type(exc).__name__}: {exc}"
            LOGGER.warning(
                "Gap probe request failed for %s %s at %s (%s): %s",
                symbol,
                timeframe,
                target,
                anchor_name,
                exc,
            )
        else:
            raw_timestamps = timestamps_from_raw_rows(rows)
            raw_before = raw_timestamps[raw_timestamps < target]
            raw_after = raw_timestamps[raw_timestamps > target]
            observation.update({
                "raw_returned_count": int(len(raw_timestamps)),
                "raw_first_returned_utc": (
                    None if raw_timestamps.empty else raw_timestamps[0].isoformat()
                ),
                "raw_last_returned_utc": (
                    None if raw_timestamps.empty else raw_timestamps[-1].isoformat()
                ),
                "raw_exact_present": bool(target in raw_timestamps),
                "raw_nearest_before_utc": (
                    None if raw_before.empty else raw_before[-1].isoformat()
                ),
                "raw_nearest_after_utc": (
                    None if raw_after.empty else raw_after[0].isoformat()
                ),
                "exact_raw_rows": diagnose_exact_raw_rows(rows, target),
            })

            try:
                frame = converter(rows, symbol, timeframe)
                if "timestamp" not in frame.columns:
                    raise ValueError("Converted API frame has no timestamp column")
                validated = pd.DatetimeIndex(
                    pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
                ).drop_duplicates().sort_values()
                observation.update({
                    "validated_returned_count": int(len(validated)),
                    "rejected_row_count": max(
                        0,
                        int(len(raw_timestamps) - len(validated)),
                    ),
                    "validated_first_returned_utc": (
                        None if validated.empty else validated[0].isoformat()
                    ),
                    "validated_last_returned_utc": (
                        None if validated.empty else validated[-1].isoformat()
                    ),
                    "validated_exact_present": bool(target in validated),
                })
            except Exception as exc:  # Keep raw evidence if validation fails.
                observation["validation_error"] = f"{type(exc).__name__}: {exc}"
                LOGGER.warning(
                    "Gap probe validation failed for %s %s at %s (%s): %s",
                    symbol,
                    timeframe,
                    target,
                    anchor_name,
                    exc,
                )

        observations.append(observation)
        if request_pause_seconds:
            time.sleep(request_pause_seconds)

    classification, validated_recovered = classify_observations(observations)
    successful_requests = sum(
        observation["request_error"] is None for observation in observations
    )
    failed_requests = len(observations) - successful_requests
    validation_errors = sum(
        observation["validation_error"] is not None for observation in observations
    )
    raw_exact_present = any(
        observation["raw_exact_present"] for observation in observations
    )
    validated_exact_present = any(
        observation["validated_exact_present"] for observation in observations
    )
    raw_bracketed = any(
        observation["raw_nearest_before_utc"] is not None
        for observation in observations
        if observation["request_error"] is None
    ) and any(
        observation["raw_nearest_after_utc"] is not None
        for observation in observations
        if observation["request_error"] is None
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "missing_timestamp_utc": target.isoformat(),
        "classification": classification,
        "raw_exact_present": raw_exact_present,
        "validated_exact_present": validated_exact_present,
        "validated_recovered": validated_recovered,
        "raw_bracketed_by_returned_candles": raw_bracketed,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
        "validation_errors": validation_errors,
        "observations": observations,
    }


def build_probe_report(
    input_root: Path = DEFAULT_INPUT_ROOT,
    samples_per_series: int = 1,
    max_series: int | None = None,
    request_pause_seconds: float = 0.15,
    frame_reader: Callable[[Path], pd.DataFrame] | None = None,
    probe_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Probe deterministic samples from every source series that contains gaps."""
    if samples_per_series < 1:
        raise ValueError("samples_per_series must be at least 1")
    if max_series is not None and max_series < 1:
        raise ValueError("max_series must be positive when provided")

    reader = frame_reader or pd.read_parquet
    probe = probe_fn or probe_missing_timestamp
    results: list[dict[str, Any]] = []
    source_series_with_gaps = 0
    sampled_series = 0
    total_source_missing = 0

    stop = False
    for symbol in SYMBOLS:
        if stop:
            break
        for timeframe in TIMEFRAMES:
            parquet_path = input_root / symbol / f"{timeframe}.parquet"
            if not parquet_path.exists():
                continue

            frame = reader(parquet_path)
            if "timestamp" not in frame.columns:
                raise ValueError(f"Missing timestamp column: {parquet_path}")

            missing = missing_timestamp_set(frame["timestamp"], timeframe)
            if not missing:
                continue

            source_series_with_gaps += 1
            total_source_missing += len(missing)
            if max_series is not None and sampled_series >= max_series:
                stop = True
                break

            samples = sample_missing_timestamps(missing, samples_per_series)
            sampled_series += 1
            for target in samples:
                result = probe(
                    symbol,
                    timeframe,
                    target,
                    request_pause_seconds=request_pause_seconds,
                )
                result["source_rows"] = int(len(frame))
                result["source_missing_candles"] = int(len(missing))
                results.append(result)

    classification_counts = Counter(
        result["classification"] for result in results
    )
    successful_requests = sum(result["successful_requests"] for result in results)
    failed_requests = sum(result["failed_requests"] for result in results)
    validation_errors = sum(result["validation_errors"] for result in results)

    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "input_root": input_root.as_posix(),
        "configuration": {
            "samples_per_series": samples_per_series,
            "max_series": max_series,
            "request_pause_seconds": request_pause_seconds,
            "anchors": [name for name, _ in PROBE_ANCHORS],
        },
        "summary": {
            "source_series_with_gaps": source_series_with_gaps,
            "sampled_series": sampled_series,
            "sampled_missing_timestamps": len(results),
            "total_source_missing_candles": total_source_missing,
            "successful_requests": successful_requests,
            "failed_requests": failed_requests,
            "validation_errors": validation_errors,
            "raw_exact_targets": sum(
                result["raw_exact_present"] for result in results
            ),
            "validated_exact_targets": sum(
                result["validated_exact_present"] for result in results
            ),
            "classification_counts": dict(sorted(classification_counts.items())),
        },
        "results": results,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# LBank Public Kline Gap Probe",
        "",
        f"Generated at: {report['generated_at_utc']}",
        "",
        "This report is diagnostic only. It does not alter canonical Parquet files, "
        "create synthetic candles, or change research-readiness decisions.",
        "",
        "## Summary",
        "",
        f"- Source series with gaps: {summary['source_series_with_gaps']}",
        f"- Sampled series: {summary['sampled_series']}",
        f"- Sampled missing timestamps: {summary['sampled_missing_timestamps']}",
        f"- Total source missing candles: {summary['total_source_missing_candles']}",
        f"- Successful API requests: {summary['successful_requests']}",
        f"- Failed API requests: {summary['failed_requests']}",
        f"- Validation errors: {summary['validation_errors']}",
        f"- Targets present in raw API rows: {summary['raw_exact_targets']}",
        f"- Targets retained after validation: {summary['validated_exact_targets']}",
        "- Classifications:",
    ]
    for classification, count in summary["classification_counts"].items():
        lines.append(f"  - `{classification}`: {count}")

    lines.extend([
        "",
        "## Sample results",
        "",
        "| Symbol | Timeframe | Missing timestamp UTC | Classification | Raw exact | Validated exact | Successful | Failed |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ])
    for result in report["results"]:
        lines.append(
            "| {symbol} | {timeframe} | {missing_timestamp_utc} | {classification} | "
            "{raw_exact_present} | {validated_exact_present} | "
            "{successful_requests} | {failed_requests} |".format(**result)
        )

    lines.extend([
        "",
        "## Classification meanings",
        "",
        "- `recoverable_validated`: the exact target survived canonical OHLCV validation.",
        "- `present_but_rejected_by_validation`: the raw API returned the target, but canonical validation removed it.",
        "- `present_but_validation_inconclusive`: the raw API returned the target, but validation itself errored.",
        "- `absent_from_raw_public_kline_response`: raw responses bracketed the target but never returned it.",
        "- `inconclusive_unbracketed_raw_response`: raw responses did not bracket the target.",
        "- `inconclusive_empty_raw_response`: successful requests contained no parseable raw timestamps.",
        "- `inconclusive_api_failure`: all three anchor requests failed.",
        "",
    ])
    return "\n".join(lines)


def write_probe_report(
    report: dict[str, Any],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    clean: bool = False,
) -> None:
    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    (output_root / "_gap_probe.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "_gap_probe.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )

    flattened = [
        {
            key: value
            for key, value in result.items()
            if key != "observations"
        }
        for result in report["results"]
    ]
    pd.DataFrame(flattened).to_csv(
        output_root / "_gap_probe.csv",
        index=False,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Probe raw and validated LBank rows around known candle gaps."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--samples-per-series", type=int, default=1)
    parser.add_argument("--max-series", type=int)
    parser.add_argument("--request-pause", type=float, default=0.15)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_probe_report(
        input_root=args.input_root,
        samples_per_series=args.samples_per_series,
        max_series=args.max_series,
        request_pause_seconds=args.request_pause,
    )
    write_probe_report(report, output_root=args.output_root, clean=args.clean)
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    main()
