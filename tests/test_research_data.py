from pathlib import Path

import pandas as pd
import pytest

from research_data import (
    EXPECTED_COLUMNS,
    ResearchDataError,
    get_series_readiness,
    load_research_series,
    validate_research_frame,
)


def status_frame(
    *,
    symbol: str = "btc_usdt",
    timeframe: str = "hour1",
    rows: int = 3,
    integrity_ok: bool = True,
    status: str = "current",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": rows,
                "status": status,
                "integrity_ok": integrity_ok,
                "missing_candles": 0 if integrity_ok else 1,
                "gap_count": 0 if integrity_ok else 1,
                "duplicate_count": 0,
                "off_grid_count": 0,
                "last_candle_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            }
        ]
    )


def candle_frame(
    timestamps=None,
    *,
    symbol: str = "btc_usdt",
    timeframe: str = "hour1",
) -> pd.DataFrame:
    timestamps = timestamps or [
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        "2026-01-01T02:00:00Z",
    ]
    size = len(timestamps)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "open": [1.0] * size,
            "high": [2.0] * size,
            "low": [0.5] * size,
            "close": [1.5] * size,
            "volume": [10.0] * size,
            "symbol": [symbol] * size,
            "timeframe": [timeframe] * size,
        }
    )[EXPECTED_COLUMNS]


def write_status(tmp_path: Path, frame: pd.DataFrame) -> Path:
    path = tmp_path / "_backfill_status.csv"
    frame.to_csv(path, index=False)
    return path


def test_get_series_readiness_returns_evaluated_row(tmp_path: Path):
    path = write_status(tmp_path, status_frame())

    result = get_series_readiness("btc_usdt", "hour1", path)

    assert result["ready_for_research"] is True
    assert result["readiness_reason"] == "ready"


def test_get_series_readiness_rejects_missing_series(tmp_path: Path):
    path = write_status(tmp_path, status_frame())

    with pytest.raises(ResearchDataError, match="absent"):
        get_series_readiness("eth_usdt", "hour1", path)


def test_validate_research_frame_sorts_and_normalizes_timestamps():
    frame = candle_frame(
        [
            "2026-01-01T02:00:00Z",
            "2026-01-01T00:00:00Z",
            "2026-01-01T01:00:00Z",
        ]
    )

    result = validate_research_frame(frame, "btc_usdt", "hour1")

    assert result["timestamp"].tolist() == list(
        pd.to_datetime(
            [
                "2026-01-01T00:00:00Z",
                "2026-01-01T01:00:00Z",
                "2026-01-01T02:00:00Z",
            ],
            utc=True,
        )
    )


def test_validate_research_frame_rejects_schema_drift():
    frame = candle_frame().drop(columns=["volume"])

    with pytest.raises(ResearchDataError, match="Unexpected Parquet schema"):
        validate_research_frame(frame, "btc_usdt", "hour1")


def test_validate_research_frame_rejects_runtime_gap():
    frame = candle_frame(
        [
            "2026-01-01T00:00:00Z",
            "2026-01-01T02:00:00Z",
        ]
    )

    with pytest.raises(ResearchDataError, match="Runtime integrity check failed"):
        validate_research_frame(frame, "btc_usdt", "hour1")


def test_validate_research_frame_rejects_wrong_series_identity():
    frame = candle_frame(symbol="eth_usdt")

    with pytest.raises(ResearchDataError, match="Unexpected symbol values"):
        validate_research_frame(frame, "btc_usdt", "hour1")


def test_load_research_series_refuses_blocked_status_before_read(
    tmp_path: Path,
    monkeypatch,
):
    status_path = write_status(
        tmp_path,
        status_frame(integrity_ok=False, status="invalid"),
    )
    called = False

    def fake_read_parquet(path):
        nonlocal called
        called = True
        return candle_frame()

    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)

    with pytest.raises(ResearchDataError, match="not research-ready"):
        load_research_series(
            "btc_usdt",
            "hour1",
            data_root=tmp_path,
            status_path=status_path,
        )
    assert called is False


def test_load_research_series_reads_only_ready_parquet(
    tmp_path: Path,
    monkeypatch,
):
    status_path = write_status(tmp_path, status_frame())
    parquet_path = tmp_path / "btc_usdt" / "hour1.parquet"
    parquet_path.parent.mkdir(parents=True)
    parquet_path.write_bytes(b"placeholder")
    monkeypatch.setattr(pd, "read_parquet", lambda path: candle_frame())

    result = load_research_series(
        "btc_usdt",
        "hour1",
        data_root=tmp_path,
        status_path=status_path,
    )

    assert len(result) == 3
    assert result["symbol"].unique().tolist() == ["btc_usdt"]


def test_load_research_series_applies_minimum_rows(tmp_path: Path):
    status_path = write_status(tmp_path, status_frame(rows=3))

    with pytest.raises(ResearchDataError, match="not research-ready"):
        load_research_series(
            "btc_usdt",
            "hour1",
            data_root=tmp_path,
            status_path=status_path,
            minimum_rows=4,
        )


def test_load_research_series_requires_parquet_file(tmp_path: Path):
    status_path = write_status(tmp_path, status_frame())

    with pytest.raises(ResearchDataError, match="Parquet file not found"):
        load_research_series(
            "btc_usdt",
            "hour1",
            data_root=tmp_path,
            status_path=status_path,
        )
