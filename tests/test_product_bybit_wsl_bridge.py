from __future__ import annotations

import json
import subprocess

import pytest

from product_bybit_wsl_bridge import BybitPublicDisplayClient, WSLBybitBridgeError

NOW_MS = 1_800_000_000_000


def _payload(
    symbol: str = "ETHUSDT",
    mark: str = "2000.5",
    stamp: int = NOW_MS,
) -> dict:
    return {
        "retCode": 0,
        "time": stamp,
        "result": {
            "category": "linear",
            "list": [{"symbol": symbol, "markPrice": mark}],
        },
    }


def _orderbook_payload(
    symbol: str = "ETHUSDT",
    bid: str = "1999.0",
    ask: str = "2001.0",
    stamp: int = NOW_MS,
) -> dict:
    return {
        "retCode": 0,
        "time": stamp,
        "result": {
            "s": symbol,
            "b": [[bid, "2.0"]],
            "a": [[ask, "3.0"]],
            "ts": stamp,
        },
    }


class _Direct:
    bases = ["https://api.bytick.com", "https://api.bybit.com"]
    attempts = 2
    timeout = 4.0

    def __init__(self) -> None:
        self.calls = []

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        return _payload(params["symbol"])


def _is_ws(args) -> bool:
    return list(args[:6]) == ["wsl.exe", "-d", "Ubuntu", "--exec", "python3", "-"]


def test_windows_bridge_prefers_official_bybit_websocket_without_shell():
    direct = _Direct()
    calls = []

    def runner(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        assert _is_ws(args)
        assert "shell" not in kwargs
        assert kwargs["timeout"] == 18.0
        script = kwargs["input"]
        assert isinstance(script, bytes)
        assert b"stream.bybit.com" in script
        assert b"ETHUSDT" in script
        assert b"api_key" not in script.lower()
        return subprocess.CompletedProcess(
            args, 0, json.dumps(_payload()).encode("utf-8"), b""
        )

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=True,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
    )

    assert result["result"]["list"][0]["symbol"] == "ETHUSDT"
    assert client.last_transport == "bybit_official_wsl_websocket"
    assert client.last_price_basis == "mark_price"
    assert direct.calls == []
    assert len(calls) == 1


def test_websocket_failure_falls_back_to_fixed_official_bybit_rest_hosts():
    direct = _Direct()
    calls = []

    def runner(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        if _is_ws(args):
            return subprocess.CompletedProcess(args, 1, b"", b"ws failed")
        assert "shell" not in kwargs
        if "api.bytick.com" in args[-1]:
            return subprocess.CompletedProcess(args, 28, b"", b"timeout")
        return subprocess.CompletedProcess(
            args, 0, json.dumps(_payload()).encode("utf-8"), b""
        )

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=True,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
    )

    assert result["result"]["list"][0]["symbol"] == "ETHUSDT"
    assert client.last_transport == "bybit_official_wsl_public"
    assert client.last_price_basis == "mark_price"
    assert direct.calls == []
    assert len(calls) == 3
    rest_calls = calls[1:]
    assert rest_calls[0][0][-1] == "https://api.bytick.com/v5/market/tickers"
    assert rest_calls[1][0][-1] == "https://api.bybit.com/v5/market/tickers"
    for args, kwargs in rest_calls:
        assert args[:4] == ["wsl.exe", "-d", "Ubuntu", "--"]
        assert "--max-redirs" in args and "0" in args
        assert "--get" in args
        assert "category=linear" in args
        assert "symbol=ETHUSDT" in args
        assert all("&" not in arg for arg in args)
        assert kwargs["timeout"] == 7.0


def test_websocket_stale_then_rest_stale_uses_fresh_official_bybit_orderbook_midpoint():
    direct = _Direct()
    calls = []
    stale = NOW_MS - 10 * 60 * 1000

    def runner(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        if _is_ws(args):
            return subprocess.CompletedProcess(
                args, 0, json.dumps(_payload(stamp=stale)).encode("utf-8"), b""
            )
        if args[-1].endswith("/v5/market/tickers"):
            return subprocess.CompletedProcess(
                args, 0, json.dumps(_payload(stamp=stale)).encode("utf-8"), b""
            )
        assert args[-1].endswith("/v5/market/orderbook")
        return subprocess.CompletedProcess(
            args, 0, json.dumps(_orderbook_payload()).encode("utf-8"), b""
        )

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=True,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
    )

    assert float(result["result"]["list"][0]["markPrice"]) == pytest.approx(2000.0)
    assert result["time"] == NOW_MS
    assert client.last_transport == "bybit_official_wsl_orderbook_mid"
    assert client.last_price_basis == "orderbook_mid"
    assert direct.calls == []
    assert len(calls) == 4
    assert _is_ws(calls[0][0])
    assert calls[1][0][-1].endswith("/v5/market/tickers")
    assert calls[2][0][-1].endswith("/v5/market/tickers")
    assert calls[3][0][-1].endswith("/v5/market/orderbook")
    assert "limit=1" in calls[3][0]
    assert all(
        "lbank" not in call[0][-1].lower() and "bitget" not in call[0][-1].lower()
        for call in calls[1:]
    )


def test_bridge_rejects_unbounded_path_params_and_symbol_before_runner():
    direct = _Direct()
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("runner must not execute for invalid requests")

    client = BybitPublicDisplayClient(
        direct, runner=runner, windows=True, wsl_executable="wsl.exe"
    )

    with pytest.raises(WSLBybitBridgeError):
        client.get("/v5/order/create", {"category": "linear", "symbol": "ETHUSDT"})
    with pytest.raises(WSLBybitBridgeError):
        client.get("/v5/market/tickers", {"category": "linear", "symbol": "ETH;curl"})
    with pytest.raises(WSLBybitBridgeError):
        client.get(
            "/v5/market/tickers",
            {"category": "linear", "symbol": "ETHUSDT", "api_key": "forbidden"},
        )

    assert calls == []
    assert direct.calls == []


def test_bridge_rejects_malformed_public_payload_without_attribute_errors():
    direct = _Direct()

    def runner(args, **kwargs):
        malformed = {"retCode": 0, "time": NOW_MS, "result": []}
        return subprocess.CompletedProcess(
            args, 0, json.dumps(malformed).encode("utf-8"), b""
        )

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=True,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )
    with pytest.raises(WSLBybitBridgeError, match="WSL Bybit public price unavailable"):
        client.get(
            "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
        )
    assert direct.calls == []


def test_missing_wsl_infrastructure_falls_back_only_to_official_direct_client():
    direct = _Direct()

    def runner(*args, **kwargs):
        raise FileNotFoundError("wsl.exe")

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=True,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
    )

    assert result["retCode"] == 0
    assert direct.calls == [
        ("/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"})
    ]
    assert client.last_transport == "bybit_official_windows_public"
    assert client.last_price_basis == "mark_price"


def test_present_wsl_network_failure_fails_closed_without_direct_or_other_venue():
    direct = _Direct()
    calls = []

    def runner(args, **kwargs):
        calls.append(list(args))
        if _is_ws(args):
            return subprocess.CompletedProcess(args, 28, b"", b"timeout")
        assert "category=linear" in args
        assert "symbol=ETHUSDT" in args
        assert all("&" not in arg for arg in args)
        return subprocess.CompletedProcess(args, 28, b"", b"timeout")

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=True,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )

    with pytest.raises(WSLBybitBridgeError):
        client.get(
            "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
        )

    assert direct.calls == []
    assert len(calls) == 5
    assert _is_ws(calls[0])
    urls = [args[-1] for args in calls[1:]]
    assert all(
        url.startswith(("https://api.bytick.com/", "https://api.bybit.com/"))
        for url in urls
    )
    assert all("lbank" not in url.lower() and "bitget" not in url.lower() for url in urls)


def test_stale_websocket_ticker_rest_ticker_and_orderbook_fail_closed():
    direct = _Direct()
    stale = NOW_MS - 10 * 60 * 1000

    def runner(args, **kwargs):
        if _is_ws(args):
            payload = _payload(stamp=stale)
        else:
            payload = (
                _payload(stamp=stale)
                if args[-1].endswith("/v5/market/tickers")
                else _orderbook_payload(stamp=stale)
            )
        return subprocess.CompletedProcess(
            args, 0, json.dumps(payload).encode("utf-8"), b""
        )

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=True,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )
    with pytest.raises(WSLBybitBridgeError):
        client.get(
            "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
        )
    assert direct.calls == []


def test_non_windows_keeps_existing_official_direct_bybit_client():
    direct = _Direct()

    def runner(*args, **kwargs):
        raise AssertionError("WSL must not be used off Windows")

    client = BybitPublicDisplayClient(
        direct,
        runner=runner,
        windows=False,
        wsl_executable="wsl.exe",
        clock_ms=lambda: NOW_MS,
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"}
    )

    assert result["result"]["list"][0]["symbol"] == "BTCUSDT"
    assert direct.calls == [
        ("/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})
    ]
    assert client.last_transport == "bybit_official_public"
    assert client.last_price_basis == "mark_price"
