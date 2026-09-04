from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_bybit_same_interval_chunk_fallback as fallback
from bybit_public_klines import BybitKlineError, INTERVAL_MS


TERMINAL = (
    "all approved Bybit Mainnet endpoints were unavailable or geographically rejected: "
    "https://api.bybit.eu:http403:unclassified,"
    "https://api.bybit.com:http403:unclassified,"
    "https://api.bytick.com:http403:unclassified"
)


def _direct_terminal(**_):
    raise BybitKlineError(TERMINAL)


def _sentinel(symbol: str, interval: str) -> dict[str, object]:
    return {
        "binding_sha256": "d" * 64,
        "source": "Bybit",
        "source_role": "primary",
        "market": "spot",
        "source_symbol": symbol,
        "interval": interval,
    }


@pytest.mark.parametrize(
    ("canonical_symbol", "source_symbol"),
    [
        ("SOL/USDT", "SOLUSDT"),
        ("XRP/USDT", "XRPUSDT"),
    ],
)
@pytest.mark.parametrize("interval", ["15", "60", "240"])
def test_new_multipair_cells_use_only_same_bybit_end_anchored_shape_after_terminal_403(
    monkeypatch, canonical_symbol, source_symbol, interval
):
    sentinel = _sentinel(source_symbol, interval)
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail(
            "SOL/XRP cells must not enter the legacy ETH-only chunk path"
        ),
    )
    calls: list[dict[str, object]] = []

    def end_anchored(**kwargs):
        calls.append(dict(kwargs))
        return deepcopy(sentinel)

    monkeypatch.setattr(fallback, "_fetch_end_anchored_dataset", end_anchored)
    step = INTERVAL_MS[interval]
    result = fallback.fetch_bind_bybit_dataset(
        canonical_symbol=canonical_symbol,
        source_symbol=source_symbol,
        interval=interval,
        now_ms=241 * step,
        start_time_ms=0,
        end_time_ms=239 * step,
        limit=240,
    )

    assert result == sentinel
    assert calls == [
        {
            "canonical_symbol": canonical_symbol,
            "source_symbol": source_symbol,
            "interval": interval,
            "now_ms": 241 * step,
            "start_time_ms": 0,
            "end_time_ms": 239 * step,
            "limit": 240,
            "timeout_seconds": 30.0,
        }
    ]


def test_same_bybit_fallback_surface_is_exact_four_symbol_contract() -> None:
    assert fallback._CANONICAL_SURFACE == {
        ("BTC/USDT", "BTCUSDT"),
        ("ETH/USDT", "ETHUSDT"),
        ("SOL/USDT", "SOLUSDT"),
        ("XRP/USDT", "XRPUSDT"),
    }
    assert fallback._REQUEST_SHAPE_INTERVALS == frozenset({"15", "60", "240"})


@pytest.mark.parametrize(
    ("canonical_symbol", "source_symbol"),
    [
        ("SOL/USDT", "XRPUSDT"),
        ("XRP/USDT", "SOLUSDT"),
        ("DOGE/USDT", "DOGEUSDT"),
    ],
)
def test_unknown_or_cross_wired_pair_remains_fail_closed(
    monkeypatch, canonical_symbol, source_symbol
):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "_fetch_end_anchored_dataset",
        lambda **kwargs: pytest.fail("untrusted pair must not enter fallback"),
    )
    step = INTERVAL_MS["60"]
    with pytest.raises(BybitKlineError, match="all approved Bybit Mainnet endpoints"):
        fallback.fetch_bind_bybit_dataset(
            canonical_symbol=canonical_symbol,
            source_symbol=source_symbol,
            interval="60",
            now_ms=241 * step,
            start_time_ms=0,
            end_time_ms=239 * step,
            limit=240,
        )
