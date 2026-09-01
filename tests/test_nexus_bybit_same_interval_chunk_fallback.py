from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_bybit_same_interval_chunk_fallback as fallback
from bybit_public_klines import BybitKlineError, INTERVAL_MS


STEP = INTERVAL_MS["240"]
TERMINAL = (
    "all approved Bybit Mainnet endpoints were unavailable or geographically rejected"
    ": https://api.bybit.eu:http403:unclassified"
)


def _candle(symbol: str, open_time_ms: int) -> dict[str, object]:
    value = 100 + open_time_ms // STEP
    return {
        "source": "Bybit",
        "market_type": "spot",
        "symbol": symbol,
        "interval": "240",
        "open_time_ms": open_time_ms,
        "close_time_ms": open_time_ms + STEP - 1,
        "open": str(value),
        "high": str(value + 2),
        "low": str(value - 1),
        "close": str(value + 1),
        "volume": "10",
        "turnover": str((value + 1) * 10),
        "closed": True,
    }


def _rows(symbol: str, start: int, end: int) -> list[dict[str, object]]:
    return [_candle(symbol, stamp) for stamp in range(start, end + 1, STEP)]


def _direct_terminal(**_):
    raise BybitKlineError(TERMINAL)


def test_direct_success_remains_authoritative(monkeypatch):
    sentinel = {"binding_sha256": "a" * 64, "source": "Bybit"}
    monkeypatch.setattr(fallback, "_fetch_bind_direct", lambda **_: deepcopy(sentinel))
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("chunk fallback must not run after direct success"),
    )

    result = fallback.fetch_bind_bybit_dataset(
        canonical_symbol="ETH/USDT",
        source_symbol="ETHUSDT",
        interval="240",
        now_ms=241 * STEP,
        start_time_ms=0,
        end_time_ms=239 * STEP,
        limit=240,
    )
    assert result == sentinel


def test_terminal_4h_failure_retries_only_same_interval_in_four_bounded_chunks(
    monkeypatch, capsys
):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    calls = []

    def fetch(symbol, interval, **kwargs):
        calls.append((symbol, interval, dict(kwargs)))
        assert interval == "240"
        return _rows(symbol, kwargs["start_time_ms"], kwargs["end_time_ms"])

    monkeypatch.setattr(fallback, "fetch_closed_klines", fetch)
    result = fallback.fetch_bind_bybit_dataset(
        canonical_symbol="ETH/USDT",
        source_symbol="ETHUSDT",
        interval="240",
        now_ms=241 * STEP,
        start_time_ms=0,
        end_time_ms=239 * STEP,
        limit=240,
    )

    assert result["source"] == "Bybit"
    assert result["source_role"] == "primary"
    assert result["market"] == "spot"
    assert result["interval"] == "240"
    assert result["manifest_timeframe"] == "4h"
    assert result["row_count"] == 240
    assert result["endpoint_contract"].endswith("symbol=ETHUSDT&interval=240")
    assert len(calls) == 4
    assert [call[2]["limit"] for call in calls] == [60, 60, 60, 60]
    assert all(call[1] == "240" for call in calls)
    assert calls[0][2]["start_time_ms"] == 0
    assert calls[-1][2]["end_time_ms"] == 239 * STEP
    output = capsys.readouterr().out
    assert '"semantic_substitution":false' in output
    assert '"chunk_count":4' in output
    assert '"interval":"240"' in output


def test_classified_access_failure_never_enters_chunk_fallback(monkeypatch):
    def classified(**_):
        raise BybitKlineError(
            "Bybit Mainnet access is blocked (HTTP 403 region_restricted); repeated requests suppressed"
        )

    monkeypatch.setattr(fallback, "_fetch_bind_direct", classified)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("classified access failure must remain fail-fast"),
    )
    with pytest.raises(BybitKlineError, match="region_restricted"):
        fallback.fetch_bind_bybit_dataset(
            canonical_symbol="ETH/USDT",
            source_symbol="ETHUSDT",
            interval="240",
            now_ms=241 * STEP,
            start_time_ms=0,
            end_time_ms=239 * STEP,
            limit=240,
        )


def test_non_4h_terminal_failure_never_uses_fallback(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("fallback must be restricted to interval 240"),
    )
    with pytest.raises(BybitKlineError, match="all approved Bybit Mainnet endpoints"):
        fallback.fetch_bind_bybit_dataset(
            canonical_symbol="ETH/USDT",
            source_symbol="ETHUSDT",
            interval="60",
            now_ms=241 * STEP,
            start_time_ms=0,
            end_time_ms=59 * STEP,
            limit=60,
        )


def test_chunk_fallback_rejects_incomplete_subwindow(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)

    def incomplete(symbol, interval, **kwargs):
        rows = _rows(symbol, kwargs["start_time_ms"], kwargs["end_time_ms"])
        return rows[:-1]

    monkeypatch.setattr(fallback, "fetch_closed_klines", incomplete)
    with pytest.raises(BybitKlineError, match="chunk response is incomplete"):
        fallback.fetch_bind_bybit_dataset(
            canonical_symbol="ETH/USDT",
            source_symbol="ETHUSDT",
            interval="240",
            now_ms=121 * STEP,
            start_time_ms=0,
            end_time_ms=119 * STEP,
            limit=120,
        )


def test_chunk_fallback_rejects_semantic_substitution(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)

    def substituted(symbol, interval, **kwargs):
        rows = _rows(symbol, kwargs["start_time_ms"], kwargs["end_time_ms"])
        rows[0]["interval"] = "60"
        return rows

    monkeypatch.setattr(fallback, "fetch_closed_klines", substituted)
    with pytest.raises(BybitKlineError, match="changed canonical Bybit semantics"):
        fallback.fetch_bind_bybit_dataset(
            canonical_symbol="ETH/USDT",
            source_symbol="ETHUSDT",
            interval="240",
            now_ms=121 * STEP,
            start_time_ms=0,
            end_time_ms=119 * STEP,
            limit=120,
        )


def test_chunk_fallback_refuses_history_surface_above_current_240_candle_contract(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("over-broad fallback must fail before network access"),
    )
    with pytest.raises(BybitKlineError, match="exceeds bounded 4h history surface"):
        fallback.fetch_bind_bybit_dataset(
            canonical_symbol="ETH/USDT",
            source_symbol="ETHUSDT",
            interval="240",
            now_ms=242 * STEP,
            start_time_ms=0,
            end_time_ms=240 * STEP,
            limit=241,
        )


def test_chunk_fallback_rejects_off_grid_window_before_network(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("off-grid fallback must fail before network access"),
    )
    with pytest.raises(BybitKlineError, match="off the 4h UTC grid"):
        fallback.fetch_bind_bybit_dataset(
            canonical_symbol="ETH/USDT",
            source_symbol="ETHUSDT",
            interval="240",
            now_ms=122 * STEP,
            start_time_ms=1,
            end_time_ms=120 * STEP + 1,
            limit=121,
        )
