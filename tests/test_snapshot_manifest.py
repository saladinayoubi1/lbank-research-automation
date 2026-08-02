import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import snapshot_manifest
from snapshot_manifest import (
    EXPECTED_PARQUET_COLUMNS,
    build_file_record,
    build_snapshot_manifest,
    inspect_parquet,
    sha256_file,
    write_snapshot_manifest,
)


def candle_frame(symbol: str, timeframe: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"]
            ),
            "open": [1.0, 2.0],
            "high": [2.0, 3.0],
            "low": [0.5, 1.5],
            "close": [1.5, 2.5],
            "volume": [10.0, 11.0],
            "symbol": [symbol, symbol],
            "timeframe": [timeframe, timeframe],
        }
    )[EXPECTED_PARQUET_COLUMNS]


def fake_series_file(root: Path, symbol: str, timeframe: str) -> Path:
    path = root / symbol / f"{timeframe}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"{symbol}:{timeframe}".encode())
    return path


def test_sha256_file_matches_hashlib(tmp_path: Path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"lbank")

    assert sha256_file(path) == hashlib.sha256(b"lbank").hexdigest()


def test_build_file_record_reports_integrity_metadata(tmp_path: Path):
    path = fake_series_file(tmp_path, "btc_usdt", "hour1")

    result = build_file_record(path, tmp_path, candle_frame("btc_usdt", "hour1"))

    assert result["path"] == "btc_usdt/hour1.parquet"
    assert result["rows"] == 2
    assert result["bytes"] > 0
    assert result["schema_ok"] is True
    assert result["first_candle_utc"] == "2026-01-01T00:00:00+00:00"
    assert result["last_candle_utc"] == "2026-01-01T01:00:00+00:00"


def test_build_snapshot_manifest_aggregates_and_sorts(tmp_path: Path, monkeypatch):
    btc = fake_series_file(tmp_path, "btc_usdt", "hour1")
    eth = fake_series_file(tmp_path, "eth_usdt", "hour4")

    records = {
        btc: build_file_record(btc, tmp_path, candle_frame("btc_usdt", "hour1")),
        eth: build_file_record(eth, tmp_path, candle_frame("eth_usdt", "hour4")),
    }
    monkeypatch.setattr(snapshot_manifest, "inspect_parquet", lambda path, root: records[path])

    result = build_snapshot_manifest(tmp_path)

    assert result["file_count"] == 2
    assert result["total_rows"] == 4
    assert result["total_bytes"] > 0
    assert result["all_schemas_ok"] is True
    assert [item["path"] for item in result["files"]] == [
        "btc_usdt/hour1.parquet",
        "eth_usdt/hour4.parquet",
    ]


def test_manifest_ignores_non_series_files(tmp_path: Path, monkeypatch):
    path = fake_series_file(tmp_path, "btc_usdt", "hour1")
    (tmp_path / "_backfill_status.csv").write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(
        snapshot_manifest,
        "inspect_parquet",
        lambda candidate, root: build_file_record(
            candidate, root, candle_frame("btc_usdt", "hour1")
        ),
    )

    result = build_snapshot_manifest(tmp_path)

    assert result["file_count"] == 1
    assert result["files"][0]["path"] == path.relative_to(tmp_path).as_posix()


def test_schema_mismatch_is_reported(tmp_path: Path):
    path = fake_series_file(tmp_path, "btc_usdt", "hour1")
    frame = candle_frame("btc_usdt", "hour1").drop(columns=["volume"])

    result = build_file_record(path, tmp_path, frame)

    assert result["schema_ok"] is False


def test_write_snapshot_manifest_creates_json_and_markdown(tmp_path: Path, monkeypatch):
    manifest = {
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "source_commit": "abc123",
        "file_count": 0,
        "total_rows": 0,
        "total_bytes": 0,
        "all_schemas_ok": True,
        "files": [],
    }
    monkeypatch.setattr(snapshot_manifest, "build_snapshot_manifest", lambda root: manifest)

    result = write_snapshot_manifest(tmp_path)

    json_path = tmp_path / "_snapshot_manifest.json"
    md_path = tmp_path / "_snapshot_manifest.md"
    assert json_path.exists()
    assert md_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["source_commit"] == "abc123"
    assert result["all_schemas_ok"] is True


def test_inspect_parquet_integration_when_engine_available(tmp_path: Path):
    pytest.importorskip("pyarrow")
    path = tmp_path / "btc_usdt" / "hour1.parquet"
    path.parent.mkdir(parents=True)
    candle_frame("btc_usdt", "hour1").to_parquet(path, index=False)

    result = inspect_parquet(path, tmp_path)

    assert result["rows"] == 2
    assert result["schema_ok"] is True
