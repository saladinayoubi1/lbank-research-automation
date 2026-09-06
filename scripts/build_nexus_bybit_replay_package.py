from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


START_DATE = "2022-12-01"
END_DATE = "2026-07-31"
SYMBOLS = ("btc_usdt", "eth_usdt")
TIMEFRAMES = {
    "minute15": (pd.Timedelta(minutes=15), 128544),
    "hour1": (pd.Timedelta(hours=1), 32136),
    "hour4": (pd.Timedelta(hours=4), 8034),
}
CANONICAL_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "symbol",
    "timeframe",
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class ReplayPackageError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_series_digest(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    for row in frame.loc[:, CANONICAL_COLUMNS].itertuples(index=False, name=None):
        timestamp = pd.Timestamp(row[0])
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        digest.update(struct.pack("<q", int(timestamp.value)))
        for value in row[1:6]:
            number = float(value)
            if not math.isfinite(number):
                raise ReplayPackageError("non-finite market value in replay series")
            digest.update(struct.pack("<d", number))
        for value in row[6:8]:
            encoded = str(value).encode("utf-8")
            digest.update(struct.pack("<I", len(encoded)))
            digest.update(encoded)
    return digest.hexdigest()


def expected_index(step: pd.Timedelta) -> pd.DatetimeIndex:
    start = pd.Timestamp(START_DATE, tz="UTC")
    end = pd.Timestamp(END_DATE, tz="UTC") + pd.Timedelta(days=1)
    return pd.date_range(start, end, freq=step, inclusive="left")


def canonical_timestamp_index(values: Any) -> pd.DatetimeIndex:
    """Normalize equivalent UTC timestamps to one representation before strict comparison."""
    return pd.DatetimeIndex(values).as_unit("ns")


def validate_series(path: Path, symbol: str, timeframe: str) -> dict[str, Any]:
    step, expected_rows = TIMEFRAMES[timeframe]
    frame = pd.read_parquet(path)
    missing_columns = sorted(set(CANONICAL_COLUMNS).difference(frame.columns))
    if missing_columns:
        raise ReplayPackageError(f"{path} missing columns: {missing_columns}")
    frame = frame.loc[:, CANONICAL_COLUMNS].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    timestamps = canonical_timestamp_index(frame["timestamp"])
    expected = canonical_timestamp_index(expected_index(step))
    frame["timestamp"] = timestamps
    if len(frame) != expected_rows or len(frame) != len(expected):
        raise ReplayPackageError(
            f"{path} row count {len(frame)} does not match expected {expected_rows}"
        )
    if not timestamps.equals(expected):
        missing = expected.difference(timestamps)
        unexpected = timestamps.difference(expected)
        raise ReplayPackageError(
            f"{path} timestamp grid mismatch missing={len(missing)} unexpected={len(unexpected)}"
        )
    if timestamps.duplicated().any():
        raise ReplayPackageError(f"{path} contains duplicate timestamps")
    numeric = frame[["open", "high", "low", "close", "volume"]]
    if numeric.isna().any().any():
        raise ReplayPackageError(f"{path} contains null market values")
    required_high = frame[["open", "close", "low"]].max(axis=1)
    required_low = frame[["open", "close", "high"]].min(axis=1)
    if ((frame["high"] < required_high) | (frame["low"] > required_low)).any():
        raise ReplayPackageError(f"{path} contains invalid OHLC rows")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ReplayPackageError(f"{path} contains non-positive OHLC values")
    if (frame["volume"] < 0).any():
        raise ReplayPackageError(f"{path} contains negative volume")
    if frame["symbol"].astype(str).str.lower().ne(symbol).any():
        raise ReplayPackageError(f"{path} contains symbol mismatch")
    if frame["timeframe"].astype(str).ne(timeframe).any():
        raise ReplayPackageError(f"{path} contains timeframe mismatch")
    return {
        "path": path.as_posix(),
        "bytes": path.stat().st_size,
        "parquet_sha256": sha256_file(path),
        "semantic_sha256": semantic_series_digest(frame),
        "rows": int(len(frame)),
        "first_timestamp": frame["timestamp"].iloc[0].isoformat(),
        "last_timestamp": frame["timestamp"].iloc[-1].isoformat(),
    }


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def build_manifest(root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    semantic_root = hashlib.sha256()
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            relative = Path("bybit_market") / symbol / f"{timeframe}.parquet"
            path = root / relative
            if not path.is_file():
                raise ReplayPackageError(f"missing replay series: {relative.as_posix()}")
            item = validate_series(path, symbol, timeframe)
            item["path"] = relative.as_posix()
            files.append(item)
            semantic_root.update(relative.as_posix().encode("utf-8"))
            semantic_root.update(b"\0")
            semantic_root.update(bytes.fromhex(item["semantic_sha256"]))
    manifest = {
        "schema_version": 2,
        "venue": "bybit",
        "source": "official_public_spot_trade_archives",
        "start_date": START_DATE,
        "end_date": END_DATE,
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "series_count": len(files),
        "semantic_dataset_sha256": semantic_root.hexdigest(),
        "files": files,
    }
    manifest["manifest_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    return manifest


def write_deterministic_zip(root: Path, output_zip: Path, manifest: dict[str, Any]) -> str:
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    entries: list[tuple[str, bytes]] = [("REPLAY_DATASET_MANIFEST.json", manifest_bytes)]
    for item in manifest["files"]:
        relative = str(item["path"])
        entries.append((relative, (root / relative).read_bytes()))
    entries.sort(key=lambda pair: pair[0])
    with zipfile.ZipFile(
        output_zip,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as handle:
        for name, payload in entries:
            info = zipfile.ZipInfo(filename=name, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            handle.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return sha256_file(output_zip)


def build_package(root: Path, output_zip: Path, delivery_path: Path) -> dict[str, Any]:
    manifest = build_manifest(root)
    replay_sha = write_deterministic_zip(root, output_zip, manifest)
    delivery = {
        "schema_version": 2,
        "file_name": output_zip.name,
        "size_bytes": output_zip.stat().st_size,
        "sha256": replay_sha,
        "semantic_dataset_sha256": manifest["semantic_dataset_sha256"],
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "range": f"{START_DATE} through {END_DATE} UTC",
        "series_count": manifest["series_count"],
        "paper_replay_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
    }
    delivery_path.parent.mkdir(parents=True, exist_ok=True)
    delivery_path.write_text(json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(delivery, sort_keys=True))
    return delivery


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-zip", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_package(args.root, args.output_zip, args.delivery)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
