from __future__ import annotations

import requests

import sitecustomize


def _response(status: int) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://public.bybit.com/spot/BTCUSDT/"
    return response


def test_non_bybit_request_is_not_modified(monkeypatch):
    calls = []

    def original(session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _response(200)

    monkeypatch.setattr(sitecustomize, "_ORIGINAL_REQUEST", original)
    session = requests.Session()
    response = sitecustomize._request_with_resilience(
        session,
        "GET",
        "https://example.com/data",
        headers={"X-Test": "1"},
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert calls[0][2]["headers"] == {"X-Test": "1"}


def test_bybit_request_adds_headers_and_retries(monkeypatch):
    statuses = iter([403, 429, 200])
    calls = []
    sleeps = []

    def original(session, method, url, **kwargs):
        calls.append(kwargs)
        return _response(next(statuses))

    monkeypatch.setattr(sitecustomize, "_ORIGINAL_REQUEST", original)
    monkeypatch.setattr(sitecustomize.time, "sleep", sleeps.append)
    monkeypatch.setattr(sitecustomize.random, "uniform", lambda _a, _b: 0.0)

    response = sitecustomize._request_with_resilience(
        requests.Session(),
        "GET",
        "https://public.bybit.com/spot/BTCUSDT/",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]
    for call in calls:
        headers = call["headers"]
        assert headers["Accept"] == "application/json"
        assert headers["User-Agent"].startswith("Mozilla/5.0")
        assert headers["Referer"] == "https://public.bybit.com/"


def test_bybit_request_stops_after_six_attempts(monkeypatch):
    calls = []

    def original(session, method, url, **kwargs):
        calls.append(kwargs)
        return _response(403)

    monkeypatch.setattr(sitecustomize, "_ORIGINAL_REQUEST", original)
    monkeypatch.setattr(sitecustomize.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(sitecustomize.random, "uniform", lambda _a, _b: 0.0)

    response = sitecustomize._request_with_resilience(
        requests.Session(),
        "GET",
        "https://public.bybit.com/spot/BTCUSDT/BTCUSDT-2024-06.csv.gz",
    )

    assert response.status_code == 403
    assert len(calls) == 6


def test_install_is_idempotent(monkeypatch):
    monkeypatch.setattr(sitecustomize, "_INSTALLED", False)
    original = requests.sessions.Session.request

    sitecustomize.install()
    first = requests.sessions.Session.request
    sitecustomize.install()
    second = requests.sessions.Session.request

    assert first is sitecustomize._request_with_resilience
    assert second is first
    monkeypatch.setattr(requests.sessions.Session, "request", original)
