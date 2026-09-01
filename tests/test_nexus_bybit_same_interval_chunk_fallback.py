from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_bybit_same_interval_chunk_fallback as fallback
from bybit_public_klines import BybitKlineError, INTERVAL_MS


STEP = INTERVAL_MS["240"]
TERMINAL = (
    "all approved Bybit Mainnet endpoints were unavailable or geographically rejected: "
    "https://api.bybit.eu:http403:unclassified,"
    "https://api.bybit.com:http403:unclassified,"
    "https://api.bytick.com:http403:unclassified"
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


def _exact_kwargs() -> dict[str, object]:
    return {
        "canonical_symbol": "ETH/USDT",
        "source_symbol": "ETHUSDT",
        "interval": "240",
        "now_ms": 241 * STEP,
        "start_time_ms": 0,
        "end_time_ms": 239 * STEP,
        "limit": 240,
    }


def _end_sentinel() -> dict[str, object]:
    return {
        "binding_sha256": "e" * 64,
        "source": "Bybit",
        "source_role": "primary",
        "market": "spot",
    }


def test_direct_success_remains_authoritative(monkeypatch):
    sentinel = {"binding_sha256": "a" * 64, "source": "Bybit"}
    monkeypatch.setattr(fallback, "_fetch_bind_direct", lambda **_: deepcopy(sentinel))
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("chunk fallback must not run after direct success"),
    )
    monkeypatch.setattr(
        fallback,
        "_fetch_end_anchored_dataset",
        lambda **kwargs: pytest.fail("request-shape fallback must not run after direct success"),
    )
    assert fallback.fetch_bind_bybit_dataset(**_exact_kwargs()) == sentinel


def test_exact_eth_4h_unclassified_403_uses_four_same_interval_chunks(monkeypatch, capsys):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    calls = []

    def fetch(symbol, interval, **kwargs):
        calls.append((symbol, interval, dict(kwargs)))
        assert interval == "240"
        return _rows(symbol, kwargs["start_time_ms"], kwargs["end_time_ms"])

    monkeypatch.setattr(fallback, "fetch_closed_klines", fetch)
    monkeypatch.setattr(
        fallback,
        "_fetch_end_anchored_dataset",
        lambda **kwargs: pytest.fail("end-anchored fallback is second stage, not first stage"),
    )
    result = fallback.fetch_bind_bybit_dataset(**_exact_kwargs())

    assert result["source"] == "Bybit"
    assert result["source_role"] == "primary"
    assert result["market"] == "spot"
    assert result["interval"] == "240"
    assert result["manifest_timeframe"] == "4h"
    assert result["row_count"] == 240
    assert result["endpoint_contract"].endswith("symbol=ETHUSDT&interval=240")
    assert len(calls) == 4
    assert [call[2]["limit"] for call in calls] == [60, 60, 60, 60]
    assert all(call[0] == "ETHUSDT" and call[1] == "240" for call in calls)
    assert calls[0][2]["start_time_ms"] == 0
    assert calls[-1][2]["end_time_ms"] == 239 * STEP
    output = capsys.readouterr().out
    assert '"semantic_substitution":false' in output
    assert '"chunk_count":4' in output
    assert '"trigger":"all_approved_hosts_unclassified_http403"' in output


def test_eth_4h_chunk_terminal_can_enter_end_anchored_second_stage(monkeypatch):
    sentinel = _end_sentinel()
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: (_ for _ in ()).throw(BybitKlineError(TERMINAL)),
    )
    calls = []

    def end_anchored(**kwargs):
        calls.append(dict(kwargs))
        return deepcopy(sentinel)

    monkeypatch.setattr(fallback, "_fetch_end_anchored_dataset", end_anchored)
    assert fallback.fetch_bind_bybit_dataset(**_exact_kwargs()) == sentinel
    assert len(calls) == 1
    assert calls[0]["source_symbol"] == "ETHUSDT"
    assert calls[0]["interval"] == "240"
    assert calls[0]["limit"] == 240


def test_classified_access_failure_never_enters_fallbacks(monkeypatch):
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
    monkeypatch.setattr(
        fallback,
        "_fetch_end_anchored_dataset",
        lambda **kwargs: pytest.fail("classified access failure must not change request shape"),
    )
    with pytest.raises(BybitKlineError, match="region_restricted"):
        fallback.fetch_bind_bybit_dataset(**_exact_kwargs())


def test_mixed_transport_terminal_never_enters_fallbacks(monkeypatch):
    mixed = (
        "all approved Bybit Mainnet endpoints were unavailable or geographically rejected: "
        "https://api.bybit.eu:http403:unclassified,"
        "https://api.bybit.com:transport:Timeout"
    )
    monkeypatch.setattr(
        fallback,
        "_fetch_bind_direct",
        lambda **_: (_ for _ in ()).throw(BybitKlineError(mixed)),
    )
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("mixed transport failure must remain fail-closed"),
    )
    monkeypatch.setattr(
        fallback,
        "_fetch_end_anchored_dataset",
        lambda **kwargs: pytest.fail("mixed transport failure must not change request shape"),
    )
    with pytest.raises(BybitKlineError, match="all approved Bybit Mainnet endpoints"):
        fallback.fetch_bind_bybit_dataset(**_exact_kwargs())


@pytest.mark.parametrize(
    ("canonical_symbol", "source_symbol", "interval"),
    [
        ("BTC/USDT", "BTCUSDT", "15"),
        ("BTC/USDT", "BTCUSDT", "60"),
        ("BTC/USDT", "BTCUSDT", "240"),
        ("ETH/USDT", "ETHUSDT", "15"),
        ("ETH/USDT", "ETHUSDT", "60"),
    ],
)
def test_other_canonical_matrix_cells_use_end_anchored_shape_only_after_terminal_403(
    monkeypatch, canonical_symbol, source_symbol, interval
):
    sentinel = _end_sentinel()
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("non-ETH4 cells must not enter the chunk path"),
    )
    calls = []

    def end_anchored(**kwargs):
        calls.append(dict(kwargs))
        return deepcopy(sentinel)

    monkeypatch.setattr(fallback, "_fetch_end_anchored_dataset", end_anchored)
    step = INTERVAL_MS[interval]
    kwargs = {
        "canonical_symbol": canonical_symbol,
        "source_symbol": source_symbol,
        "interval": interval,
        "now_ms": 241 * step,
        "start_time_ms": 0,
        "end_time_ms": 239 * step,
        "limit": 240,
    }
    assert fallback.fetch_bind_bybit_dataset(**kwargs) == sentinel
    assert len(calls) == 1
    assert calls[0]["canonical_symbol"] == canonical_symbol
    assert calls[0]["source_symbol"] == source_symbol
    assert calls[0]["interval"] == interval
    assert calls[0]["limit"] == 240


def test_non_240_history_surface_never_uses_fallback(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("non-current history surface must not enter fallback"),
    )
    monkeypatch.setattr(
        fallback,
        "_fetch_end_anchored_dataset",
        lambda **kwargs: pytest.fail("non-240 surface must not change request shape"),
    )
    kwargs = _exact_kwargs()
    kwargs.update(end_time_ms=119 * STEP, limit=120, now_ms=121 * STEP)
    with pytest.raises(BybitKlineError, match="all approved Bybit Mainnet endpoints"):
        fallback.fetch_bind_bybit_dataset(**kwargs)


def test_chunk_fallback_rejects_incomplete_subwindow(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)

    def incomplete(symbol, interval, **kwargs):
        return _rows(symbol, kwargs["start_time_ms"], kwargs["end_time_ms"])[1:]

    monkeypatch.setattr(fallback, "fetch_closed_klines", incomplete)
    with pytest.raises(BybitKlineError, match="chunk response is incomplete"):
        fallback.fetch_bind_bybit_dataset(**_exact_kwargs())


def test_chunk_fallback_rejects_semantic_substitution(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)

    def substituted(symbol, interval, **kwargs):
        rows = _rows(symbol, kwargs["start_time_ms"], kwargs["end_time_ms"])
        if kwargs["start_time_ms"] == 0:
            rows[0]["interval"] = "60"
        return rows

    monkeypatch.setattr(fallback, "fetch_closed_klines", substituted)
    with pytest.raises(BybitKlineError, match="changed canonical Bybit semantics"):
        fallback.fetch_bind_bybit_dataset(**_exact_kwargs())


def test_chunk_fallback_rejects_stitch_gap_even_with_full_chunk_lengths(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)

    def shifted(symbol, interval, **kwargs):
        rows = _rows(symbol, kwargs["start_time_ms"], kwargs["end_time_ms"])
        if kwargs["start_time_ms"] == 60 * STEP:
            rows[0]["open_time_ms"] += STEP
        return rows

    monkeypatch.setattr(fallback, "fetch_closed_klines", shifted)
    with pytest.raises(BybitKlineError, match="stitch is incomplete or off-grid"):
        fallback.fetch_bind_bybit_dataset(**_exact_kwargs())


def test_chunk_fallback_rejects_off_grid_window_before_network(monkeypatch):
    monkeypatch.setattr(fallback, "_fetch_bind_direct", _direct_terminal)
    monkeypatch.setattr(
        fallback,
        "fetch_closed_klines",
        lambda *args, **kwargs: pytest.fail("off-grid fallback must fail before network access"),
    )
    kwargs = _exact_kwargs()
    kwargs.update(start_time_ms=1, end_time_ms=239 * STEP + 1)
    with pytest.raises(BybitKlineError, match="off the 4h UTC grid"):
        fallback.fetch_bind_bybit_dataset(**kwargs)


class _Response:
    status_code = 200
    content = b"{}"

    def __init__(self, payload):
        self._payload = payload
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return deepcopy(self._payload)


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, deepcopy(kwargs)))
        return _Response(self.payload)


def _raw_payload(interval: str, start: int, count: int) -> dict[str, object]:
    step = INTERVAL_MS[interval]
    rows = []
    for index in reversed(range(count)):
        stamp = start + index * step
        value = 100 + index
        rows.append(
            [
                str(stamp),
                str(value),
                str(value + 2),
                str(value - 1),
                str(value + 1),
                "10",
                str((value + 1) * 10),
            ]
        )
    return {"retCode": 0, "retMsg": "OK", "result": {"list": rows}}


def test_end_anchored_request_omits_only_start_and_revalidates_exact_surface(monkeypatch):
    interval = "15"
    step = INTERVAL_MS[interval]
    payload = _raw_payload(interval, 0, 240)
    session = _Session(payload)
    monkeypatch.setattr(
        fallback,
        "_active_mainnet_base_urls",
        lambda: ("GLOBAL", ("https://api.bybit.com",)),
    )

    rows = fallback._fetch_end_anchored_closed_klines(
        source_symbol="BTCUSDT",
        interval=interval,
        now_ms=241 * step,
        start_time_ms=0,
        end_time_ms=239 * step,
        limit=240,
        timeout_seconds=1.0,
        session=session,
    )

    assert len(rows) == 240
    assert [row["open_time_ms"] for row in rows] == list(range(0, 240 * step, step))
    assert len(session.calls) == 1
    url, request = session.calls[0]
    assert url == "https://api.bybit.com/v5/market/kline"
    assert request["params"] == {
        "category": "spot",
        "symbol": "BTCUSDT",
        "interval": "15",
        "end": 239 * step,
        "limit": 240,
    }
    assert "start" not in request["params"]
    assert request["allow_redirects"] is False


def test_end_anchored_response_cannot_smuggle_incomplete_history(monkeypatch):
    interval = "60"
    step = INTERVAL_MS[interval]
    session = _Session(_raw_payload(interval, step, 239))
    monkeypatch.setattr(
        fallback,
        "_active_mainnet_base_urls",
        lambda: ("GLOBAL", ("https://api.bybit.com",)),
    )
    with pytest.raises(BybitKlineError, match="outside requested bounds|incomplete or substituted"):
        fallback._fetch_end_anchored_closed_klines(
            source_symbol="ETHUSDT",
            interval=interval,
            now_ms=241 * step,
            start_time_ms=0,
            end_time_ms=239 * step,
            limit=240,
            timeout_seconds=1.0,
            session=session,
        )
