from datetime import datetime, timezone

import pandas as pd
import pytest

import cross_source_gap_reconciliation as recon


def _row(source, close, ts=1710000000000, *, high=None, symbol="BTCUSDT"):
    close_value = str(close)
    high_value = str(high if high is not None else close)
    return {
        "source": source,
        "market_type": "spot",
        "symbol": symbol,
        "interval": "15",
        "open_time_ms": ts,
        "close_time_ms": ts + 900000 - 1,
        "open": close_value,
        "high": high_value,
        "low": close_value,
        "close": close_value,
        "volume": "1",
        "closed": True,
    }


def test_missing_timestamps_detects_internal_gap():
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:30:00Z",
        ], utc=True)
    })
    assert recon.missing_timestamps(frame, "minute15") == [pd.Timestamp("2024-01-01T00:15:00Z")]


def test_duplicate_input_timestamp_fails_closed():
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:00:00Z",
        ], utc=True)
    })
    with pytest.raises(ValueError, match="duplicate_timestamp"):
        recon.missing_timestamps(frame, "minute15")


def test_out_of_order_input_timestamp_fails_closed():
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-01-01T00:15:00Z",
            "2024-01-01T00:00:00Z",
        ], utc=True)
    })
    with pytest.raises(ValueError, match="out_of_order_timestamp"):
        recon.missing_timestamps(frame, "minute15")


def test_off_grid_input_timestamp_fails_closed():
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:16:00Z",
        ], utc=True)
    })
    with pytest.raises(ValueError, match="off_grid_timestamp"):
        recon.missing_timestamps(frame, "minute15")


def test_invalid_input_blocks_before_any_source_fetch(tmp_path, monkeypatch):
    path = tmp_path / "minute15.parquet"
    pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-01-01T00:15:00Z",
            "2024-01-01T00:00:00Z",
        ], utc=True)
    }).to_parquet(path, index=False)
    monkeypatch.setattr(recon, "fetch_bybit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")))
    monkeypatch.setattr(recon, "fetch_binance", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")))

    with pytest.raises(ValueError, match="out_of_order_timestamp"):
        recon.reconcile_dataset(path, "btc_usdt", "minute15")


def test_eligible_only_when_primary_and_secondary_ohlc_agree(monkeypatch):
    monkeypatch.setattr(recon, "fetch_bybit", lambda *a, **k: [_row("Bybit", "100")])
    monkeypatch.setattr(recon, "fetch_binance", lambda *a, **k: [_row("Binance", "100.5")])
    candidate = recon.reconcile_one_timestamp(
        "btc_usdt",
        "minute15",
        pd.Timestamp(1710000000000, unit="ms", tz="UTC"),
        now_ms=1710002000000,
    )
    assert candidate.status == "eligible_candidate"
    assert candidate.selected_source == "Bybit"
    assert candidate.primary_candle_sha256
    assert candidate.secondary_candle_sha256


def test_blocks_material_cross_source_ohlc_disagreement(monkeypatch):
    monkeypatch.setattr(recon, "fetch_bybit", lambda *a, **k: [_row("Bybit", "100", high="100")])
    monkeypatch.setattr(recon, "fetch_binance", lambda *a, **k: [_row("Binance", "100", high="105")])
    candidate = recon.reconcile_one_timestamp(
        "btc_usdt",
        "minute15",
        pd.Timestamp(1710000000000, unit="ms", tz="UTC"),
        now_ms=1710002000000,
    )
    assert candidate.status == "blocked"
    assert candidate.reason == "cross_source_ohlc_disagreement"


def test_source_identity_mismatch_fails_closed(monkeypatch):
    monkeypatch.setattr(recon, "fetch_bybit", lambda *a, **k: [_row("Binance", "100")])
    monkeypatch.setattr(recon, "fetch_binance", lambda *a, **k: [_row("Binance", "100")])
    candidate = recon.reconcile_one_timestamp(
        "btc_usdt",
        "minute15",
        pd.Timestamp(1710000000000, unit="ms", tz="UTC"),
        now_ms=1710002000000,
    )
    assert candidate.status == "blocked"
    assert candidate.reason.startswith("source_validation_failed:source identity mismatch")


def test_unknown_symbol_fails_closed_without_fetch(monkeypatch):
    monkeypatch.setattr(recon, "fetch_bybit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")))
    candidate = recon.reconcile_one_timestamp(
        "aero_usdt",
        "minute15",
        pd.Timestamp(1710000000000, unit="ms", tz="UTC"),
        now_ms=1710002000000,
    )
    assert candidate.status == "blocked"
    assert candidate.reason == "mapping_unapproved"


def test_reconciliation_digest_is_stable_across_generation_times(tmp_path, monkeypatch):
    path = tmp_path / "minute15.parquet"
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2024-03-09T16:00:00Z",
            "2024-03-09T16:30:00Z",
        ], utc=True)
    })
    frame.to_parquet(path, index=False)
    target_ts = int(pd.Timestamp("2024-03-09T16:15:00Z").timestamp() * 1000)
    monkeypatch.setattr(recon, "fetch_bybit", lambda *a, **k: [_row("Bybit", "100", ts=target_ts)])
    monkeypatch.setattr(recon, "fetch_binance", lambda *a, **k: [_row("Binance", "100.5", ts=target_ts)])
    monkeypatch.setattr(recon, "OUTPUT_ROOT", tmp_path / "out")

    first = recon.reconcile_dataset(
        path,
        "btc_usdt",
        "minute15",
        generated_at=datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc),
    )
    second = recon.reconcile_dataset(
        path,
        "btc_usdt",
        "minute15",
        generated_at=datetime(2026, 8, 8, 13, 0, tzinfo=timezone.utc),
    )

    assert first["generated_at"] != second["generated_at"]
    assert first["reconciliation_sha256"] == second["reconciliation_sha256"]
    assert first["input"]["sha256"] == second["input"]["sha256"]
