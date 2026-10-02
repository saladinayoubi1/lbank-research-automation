from __future__ import annotations

import numpy as np
import pandas as pd

import nexus_perpetual_positioning_divergence_research as a9


def _spot_frame() -> pd.DataFrame:
    index = pd.date_range(a9.START, a9.END_EXCLUSIVE, freq="15min", inclusive="left")
    x = np.arange(len(index), dtype=float)
    close = 100.0 + x * 0.002 + np.sin(x / 23.0) * 0.25
    open_ = close - 0.01
    return pd.DataFrame({
        "timestamp": index,
        "open": open_,
        "high": np.maximum(open_, close) + 0.08,
        "low": np.minimum(open_, close) - 0.08,
        "close": close,
        "volume": 10.0,
        "symbol": "btc_usdt",
        "timeframe": "minute15",
    })


def _positioning_inputs():
    history_start = a9.START - pd.Timedelta(days=1)
    oi_index = pd.date_range(history_start, a9.END_EXCLUSIVE, freq="15min", inclusive="left")
    x = np.arange(len(oi_index), dtype=float)
    oi = pd.DataFrame({
        "timestamp": oi_index,
        "open_interest": 1000.0 + x * 0.5 + np.sin(x / 31.0) * 5.0,
    })
    funding_index = pd.date_range(history_start, a9.END_EXCLUSIVE, freq="8h", inclusive="left")
    funding = pd.DataFrame({
        "timestamp": funding_index,
        "funding_rate": np.where(np.arange(len(funding_index)) % 3 == 0, -0.0003, -0.00005),
    })
    proof = {
        "symbol": "BTCUSDT",
        "funding_interval_minutes": 480,
        "funding_rows": len(funding),
        "expected_funding_rows": len(funding),
        "open_interest_rows": len(oi),
        "expected_open_interest_rows": len(oi),
        "funding_semantic_sha256": "a" * 64,
        "open_interest_semantic_sha256": "b" * 64,
    }
    return funding, oi, proof


def test_train_thresholds_ignore_validation_and_test_mutation():
    frame = pd.DataFrame({
        "funding_lagged": np.linspace(-0.001, 0.001, 1000),
        "oi_change_4h": np.linspace(0.001, 0.10, 1000),
    })
    before = a9.train_thresholds(frame, 600)
    frame.loc[600:, "funding_lagged"] = -99.0
    frame.loc[600:, "oi_change_4h"] = 99.0
    after = a9.train_thresholds(frame, 600)
    assert before == after
    assert before["funding_extreme_max"] <= 0.0
    assert before["oi_growth_min"] > 0.0


def test_signal_uses_prior_positioning_and_current_closed_spot_confirmation():
    frame = pd.DataFrame({
        "funding_lagged": [-0.001, -0.002, -0.001, -0.001],
        "oi_change_4h": [0.1, 0.3, 0.2, 0.1],
        "price_return_4h_lagged": [-0.01, -0.02, 0.01, 0.01],
        "open": [100.0, 100.0, 100.0, 100.0],
        "close": [100.0, 100.0, 101.0, 100.0],
        "prior_high_2h": [101.0, 101.0, 100.5, 101.5],
        "atr": [1.0, 1.0, 1.0, 1.0],
    })
    sig = a9.build_signal(frame, {"funding_extreme_max": -0.0015, "oi_growth_min": 0.2})
    assert sig.tolist() == [False, False, True, False]
    frame.loc[3, "funding_lagged"] = -99.0
    assert a9.build_signal(frame, {"funding_extreme_max": -0.0015, "oi_growth_min": 0.2})[2]


def test_simulator_fills_entry_no_earlier_than_next_open():
    frame = pd.DataFrame({
        "open": [100.0, 200.0, 200.0],
        "high": [101.0, 201.0, 201.0],
        "low": [99.0, 198.0, 199.0],
        "close": [100.0, 200.0, 200.0],
        "atr": [1.0, 1.0, 1.0],
        "funding_lagged": [-0.001, -0.001, 0.001],
        "oi_change_4h": [0.2, 0.2, -0.1],
    })
    result = a9.simulate(
        frame, np.array([True, False, False]), fee_bps=0.0, slip_bps=0.0
    )
    assert result["closed_trades"] == 1
    assert result["ending_cash_usdt"] < 10_000.0
    assert result["derivative_execution"] is False
    assert result["spot_long_flat_only"] is True


def test_full_run_is_research_only_and_source_bound(tmp_path, monkeypatch):
    for symbol in a9.SYMBOLS:
        folder = tmp_path / symbol
        folder.mkdir(parents=True)
        frame = _spot_frame()
        frame["symbol"] = symbol
        frame.to_parquet(folder / "minute15.parquet", index=False)

    funding, oi, proof = _positioning_inputs()

    def fake_fetch(_client, linear_symbol):
        return funding.copy(), oi.copy(), {**proof, "symbol": linear_symbol}

    monkeypatch.setattr(a9, "fetch_positioning", fake_fetch)
    report = a9.run(tmp_path, tmp_path / "out", "c" * 40)
    assert report["mechanism"] == "perpetual_positioning_divergence"
    assert report["research_only"] is True
    assert report["paper_only"] is True
    assert report["derivative_execution"] is False
    assert report["automatic_strategy_promotion"] is False
    assert report["live_trading_authority"] is False
    assert report["qualification"] == "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
    assert len(report["rows"]) == 12
    assert all(row["trade_count_limit"] is None for row in report["rows"])
    assert all(row["derivative_execution"] is False for row in report["rows"])
