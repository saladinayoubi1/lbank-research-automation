from copy import deepcopy

import pytest

from data_intelligence import DataIntelligenceError, classify_canonical_regimes, replay_identical
from phase6_research_pipeline import bind_bybit_closed_dataset


START = 1_700_000_100_000
STEP = 900_000


def candles(count=60, *, slope="up"):
    rows = []
    for index in range(count):
        if slope == "up":
            price = 100 + index * 0.5
        elif slope == "down":
            price = 130 - index * 0.5
        else:
            price = 100 + (index % 2) * 0.2
        rows.append(
            {
                "source": "Bybit",
                "market_type": "spot",
                "symbol": "BTCUSDT",
                "interval": "15",
                "open_time_ms": START + index * STEP,
                "close_time_ms": START + (index + 1) * STEP - 1,
                "open": f"{price:.8f}",
                "high": f"{price * 1.003:.8f}",
                "low": f"{price * 0.997:.8f}",
                "close": f"{price:.8f}",
                "volume": "10",
                "turnover": f"{price * 10:.8f}",
                "closed": True,
            }
        )
    return rows


def dataset(rows=None):
    return bind_bybit_closed_dataset(
        rows or candles(),
        canonical_symbol="BTC/USDT",
        source_symbol="BTCUSDT",
        interval="15",
    )


def test_regime_evidence_is_versioned_bound_and_replay_deterministic():
    ds = dataset()
    first = classify_canonical_regimes(ds)
    second = classify_canonical_regimes(deepcopy(ds))
    assert replay_identical(first, second)
    assert first == second
    assert first["dataset_binding_sha256"] == ds["binding_sha256"]
    assert first["paper_only"] is True
    assert first["lookahead_control"] is True
    assert first["feature_version"].endswith(".v1")
    assert first["taxonomy_version"].endswith(".v1")
    assert len(first["evidence_sha256"]) == 64
    assert first["current_regime"] == first["records"][-1]


def test_directional_taxonomy_distinguishes_up_and_down_structure():
    up = classify_canonical_regimes(dataset(candles(slope="up")))
    down = classify_canonical_regimes(dataset(candles(slope="down")))
    assert up["current_regime"]["regime"] == "TREND_UP"
    assert "POSITIVE_20_BAR_STRUCTURE" in up["current_regime"]["reason_codes"]
    assert down["current_regime"]["regime"] == "TREND_DOWN"
    assert "NEGATIVE_20_BAR_STRUCTURE" in down["current_regime"]["reason_codes"]


def test_future_candle_cannot_change_prior_regime_records():
    original = candles()
    changed = deepcopy(original)
    changed[-1]["open"] = "250"
    changed[-1]["high"] = "260"
    changed[-1]["low"] = "240"
    changed[-1]["close"] = "250"
    changed[-1]["volume"] = "100"
    changed[-1]["turnover"] = "25000"
    first = classify_canonical_regimes(dataset(original))
    second = classify_canonical_regimes(dataset(changed))
    assert first["records"][:-1] == second["records"][:-1]
    assert first["records"][-1] != second["records"][-1]


def test_high_volatility_and_liquidity_reason_codes_are_explicit():
    rows = candles(slope="range")
    for index in range(35, len(rows)):
        price = 100 if index % 2 == 0 else 108
        rows[index]["open"] = str(price)
        rows[index]["high"] = str(price * 1.04)
        rows[index]["low"] = str(price * 0.96)
        rows[index]["close"] = str(price)
        rows[index]["volume"] = "1" if index == len(rows) - 1 else "10"
        rows[index]["turnover"] = str(price * float(rows[index]["volume"]))
    result = classify_canonical_regimes(dataset(rows))
    current = result["current_regime"]
    assert current["regime"] == "HIGH_VOLATILITY"
    assert "VOLATILITY_THRESHOLD" in current["reason_codes"]
    assert current["liquidity_state"] == "THIN"
    assert "THIN_LIQUIDITY" in current["reason_codes"]


def test_tampered_or_ineligible_dataset_is_rejected_before_features():
    ds = dataset()
    ds["binding_sha256"] = "0" * 64
    with pytest.raises(DataIntelligenceError, match="canonical dataset rejected"):
        classify_canonical_regimes(ds)


def test_too_short_dataset_fails_closed():
    with pytest.raises(DataIntelligenceError, match="at least 21"):
        classify_canonical_regimes(dataset(candles(20)))
