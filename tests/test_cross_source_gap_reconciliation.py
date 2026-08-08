import pandas as pd

import cross_source_gap_reconciliation as recon


def _row(source, close, ts=1710000000000):
    return {
        "source": source,
        "market_type": "spot",
        "symbol": "BTCUSDT",
        "interval": "15",
        "open_time_ms": ts,
        "close_time_ms": ts + 900000 - 1,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
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


def test_eligible_only_when_primary_and_secondary_agree(monkeypatch):
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


def test_blocks_material_cross_source_disagreement(monkeypatch):
    monkeypatch.setattr(recon, "fetch_bybit", lambda *a, **k: [_row("Bybit", "100")])
    monkeypatch.setattr(recon, "fetch_binance", lambda *a, **k: [_row("Binance", "105")])
    candidate = recon.reconcile_one_timestamp(
        "btc_usdt",
        "minute15",
        pd.Timestamp(1710000000000, unit="ms", tz="UTC"),
        now_ms=1710002000000,
    )
    assert candidate.status == "blocked"
    assert candidate.reason == "cross_source_price_disagreement"


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
