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
    """Classify whether a missing candle is returned by public API probes."""
    if any(observation["exact_present"] for observation in observations):
        return "recoverable", True

    successful = [
        observation for observation in observations if observation["error"] is None
    ]
    if not successful:
        return "inconclusive_api_failure", False

    returned_count = sum(observation["returned_count"] for observation in successful)
    if returned_count == 0:
        return "inconclusive_empty_response", False

    has_before = any(
        observation["nearest_before_utc"] is not None
        for observation in successful
    )
    has_after = any(
        observation["nearest_after_utc"] is not None
        for observation in successful
    )
    bracketed = has_before and has_after
    if bracketed:
        return "absent_from_public_kline_response", False
    return "inconclusive_unbracketed", False


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
            "returned_count": 0,
            "first_returned_utc": None,
            "last_returned_utc": None,
            "exact_present": False,
            "nearest_before_utc": None,
            "nearest_after_utc": None,
            "error": None,
        }

        try:
            rows = fetcher(symbol, timeframe, int(requested_at.timestamp()))
            frame = converter(rows, symbol, timeframe)
            if "timestamp" not in frame.columns:
                raise ValueError("Converted API frame has no timestamp column")

            timestamps = pd.DatetimeIndex(
                pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
            ).drop_duplicates().sort_values()
            before = timestamps[timestamps < target]
            after = timestamps[timestamps > target]

            observation.update({
                "returned_count": int(len(timestamps)),
                "first_returned_utc": (
                    None if timestamps.empty else timestamps[0].isoformat()
                ),
                "last_returned_utc": (
                    None if timestamps.empty else timestamps[-1].isoformat()
                ),
                "exact_present": bool(target in timestamps),
                "nearest_before_utc": (
                    None if before.empty else before[-1].isoformat()
                ),
                "nearest_after_utc": (
                    None if after.empty else after[0].isoformat()
                ),
            })
        except Exception as exc:  # Diagnostic output must survive partial API failure.
            observation["error"] = f"{type(exc).__name__}: {exc}"
            LOGGER.warning(
                "Gap probe failed for %s %s at %s (%s): %s",
                symbol,
                timeframe,
                target,
                anchor_name,
                exc,
            )

        observations.append(observation)
        if request_pause_seconds:
            time.sleep(request_pause_seconds)

    classification, exact_recovered = classify_observations(observations)
    successful_requests = sum(
        observation["error"] is None for observation in observations
    )
    failed_requests = len(observations) - successful_requests
    bracketed = any(
        observation["nearest_before_utc"] is not None
        for observation in observations
        if observation["error"] is None
    ) and any(
        observation["nearest_after_utc"] is not None
        for observation in observations
        if observation["error"] is None
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "missing_timestamp_utc": target.isoformat(),
        "classification": classification,
        "exact_recovered": exact_recovered,
        "bracketed_by_returned_candles": bracketed,
        "successful_requests": successful_requests,
        "failed_requests": failed_requests,
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
        "- Classifications:",
    ]
    for classification, count in summary["classification_counts"].items():
        lines.append(f"  - `{classification}`: {count}")

    lines.extend([
        "",
        "## Sample results",
        "",
        "| Symbol | Timeframe | Missing timestamp UTC | Classification | Exact returned | Bracketed | Successful | Failed |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ])
    for result in report["results"]:
        lines.append(
            "| {symbol} | {timeframe} | {missing_timestamp_utc} | {classification} | "
            "{exact_recovered} | {bracketed_by_returned_candles} | "
            "{successful_requests} | {failed_requests} |".format(**result)
        )

    lines.extend([
        "",
        "## Classification meanings",
        "",
        "- `recoverable`: at least one public API response contained the exact missing timestamp.",
        "- `absent_from_public_kline_response`: successful responses returned candles on both sides of the target, but never the target itself.",
        "- `inconclusive_unbracketed`: responses succeeded but did not provide candles on both sides of the target.",
        "- `inconclusive_empty_response`: all successful responses were empty.",
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
        description="Probe public LBank kline responses around known missing candles."
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
