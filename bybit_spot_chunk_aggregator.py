from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd

START_DATE = "2022-12-01"
END_DATE = "2026-07-31"
SYMBOLS = ("btc_usdt", "eth_usdt")
TIMEFRAMES = {
    "minute15": pd.Timedelta(minutes=15),
    "hour1": pd.Timedelta(hours=1),
    "hour4": pd.Timedelta(hours=4),
}
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


class AggregationError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_index(step: pd.Timedelta) -> pd.DatetimeIndex:
    start = pd.Timestamp(START_DATE, tz="UTC")
    end = pd.Timestamp(END_DATE, tz="UTC") + pd.Timedelta(days=1)
    return pd.date_range(start, end, freq=step, inclusive="left")


def load_series(inputs: list[Path], symbol: str, timeframe: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    relative = Path("bybit_market") / symbol / f"{timeframe}.parquet"
    for root in inputs:
        path = root / relative
        if not path.exists():
            raise AggregationError(f"Missing input series: {path}")
        frame = pd.read_parquet(path)
        missing = sorted(set(CANONICAL_COLUMNS).difference(frame.columns))
        if missing:
            raise AggregationError(f"Missing columns in {path}: {missing}")
        frame = frame.loc[:, CANONICAL_COLUMNS].copy()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
        frames.append(frame)
    merged = pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    return merged


def validate_series(frame: pd.DataFrame, symbol: str, timeframe: str) -> dict[str, object]:
    step = TIMEFRAMES[timeframe]
    expected = expected_index(step)
    timestamps = pd.DatetimeIndex(frame["timestamp"])
    duplicate_count = int(timestamps.duplicated().sum())
    unique = timestamps.drop_duplicates().sort_values()
    missing = expected.difference(unique)
    unexpected = unique.difference(expected)
    step_ns = int(step.value)
    off_grid_count = int(sum((int(value.value) % step_ns) != 0 for value in unique))
    required_high = frame[["open", "close", "low"]].max(axis=1)
    required_low = frame[["open", "close", "high"]].min(axis=1)
    invalid_ohlc = int(((frame["high"] < required_high) | (frame["low"] > required_low)).sum())
    nonpositive = int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    negative_volume = int((frame["volume"] < 0).sum())
    symbol_mismatch = int(frame["symbol"].astype(str).str.lower().ne(symbol).sum())
    timeframe_mismatch = int(frame["timeframe"].astype(str).ne(timeframe).sum())
    ready = all(
        value == 0
        for value in [
            duplicate_count,
            len(missing),
            len(unexpected),
            off_grid_count,
            invalid_ohlc,
            nonpositive,
            negative_volume,
            symbol_mismatch,
            timeframe_mismatch,
        ]
    ) and len(frame) == len(expected)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "rows": int(len(frame)),
        "expected_rows": int(len(expected)),
        "first_timestamp": None if frame.empty else frame["timestamp"].iloc[0].isoformat(),
        "last_timestamp": None if frame.empty else frame["timestamp"].iloc[-1].isoformat(),
        "missing_candles": int(len(missing)),
        "gap_groups": 0 if len(missing) == 0 else 1 + int(((missing[1:] - missing[:-1]) != step).sum()),
        "duplicate_timestamps": duplicate_count,
        "unexpected_timestamps": int(len(unexpected)),
        "off_grid_timestamps": off_grid_count,
        "invalid_ohlc_rows": invalid_ohlc,
        "nonpositive_ohlc_rows": nonpositive,
        "negative_volume_rows": negative_volume,
        "symbol_mismatch_rows": symbol_mismatch,
        "timeframe_mismatch_rows": timeframe_mismatch,
        "status": "ready" if ready else "invalid",
        "integrity_ok": ready,
    }


def aggregate(base_root: Path, chunks_root: Path, output_root: Path) -> dict[str, object]:
    chunk_roots = [chunks_root / f"chunk-{number:02d}" for number in range(1, 27)]
    missing_chunks = [path.name for path in chunk_roots if not path.exists()]
    if missing_chunks:
        raise AggregationError(f"Missing chunk directories: {missing_chunks}")
    inputs = [base_root, *chunk_roots]
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)

    statuses: list[dict[str, object]] = []
    files: list[dict[str, object]] = []
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            frame = load_series(inputs, symbol, timeframe)
            status = validate_series(frame, symbol, timeframe)
            statuses.append(status)
            if not status["integrity_ok"]:
                raise AggregationError(f"Final integrity failed: {status}")
            path = output_root / "bybit_market" / symbol / f"{timeframe}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(path, index=False, compression="zstd")
            files.append(
                {
                    "path": path.relative_to(output_root).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                    "rows": status["rows"],
                    "first_timestamp": status["first_timestamp"],
                    "last_timestamp": status["last_timestamp"],
                }
            )

    report = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "venue": "bybit",
        "source": "official_public_spot_trade_archives",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "base_snapshot_artifact_id": 8845033283,
        "chunk_count": 26,
        "series_count": len(statuses),
        "all_series_ready": all(bool(item["integrity_ok"]) for item in statuses),
        "statuses": statuses,
        "files": files,
    }
    (output_root / "_final_integrity_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    pd.DataFrame(statuses).to_csv(output_root / "_final_integrity_status.csv", index=False)
    manifest = {
        "generated_at_utc": report["generated_at_utc"],
        "root": output_root.name,
        "files": files,
    }
    (output_root / "_snapshot_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-root", type=Path, required=True)
    parser.add_argument("--chunks-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = aggregate(args.base_root, args.chunks_root, args.output_root)
    print(json.dumps({"all_series_ready": report["all_series_ready"], "series_count": report["series_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
