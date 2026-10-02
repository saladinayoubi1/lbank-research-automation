from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import nexus_perpetual_positioning_divergence_research as a9


def write_spot(root, symbol="btc_usdt"):
    index = pd.date_range(a9.START, a9.END_EXCLUSIVE, freq="15min", inclusive="left")
    close = 100.0 + np.arange(len(index)) * 0.001 + np.sin(np.arange(len(index)) / 17.0) * 0.2
    frame = pd.DataFrame(
        {
            "timestamp": index,
            "open": close - 0.01,
            "high": close + 0.05,
            "low": close - 0.06,
            "close": close,
            "volume": 10.0,
            "symbol": symbol,
            "timeframe": "minute15",
        }
    )
    path = root / "bybit_market" / symbol
    path.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path / "minute15.parquet", index=False)
    return frame


def positioning():
    oi_index = pd.date_range(a9.START, a9.END_EXCLUSIVE, freq="1h", inclusive="left")
    funding_index = pd.date_range(a9.START, a9.END_EXCLUSIVE, freq="8h", inclusive="left")
    oi = pd.DataFrame(
        {
            "timestamp": oi_index,
            "single_open_interest": 50_000.0 + np.arange(len(oi_index)) * 3.0,
            "bilateral_open_interest": 100_000.0 + np.arange(len(oi_index)) * 6.0,
            "available_at": oi_index + pd.Timedelta(hours=1),
            "symbol": "BTCUSDT",
            "oi_methodology": "post_2026_06_11_single_sided",
        }
    )
    funding = pd.DataFrame(
        {
            "timestamp": funding_index,
            "funding_rate": np.where(np.arange(len(funding_index)) % 5 == 0, -0.0002, 0.00005),
            "available_at": funding_index,
            "symbol": "BTCUSDT",
        }
    )
    return {"oi": oi, "funding": funding}


def prepared_frame():
    index = pd.date_range(a9.START, a9.END_EXCLUSIVE, freq="15min", inclusive="left")
    x = np.arange(len(index))
    close = 100.0 + x * 0.001 + np.sin(x / 11.0) * 0.3
    funding = np.where(x % 160 < 40, -0.0002, 0.00005)
    oi_growth = 0.002 + np.sin(x / 23.0) * 0.003
    frame = pd.DataFrame(
        {
            "timestamp": index,
            "decision_at": index + pd.Timedelta(minutes=15),
            "open": close - 0.01,
            "high": close + 0.05,
            "low": close - 0.06,
            "close": close,
            "volume": 10.0,
            "atr": 0.11,
            "funding_rate": funding,
            "oi_growth_4h": oi_growth,
            "price_return_4h": pd.Series(close).pct_change(16).fillna(0.0),
        }
    )
    return frame


def test_a9_has_no_independent_derivatives_fetch_path():
    text = open(a9.__file__, encoding="utf-8").read()
    assert "Client(" not in text
    assert "/v5/market/open-interest" not in text
    assert "fetch_open_interest_15m" not in text
    assert a9.EXPECTED_POSITIONING_DIGEST == (
        "a59405c733ecc6cad5c9270155a22bab52173989cd62c9569cf37b06f844c6e6"
    )


def test_verified_positioning_rejects_different_source_contract(tmp_path, monkeypatch):
    proof = {
        "dataset_semantic_sha256": "0" * 64,
        "oi_interval": "15min",
        "oi_value_field": "openInterest",
        "oi_methodology": "legacy",
        "start_utc": a9.START.isoformat(),
        "end_exclusive_utc": a9.END_EXCLUSIVE.isoformat(),
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "research_only": True,
        "paper_only": True,
        "derivatives_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "credentials_used": False,
    }
    (tmp_path / "_perpetual_positioning_proof.json").write_text(json.dumps(proof))
    monkeypatch.setattr(a9, "verify_positioning_proof", lambda value: None)
    with pytest.raises(a9.PositioningResearchError, match="accepted A9 source contract"):
        a9.load_verified_positioning(tmp_path)


def test_prepare_symbol_waits_for_completed_one_hour_oi(tmp_path):
    write_spot(tmp_path)
    frame = a9.prepare_symbol(tmp_path, "btc_usdt", positioning())
    assert pd.isna(frame["open_interest_observed"].iloc[2])
    assert frame["decision_at"].iloc[3] == pd.Timestamp("2026-07-03T01:00:00Z")
    assert frame["open_interest_observed"].iloc[3] == 50_000.0
    assert frame["oi_timestamp"].iloc[3] == pd.Timestamp("2026-07-03T00:00:00Z")
    assert frame["oi_available_at"].iloc[3] == pd.Timestamp("2026-07-03T01:00:00Z")
    assert frame["open_interest_observed"].iloc[7] == 50_003.0
    assert not (
        frame["oi_available_at"].dropna()
        > frame.loc[frame["oi_available_at"].notna(), "decision_at"]
    ).any()


def test_training_thresholds_ignore_validation_and_test_mutations(tmp_path):
    write_spot(tmp_path)
    frame = a9.prepare_symbol(tmp_path, "btc_usdt", positioning())
    cut = int(len(frame) * a9.TRAIN_FRAC)
    before = a9.training_thresholds(frame, cut)
    frame.loc[cut:, "funding_rate"] = -1.0
    frame.loc[cut:, "oi_growth_4h"] = 10.0
    after = a9.training_thresholds(frame, cut)
    assert before == after


def test_signal_requires_prior_divergence_then_closed_bar_reclaim():
    frame = pd.DataFrame(
        {
            "funding_rate": [0.0, -0.1, -0.1, -0.1],
            "oi_growth_4h": [0.0, 0.2, 0.2, 0.2],
            "price_return_4h": [0.0, -0.01, 0.01, 0.01],
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [100.5, 100.5, 101.0, 101.5],
            "close": [100.0, 100.0, 101.2, 101.6],
            "atr": [1.0, 1.0, 1.0, 1.0],
        }
    )
    threshold = {
        "funding_low_q25": -0.05,
        "funding_median": 0.0,
        "oi_growth_high_q75": 0.1,
    }
    assert a9.build_signal(frame, threshold).tolist() == [False, False, True, False]


def test_evaluate_is_research_only_spot_only_and_no_trade_cap(tmp_path, monkeypatch):
    (tmp_path / spot_backfill_name()).write_text("[]")
    fake_positioning = {
        "BTCUSDT": positioning(),
        "ETHUSDT": positioning(),
    }
    fake_proof = {
        "dataset_semantic_sha256": a9.EXPECTED_POSITIONING_DIGEST,
        "proof_sha256": "f" * 64,
        "oi_interval": "1h",
        "oi_value_field": "singleOpenInterest",
        "oi_methodology": "post_2026_06_11_single_sided",
    }
    monkeypatch.setattr(
        a9,
        "load_spot_proof",
        lambda root: {"snapshot_digest": "e" * 64},
    )
    monkeypatch.setattr(
        a9,
        "load_verified_positioning",
        lambda root: (fake_positioning, fake_proof),
    )
    raw = write_spot(tmp_path)
    monkeypatch.setattr(
        a9,
        "load_spot",
        lambda root, symbol: raw.assign(
            symbol=symbol,
            decision_at=raw["timestamp"] + pd.Timedelta(minutes=15),
        ),
    )
    monkeypatch.setattr(
        a9,
        "prepare_symbol",
        lambda root, symbol, data: prepared_frame(),
    )
    report = a9.evaluate(tmp_path, tmp_path, tmp_path, "b" * 40)
    assert report["mechanism"] == "perpetual_positioning_divergence"
    assert report["positioning_oi_interval"] == "1h"
    assert report["positioning_oi_value_field"] == "singleOpenInterest"
    assert report["historical_test_pristine"] is False
    assert report["independent_future_data_required"] is True
    assert report["research_only"] is True
    assert report["paper_only"] is True
    assert report["automatic_strategy_promotion"] is False
    assert report["derivative_execution_authority"] is False
    assert report["live_trading_authority"] is False
    assert report["qualification"] == "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
    assert len(report["rows"]) == 12
    assert all(row["execution_instrument"] == "spot_long_or_cash_only" for row in report["rows"])
    assert all(row["trade_count_limit"] is None for row in report["rows"])


def spot_backfill_name():
    return a9.spot_backfill.SOURCE_MANIFEST_NAME
