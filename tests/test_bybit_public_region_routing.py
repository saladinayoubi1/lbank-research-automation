from __future__ import annotations

import json

import pytest

import bybit_public_klines as bybit_klines
from bybit_public_klines import (
    BybitKlineError,
    OFFICIAL_MAINNET_BASE_URLS,
    OFFICIAL_REGIONAL_MAINNET_BASE_URLS,
    fetch_closed_klines,
)


def _payload():
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "spot",
            "list": [
                ["1710000900000", "101", "103", "100", "102", "10", "1020"],
                ["1710000000000", "100", "102", "99", "101", "12", "1212"],
            ],
        },
    }


class _Response:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.content = (
            b"{}" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        )
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls: list[str] = []
        self.requests: list[dict] = []
        self.closed = False

    def get(self, url, **kwargs):
        self.urls.append(url)
        self.requests.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def _fetch(session: _Session):
    return fetch_closed_klines(
        "BTCUSDT",
        "15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
        limit=2,
        session=session,
    )


def test_default_route_remains_global(monkeypatch):
    monkeypatch.delenv("NEXUS_BYBIT_PUBLIC_REGION", raising=False)
    monkeypatch.setenv("RUNNER_NAME", "unrecognized-runner")
    session = _Session([_Response(200, _payload())])

    result = _fetch(session)

    assert len(result) == 2
    assert session.urls == [OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline"]


def test_exact_physical_runner_hint_selects_official_eea_first(monkeypatch, capsys):
    monkeypatch.delenv("NEXUS_BYBIT_PUBLIC_REGION", raising=False)
    monkeypatch.setenv("RUNNER_NAME", "NEXUS-BYBIT-WSL")
    session = _Session([_Response(200, _payload())])

    result = _fetch(session)

    eea = OFFICIAL_REGIONAL_MAINNET_BASE_URLS["EEA"][0]
    assert len(result) == 2
    assert session.urls == [eea + "/v5/market/kline"]
    output = capsys.readouterr().out
    assert '"region":"EEA"' in output
    assert eea in output


def test_explicit_eea_selector_is_allowlisted_and_precedes_global(monkeypatch):
    monkeypatch.setenv("NEXUS_BYBIT_PUBLIC_REGION", "eea")
    monkeypatch.setenv("RUNNER_NAME", "some-other-runner")
    session = _Session([_Response(200, _payload())])

    _fetch(session)

    eea = OFFICIAL_REGIONAL_MAINNET_BASE_URLS["EEA"][0]
    assert session.urls == [eea + "/v5/market/kline"]


def test_unclassified_eea_403_falls_back_only_to_approved_global_hosts(monkeypatch):
    monkeypatch.setenv("NEXUS_BYBIT_PUBLIC_REGION", "EEA")
    session = _Session([
        _Response(403),
        _Response(200, _payload()),
    ])

    result = _fetch(session)

    eea = OFFICIAL_REGIONAL_MAINNET_BASE_URLS["EEA"][0]
    assert len(result) == 2
    assert session.urls == [
        eea + "/v5/market/kline",
        OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline",
    ]


def test_unknown_region_selector_fails_closed_before_network(monkeypatch):
    monkeypatch.setenv("NEXUS_BYBIT_PUBLIC_REGION", "https://attacker.invalid")
    session = _Session([_Response(200, _payload())])

    with pytest.raises(BybitKlineError, match="unsupported Bybit public region selector"):
        _fetch(session)

    assert session.urls == []


def test_request_helper_rejects_unapproved_mainnet_url():
    session = _Session([_Response(200, _payload())])

    with pytest.raises(BybitKlineError, match="unapproved Bybit Mainnet endpoint"):
        bybit_klines._request_one_official_mainnet_host(
            session,
            "https://attacker.invalid",
            symbol="BTCUSDT",
            interval="15",
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            timeout_seconds=1.0,
        )

    assert session.urls == []
