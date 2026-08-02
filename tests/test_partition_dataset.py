from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from main import COLUMNS
from partition_dataset import (
    CANONICAL_COLUMNS,
    PartitionError,
    build_partitioned_dataset,
)


def make_frame(
    timestamps: list[str],
    *,
    symbol: str = "btc_usdt",
    timeframe: str = "minute15",
) -> pd.DataFrame:
    count = len(timestamps)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, utc=True),
            "open": [100.0 + index for index in range(count)],
            "high": [101.0 + index for index in range(count)],
            "low": [99.0 + index for index in range(count)],
            "close": [100.5 + index for index in range(count)],
            "volume": [10.0 + index for index in range(count)],
            "symbol": [symbol] * count,
            "timeframe": [timeframe] * count,
        },
        columns=COLUMNS + ["symbol", "timeframe"],
    )


def write_source(
    input_root: Path,
    frame: pd.DataFrame,
    *,
    symbol: str = "btc_usdt",
    timeframe: str = "minute15",
) -> Path:
    path = input_root / symbol / f"{timeframe}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False, compression="zstd")
    return path


def test_partitions_losslessly_across_months(tmp_path: Path) -> None:
    input_root = tmp_path / "market"
    output_root = tmp_path / "partitioned"
    frame = make_frame(
        [
            "2025-01-31T23:45:00Z",
            "2025-02-01T00:00:00Z",
        ]
    )
    write_source(input_root, frame)

    manifest = build_partitioned_dataset(input_root, output_root, clean=True)

    assert manifest["source_file_count"] == 1
    assert manifest["partition_count"] == 2
    assert manifest["total_rows"] == 2
    assert manifest["partition_rows"] == 2
    assert manifest["row_conservation_ok"] is True
    assert manifest["source_files"][0]["integrity_ok"] is True

    january = (
        output_root
        / "symbol=btc_usdt"
        / "timeframe=minute15"
        / "year=2025"
        / "month=01"
        / "part-00000.parquet"
    )
    february = Path(str(january).replace("month=01", "month=02"))
    assert january.exists()
    assert february.exists()
    assert len(pd.read_parquet(january)) == 1
    assert len(pd.read_parquet(february)) == 1
    assert list(pd.read_parquet(january).columns) == CANONICAL_COLUMNS


def test_records_gaps_without_dropping_rows(tmp_path: Path) -> None:
    input_root = tmp_path / "market"
    output_root = tmp_path / "partitioned"
    frame = make_frame(
        [
            "2025-01-01T00:00:00Z",
            "2025-01-01T00:30:00Z",
        ]
    )
    write_source(input_root, frame)

    manifest = build_partitioned_dataset(input_root, output_root)
    source = manifest["source_files"][0]

    assert manifest["total_rows"] == 2
    assert manifest["partition_rows"] == 2
    assert source["gap_count"] == 1
    assert source["missing_candles"] == 1
    assert source["integrity_ok"] is False


def test_rejects_symbol_identity_mismatch(tmp_path: Path) -> None:
    input_root = tmp_path / "market"
    output_root = tmp_path / "partitioned"
    frame = make_frame(["2025-01-01T00:00:00Z"], symbol="eth_usdt")
    write_source(input_root, frame, symbol="btc_usdt")

    with pytest.raises(PartitionError, match="Symbol identity mismatch"):
        build_partitioned_dataset(input_root, output_root)


def test_rejects_schema_drift(tmp_path: Path) -> None:
    input_root = tmp_path / "market"
    output_root = tmp_path / "partitioned"
    frame = make_frame(["2025-01-01T00:00:00Z"]).drop(columns=["volume"])
    write_source(input_root, frame)

    with pytest.raises(PartitionError, match="Schema mismatch"):
        build_partitioned_dataset(input_root, output_root)


def test_rejects_missing_source_files(tmp_path: Path) -> None:
    with pytest.raises(PartitionError, match="No source Parquet files"):
        build_partitioned_dataset(tmp_path / "empty", tmp_path / "output")


def test_clean_removes_stale_output(tmp_path: Path) -> None:
    input_root = tmp_path / "market"
    output_root = tmp_path / "partitioned"
    stale = output_root / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    write_source(input_root, make_frame(["2025-01-01T00:00:00Z"]))

    build_partitioned_dataset(input_root, output_root, clean=True)

    assert not stale.exists()


def test_carries_snapshot_manifest_metadata(tmp_path: Path) -> None:
    input_root = tmp_path / "market"
    output_root = tmp_path / "partitioned"
    write_source(input_root, make_frame(["2025-01-01T00:00:00Z"]))
    source_manifest = input_root / "_snapshot_manifest.json"
    source_manifest.write_text(
        json.dumps({"source_commit": "abc123"}),
        encoding="utf-8",
    )

    manifest = build_partitioned_dataset(input_root, output_root)

    assert manifest["source_commit"] == "abc123"
    assert manifest["snapshot_manifest_path"] == "_snapshot_manifest.json"
    assert manifest["snapshot_manifest_sha256"] == hashlib.sha256(
        source_manifest.read_bytes()
    ).hexdigest()
    assert (output_root / "_partition_manifest.json").exists()
    assert (output_root / "_partition_manifest.md").exists()
