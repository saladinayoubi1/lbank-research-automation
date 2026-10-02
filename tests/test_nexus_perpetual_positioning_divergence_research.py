from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import nexus_perpetual_positioning_divergence_research as a9


def make_spot(root):
    index = pd.date_range("2026-07-03T00:00:00Z", periods=30 * 96, freq="15min")
    for j, symbol in enumerate(a9.SPOT_SYMBOLS):
        base = 100.0 + 50.0 * j
        wave = np.sin(np.arange(len(index)) / 13.0) * 0.2
        close = base + np.arange(len(index)) * 0.001 + wave
        open_ = close - 0.01
        high = np.maximum(open_, close) + 0.05
        low = np.minimum(open_, close) - 0.05
        frame = pd.DataFrame({
            "timestamp": index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 10.0,
            "symbol": symbol,
            "timeframe": "minute15",
        })
        folder = root / symbol
        folder.mkdir(parents=True)
        frame.to_parquet(folder / "minute15.parquet", index=False)


def make_positioning():
    index = pd.date_range("2026-07-03T00:00:00Z", periods=30 * 96, freq="15min")
    funding_index = pd.date_range(
        "2026-07-02T16:00:00Z", "2026-08-01T16:00:00Z", freq="8h"
    )
    result = {}
    for j, symbol in enumerate(a9.LINEAR_SYMBOLS):
        oi = 50_000.0 + j * 10_000.0 + np.arange(len(index)) * 2.0
        oi = oi + np.sin(np.arange(len(index)) / 9.0) * 50.0
        funding = np.where(
            np.arange(len(funding_index)) % 5 == 0,
            -0.0002,
            0.00005 + j * 0.00001,
        )
        result[symbol] = {
            "oi": pd.DataFrame({"timestamp": index, "open_interest": oi}),
            "funding": pd.DataFrame({
                "timestamp": funding_index,
                "funding_rate": funding,
            }),
        }
    return result


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def get(self, path, params):
        assert path == "/v5/market/open-interest"
        return {"result": {"list": self.rows}}


def test_fetch_open_interest_filters_inclusive_endpoint_and_requires_full_day():
    day = pd.Timestamp("2026-07-03T00:00:00Z")
    stamps = pd.date_range(day, day + pd.Timedelta(days=1), freq="15min")
    rows = [
        {"timestamp": str(int(ts.timestamp() * 1000)), "openInterest": "100.0"}
        for ts in reversed(stamps)
    ]
    out = a9.fetch_open_interest_15m(
        FakeClient(rows), "BTCUSDT", "2026-07-03", "2026-07-03"
    )
    assert len(out) == 96
    assert out["timestamp"].iloc[0] == day
    assert out["timestamp"].iloc[-1] == day + pd.Timedelta(hours=23, minutes=45)

    with pytest.raises(a9.PositioningResearchError, match="incomplete 15m OI day"):
        a9.fetch_open_interest_15m(
            FakeClient(rows[:-2]), "BTCUSDT", "2026-07-03", "2026-07-03"
        )
def test_prepare_symbol_lags_open_interest_one_full_bar(tmp_path):
    make_spot(tmp_path)
    data = make_positioning()
    raw = data["BTCUSDT"]["oi"]["open_interest"].copy()
    frame = a9.prepare_symbol(tmp_path, "btc_usdt", data["BTCUSDT"])
    assert pd.isna(frame["open_interest_observed"].iloc[0])
    assert frame["open_interest_observed"].iloc[1] == raw.iloc[0]
    assert frame["open_interest_observed"].iloc[10] == raw.iloc[9]


def test_training_thresholds_ignore_validation_and_test_mutations(tmp_path):
    make_spot(tmp_path)
    data = make_positioning()
    frame = a9.prepare_symbol(tmp_path, "btc_usdt", data["BTCUSDT"])
    cut = int(len(frame) * a9.TRAIN_FRAC)
    before = a9.training_thresholds(frame, cut)
    frame.loc[cut:, "funding_rate"] = -1.0
    frame.loc[cut:, "oi_growth_1h"] = 10.0
    after = a9.training_thresholds(frame, cut)
    assert before == after


def test_signal_requires_prior_positioning_divergence_and_current_closed_reclaim():
    frame = pd.DataFrame({
        "funding_rate": [0.0, -0.1, -0.1, -0.1],
        "oi_growth_1h": [0.0, 0.2, 0.2, 0.2],
        "price_return_1h": [0.0, -0.01, 0.01, 0.01],
        "open": [100.0, 100.0, 100.0, 100.0],
        "high": [100.5, 100.5, 101.0, 101.5],
        "close": [100.0, 100.0, 101.2, 101.6],
        "atr": [1.0, 1.0, 1.0, 1.0],
    })
    thresholds = {
        "funding_low_q25": -0.05,
        "funding_median": 0.0,
        "oi_growth_high_q75": 0.1,
    }
    signal = a9.build_signal(frame, thresholds)
    assert signal.tolist() == [False, False, True, False]
    frame.loc[3, "close"] = 1000.0
    assert a9.build_signal(frame, thresholds)[2]
def test_full_a9_evaluation_is_research_only_and_spot_execution_only(tmp_path):
    make_spot(tmp_path)
    data = make_positioning()
    report = a9.evaluate(
        tmp_path,
        data,
        "2026-07-03",
        "2026-08-01",
        "b" * 40,
        "c" * 64,
    )
    assert report["mechanism"] == "perpetual_positioning_divergence"
    assert report["research_only"] is True
    assert report["paper_only"] is True
    assert report["automatic_strategy_promotion"] is False
    assert report["derivative_execution_authority"] is False
    assert report["live_trading_authority"] is False
    assert report["qualification"] == "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
    assert len(report["rows"]) == 12
    assert all(row["execution_instrument"] == "spot_long_or_cash_only" for row in report["rows"])
    assert all(row["trade_count_limit"] is None for row in report["rows"])
    proof = report["positioning_proof"]
    assert proof["open_interest_availability_model"] == "one_completed_15m_interval_lag"
    assert proof["derivative_execution_authority"] is False
    assert proof["live_trading_authority"] is False