from __future__ import annotations

import pytest

from phase6_research_pipeline import bind_bybit_closed_dataset


START = 1_700_000_000_000
SEMANTICS = {
    "15": ("minute15", 900_000),
    "60": ("hour1", 3_600_000),
    "240": ("hour4", 14_400_000),
}


def _candles(symbol: str, interval: str):
    _timeframe, step = SEMANTICS[interval]
    return [
        {
            "source": "Bybit",
            "market_type": "spot",
            "symbol": symbol,
            "interval": interval,
            "closed": True,
            "open_time_ms": START,
            "open": "100",
            "high": "102",
            "low": "99",
            "close": "101",
            "volume": "1000",
        },
        {
            "source": "Bybit",
            "market_type": "spot",
            "symbol": symbol,
            "interval": interval,
            "closed": True,
            "open_time_ms": START + step,
            "open": "101",
            "high": "103",
            "low": "100",
            "close": "102",
            "volume": "1100",
        },
    ]


@pytest.mark.parametrize("canonical,source", [("SOL/USDT", "SOLUSDT"), ("XRP/USDT", "XRPUSDT")])
@pytest.mark.parametrize("interval", ["15", "60", "240"])
def test_new_pairs_bind_to_exact_bybit_primary_semantics(canonical: str, source: str, interval: str) -> None:
    timeframe, _step = SEMANTICS[interval]
    bound = bind_bybit_closed_dataset(
        _candles(source, interval),
        canonical_symbol=canonical,
        source_symbol=source,
        interval=interval,
    )
    assert bound["downstream_eligible"] is True
    assert bound["paper_only"] is True
    assert bound["source"] == "Bybit"
    assert bound["source_role"] == "primary"
    assert bound["instrument"] == canonical
    assert bound["market"] == "spot"
    assert bound["candidate_timeframe"] == timeframe
    assert bound["interval"] == interval
    assert bound["finality"] == "closed_only"


def test_new_pair_namespace_substitution_is_rejected() -> None:
    candles = _candles("SOLUSDT", "15")
    candles[0]["symbol"] = "XRPUSDT"
    with pytest.raises(Exception):
        bind_bybit_closed_dataset(
            candles,
            canonical_symbol="SOL/USDT",
            source_symbol="SOLUSDT",
            interval="15",
        )
