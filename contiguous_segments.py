from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from main import COLUMNS, SYMBOLS, TIMEFRAMES, TIMEFRAME_SECONDS

DEFAULT_INPUT_ROOT = Path("data/market")
DEFAULT_OUTPUT_ROOT = Path("build/contiguous_segments")
EXPECTED_COLUMNS = COLUMNS + ["symbol", "timeframe"]


class SegmentAnalysisError(RuntimeError):
    pass


def normalize_series_frame(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    if frame.columns.tolist() != EXPECTED_COLUMNS:
        raise SegmentAnalysisError(
            f"Unexpected schema for {symbol} {timeframe}: {frame.columns.tolist()}"
        )
    if frame.empty:
        raise SegmentAnalysisError(f"Empty series: {symbol} {timeframe}")
    if timeframe not in TIMEFRAME_SECONDS:
        raise SegmentAnalysisError(f"Unsupported timeframe: {timeframe}")

    normalized = frame.copy()
    normalized["timestamp"] = pd.to_datetime(
        normalized["timestamp"], utc=True, errors="raise"
    )

    symbols = set(normalized["symbol"].dropna().astype(str))
    timeframes = set(normalized["timeframe"].dropna().astype(str))
    if symbols != {symbol}:
        raise SegmentAnalysisError(
            f"Unexpected symbol values for {symbol} {timeframe}: {sorted(symbols)}"
        )
    if timeframes != {timeframe}:
        raise SegmentAnalysisError(
            f"Unexpected timeframe values for {symbol} {timeframe}: {sorted(timeframes)}"
        )

    numeric_columns = ["open", "high", "low", "close", "volume"]
    if normalized[numeric_columns].isna().any().any():
        raise SegmentAnalysisError(f"Null OHLCV value in {symbol} {timeframe}")

    return normalized.sort_values("timestamp").reset_index(drop=True)


def timestamp_diagnostics(
    timestamps: pd.Series,
    timeframe: str,
) -> dict[str, Any]:
    normalized = pd.to_datetime(timestamps, utc=True, errors="raise")
    duplicate_count = int(normalized.duplicated().sum())
    unique = pd.DatetimeIndex(normalized.drop_duplicates().sort_values())
    step_seconds = TIMEFRAME_SECONDS[timeframe]
    step_ns = step_seconds * 1_000_000_000
    off_grid_count = int((unique.asi8 % step_ns != 0).sum())

    if unique.empty:
        return {
            "duplicate_count": duplicate_count,
            "off_grid_count": off_grid_count,
            "expected_rows": 0,
            "missing_candles": 0,
            "unique_timestamps": unique,
        }

    span_seconds = int((unique[-1] - unique[0]).total_seconds())
    expected_rows = span_seconds // step_seconds + 1
    missing_candles = max(0, int(expected_rows - len(unique)))
    return {
        "duplicate_count": duplicate_count,
        "off_grid_count": off_grid_count,
        "expected_rows": int(expected_rows),
        "missing_candles": missing_candles,
        "unique_timestamps": unique,
    }


def split_contiguous_timestamps(
    timestamps: pd.DatetimeIndex,
    timeframe: str,
) -> list[pd.DatetimeIndex]:
    if timestamps.empty:
        return []

    step = pd.Timedelta(TIMEFRAME_SECONDS[timeframe], unit="s")
    deltas = pd.Series(timestamps).diff()
    starts = [0, *deltas[deltas != step].index.tolist()[1:]]
    # The first diff is NaT and is intentionally represented by start index 0.
    starts = sorted(set(index for index in starts if 0 <= index < len(timestamps)))
    ends = [*starts[1:], len(timestamps)]
    return [timestamps[start:end] for start, end in zip(starts, ends)]


def gap_candles_between(
    left: pd.Timestamp,
    right: pd.Timestamp,
    timeframe: str,
) -> int | None:
    step_seconds = TIMEFRAME_SECONDS[timeframe]
    delta_seconds = int((right - left).total_seconds())
    if delta_seconds <= step_seconds:
        return 0
    if delta_seconds % step_seconds != 0:
        return None
    return delta_seconds // step_seconds - 1


def analyze_series_segments(
    frame: pd.DataFrame,
    symbol: str,
    timeframe: str,
    minimum_segment_rows: int = 0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if minimum_segment_rows < 0:
        raise ValueError("minimum_segment_rows cannot be negative")

    normalized = normalize_series_frame(frame, symbol, timeframe)
    diagnostics = timestamp_diagnostics(normalized["timestamp"], timeframe)
    unique = diagnostics.pop("unique_timestamps")
    segments = split_contiguous_timestamps(unique, timeframe)
    step_seconds = TIMEFRAME_SECONDS[timeframe]

    segment_rows: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        previous_end = segments[index - 1][-1] if index > 0 else None
        next_start = segments[index + 1][0] if index + 1 < len(segments) else None
        rows = int(len(segment))
        first = segment[0]
        last = segment[-1]
        segment_rows.append({
            "symbol": symbol,
            "timeframe": timeframe,
            "segment_index": index + 1,
            "rows": rows,
            "first_candle_utc": first.isoformat(),
            "last_candle_utc": last.isoformat(),
            "calendar_span_hours": (last - first).total_seconds() / 3600,
            "covered_hours": rows * step_seconds / 3600,
            "share_of_unique_rows": rows / len(unique),
            "gap_before_candles": (
                None
                if previous_end is None
                else gap_candles_between(previous_end, first, timeframe)
            ),
            "gap_after_candles": (
                None
                if next_start is None
                else gap_candles_between(last, next_start, timeframe)
            ),
            "meets_minimum_rows": rows >= minimum_segment_rows,
        })

    largest = max(segment_rows, key=lambda row: row["rows"])
    series_summary = {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(normalized)),
        "unique_rows": int(len(unique)),
        **diagnostics,
        "segment_count": len(segment_rows),
        "segments_meeting_minimum": sum(
            row["meets_minimum_rows"] for row in segment_rows
        ),
        "largest_segment_index": largest["segment_index"],
        "largest_segment_rows": largest["rows"],
        "largest_segment_share": largest["share_of_unique_rows"],
        "largest_segment_first_candle_utc": largest["first_candle_utc"],
        "largest_segment_last_candle_utc": largest["last_candle_utc"],
        "internally_clean_segments": (
            diagnostics["duplicate_count"] == 0
            and diagnostics["off_grid_count"] == 0
        ),
    }
    return series_summary, segment_rows


def build_segment_report(
    input_root: Path = DEFAULT_INPUT_ROOT,
    minimum_segment_rows: int = 0,
    frame_reader: Callable[[Path], pd.DataFrame] = pd.read_parquet,
) -> dict[str, Any]:
    if minimum_segment_rows < 0:
        raise ValueError("minimum_segment_rows cannot be negative")

    series_rows: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            path = input_root / symbol / f"{timeframe}.parquet"
            if not path.exists():
                continue
            frame = frame_reader(path)
            summary, series_segments = analyze_series_segments(
                frame,
                symbol,
                timeframe,
                minimum_segment_rows=minimum_segment_rows,
            )
            series_rows.append(summary)
            segments.extend(series_segments)

    if not series_rows:
        raise SegmentAnalysisError(f"No canonical Parquet series found: {input_root}")

    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "input_root": input_root.as_posix(),
        "minimum_segment_rows": minimum_segment_rows,
        "summary": {
            "total_series": len(series_rows),
            "series_with_multiple_segments": sum(
                row["segment_count"] > 1 for row in series_rows
            ),
            "series_with_single_segment": sum(
                row["segment_count"] == 1 for row in series_rows
            ),
            "total_segments": len(segments),
            "segments_meeting_minimum": sum(
                row["meets_minimum_rows"] for row in segments
            ),
            "series_with_large_segment": sum(
                row["segments_meeting_minimum"] > 0 for row in series_rows
            ),
            "total_missing_candles": sum(
                row["missing_candles"] for row in series_rows
            ),
            "total_duplicates": sum(
                row["duplicate_count"] for row in series_rows
            ),
            "total_off_grid": sum(
                row["off_grid_count"] for row in series_rows
            ),
        },
        "series": sorted(
            series_rows,
            key=lambda row: (row["symbol"], row["timeframe"]),
        ),
        "segments": sorted(
            segments,
            key=lambda row: (
                row["symbol"], row["timeframe"], row["segment_index"]
            ),
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# LBank Contiguous Segment Analysis",
        "",
        f"Generated at: {report['generated_at_utc']}",
        f"Minimum segment rows: {report['minimum_segment_rows']}",
        "",
        "This report is diagnostic only. A segment meeting the configured row "
        "threshold is not automatically research-ready.",
        "",
        "## Summary",
        "",
        f"- Total series: {summary['total_series']}",
        f"- Series with one segment: {summary['series_with_single_segment']}",
        f"- Series with multiple segments: {summary['series_with_multiple_segments']}",
        f"- Total segments: {summary['total_segments']}",
        f"- Segments meeting minimum: {summary['segments_meeting_minimum']}",
        f"- Series with at least one large segment: {summary['series_with_large_segment']}",
        f"- Total missing candles: {summary['total_missing_candles']}",
        f"- Total duplicates: {summary['total_duplicates']}",
        f"- Total off-grid timestamps: {summary['total_off_grid']}",
        "",
        "## Series",
        "",
        "| Symbol | Timeframe | Rows | Missing | Segments | Largest rows | Largest share | Largest first | Largest last |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in report["series"]:
        lines.append(
            f"| {row['symbol']} | {row['timeframe']} | {row['unique_rows']} | "
            f"{row['missing_candles']} | {row['segment_count']} | "
            f"{row['largest_segment_rows']} | "
            f"{row['largest_segment_share']:.4%} | "
            f"{row['largest_segment_first_candle_utc']} | "
            f"{row['largest_segment_last_candle_utc']} |"
        )

    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "- The report does not change the strict series-level integrity gate.",
        "- Large contiguous blocks are candidates for separate review, not approval.",
        "- Any future segment loader must pin exact start/end timestamps and preserve provenance.",
        "- Cross-segment backtests must not bridge gaps or invent returns across missing candles.",
        "",
    ])
    return "\n".join(lines)


def write_segment_report(
    report: dict[str, Any],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    clean: bool = False,
) -> None:
    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    (output_root / "_contiguous_segments.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "_contiguous_segments.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    pd.DataFrame(report["series"]).to_csv(
        output_root / "_contiguous_series.csv", index=False
    )
    pd.DataFrame(report["segments"]).to_csv(
        output_root / "_contiguous_segments.csv", index=False
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze maximal timestamp-contiguous blocks in canonical OHLCV series."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--minimum-segment-rows", type=int, default=0)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_segment_report(
        input_root=args.input_root,
        minimum_segment_rows=args.minimum_segment_rows,
    )
    write_segment_report(report, args.output_root, clean=args.clean)
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
