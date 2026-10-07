from __future__ import annotations

import json
import subprocess

import pytest

from product_bybit_wsl_bridge import BybitPublicDisplayClient, WSLBybitBridgeError


def _payload(symbol: str = "ETHUSDT", mark: str = "2000.5") -> dict:
    return {
        "retCode": 0,
        "time": 1_800_000_000_000,
        "result": {
            "category": "linear",
            "list": [{"symbol": symbol, "markPrice": mark}],
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


def test_windows_bridge_uses_fixed_official_bybit_hosts_without_shell():
    direct = _Direct()
    calls = []

    def runner(args, **kwargs):
        calls.append((list(args), dict(kwargs)))
        assert isinstance(args, list)
        assert "shell" not in kwargs
        if "api.bytick.com" in args[-1]:
            return subprocess.CompletedProcess(args, 28, b"", b"timeout")
        return subprocess.CompletedProcess(
            args, 0, json.dumps(_payload()).encode("utf-8"), b""
        )

    client = BybitPublicDisplayClient(
        direct, runner=runner, windows=True, wsl_executable="wsl.exe"
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
    )

    assert result["result"]["list"][0]["symbol"] == "ETHUSDT"
    assert client.last_transport == "bybit_official_wsl_public"
    assert direct.calls == []
    assert len(calls) == 2
    assert calls[0][0][-1].startswith(
        "https://api.bytick.com/v5/market/tickers?category=linear&symbol=ETHUSDT"
    )
    assert calls[1][0][-1].startswith(
        "https://api.bybit.com/v5/market/tickers?category=linear&symbol=ETHUSDT"
    )
    for args, kwargs in calls:
        assert args[:4] == ["wsl.exe", "-d", "Ubuntu", "--"]
        assert "--max-redirs" in args and "0" in args
        assert kwargs["timeout"] == 7.0


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


def test_missing_wsl_infrastructure_falls_back_only_to_official_direct_client():
    direct = _Direct()

    def runner(*args, **kwargs):
        raise FileNotFoundError("wsl.exe")

    client = BybitPublicDisplayClient(
        direct, runner=runner, windows=True, wsl_executable="wsl.exe"
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
    )

    assert result["retCode"] == 0
    assert direct.calls == [
        ("/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"})
    ]
    assert client.last_transport == "bybit_official_windows_public"


def test_present_wsl_network_failure_fails_closed_without_direct_or_other_venue():
    direct = _Direct()
    urls = []

    def runner(args, **kwargs):
        urls.append(args[-1])
        return subprocess.CompletedProcess(args, 28, b"", b"timeout")

    client = BybitPublicDisplayClient(
        direct, runner=runner, windows=True, wsl_executable="wsl.exe"
    )

    with pytest.raises(WSLBybitBridgeError):
        client.get(
            "/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"}
        )

    assert direct.calls == []
    assert len(urls) == 2
    assert all(
        url.startswith(("https://api.bytick.com/", "https://api.bybit.com/"))
        for url in urls
    )
    assert all("lbank" not in url.lower() and "bitget" not in url.lower() for url in urls)


def test_non_windows_keeps_existing_official_direct_bybit_client():
    direct = _Direct()

    def runner(*args, **kwargs):
        raise AssertionError("WSL must not be used off Windows")

    client = BybitPublicDisplayClient(
        direct, runner=runner, windows=False, wsl_executable="wsl.exe"
    )
    result = client.get(
        "/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"}
    )

    assert result["result"]["list"][0]["symbol"] == "BTCUSDT"
    assert direct.calls == [
        ("/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})
    ]
    assert client.last_transport == "bybit_official_public"
