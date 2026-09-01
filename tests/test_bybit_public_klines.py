import json

import pytest

import bybit_public_klines as bybit_klines
from bybit_public_klines import (
    BybitKlineError,
    OFFICIAL_MAINNET_BASE_URLS,
    UNCLASSIFIED_403_RETRY_DELAYS_SECONDS,
    fetch_closed_klines,
    normalize_closed_klines,
)


def _payload(rows):
    return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "list": rows}}


def _rows():
    return [
        ["1710000900000", "101", "103", "100", "102", "10", "1020"],
        ["1710000000000", "100", "102", "99", "101", "12", "1212"],
    ]


class _Response:
    def __init__(self, status_code, payload=None, *, content=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        if content is None:
            content = b"{}" if payload is None else json.dumps(payload, separators=(",", ":")).encode()
        self.content = content
        self.headers = dict(headers or {})

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []
        self.requests = []
        self.closed = False

    def get(self, url, **kwargs):
        self.urls.append(url)
        self.requests.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)

    def close(self):
        self.closed = True


def test_normalizes_reverse_sorted_closed_window():
    result = normalize_closed_klines(
        _payload(_rows()),
        symbol="BTCUSDT",
        interval="15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
    )
    assert [row["open_time_ms"] for row in result] == [1710000000000, 1710000900000]
    assert all(row["source"] == "Bybit" and row["closed"] for row in result)


def test_rejects_incomplete_window():
    rows = [["1710000000000", "100", "102", "99", "101", "12", "1212"]]
    with pytest.raises(BybitKlineError, match="incomplete"):
        normalize_closed_klines(
            _payload(rows),
            symbol="BTCUSDT",
            interval="15",
            now_ms=1710003000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
        )


def test_rejects_open_candle():
    rows = [["1710000000000", "100", "102", "99", "101", "12", "1212"]]
    with pytest.raises(BybitKlineError, match="not a closed"):
        normalize_closed_klines(
            _payload(rows),
            symbol="BTCUSDT",
            interval="15",
            now_ms=1710000500000,
            start_time_ms=1710000000000,
            end_time_ms=1710000000000,
        )


def test_fetch_uses_primary_official_mainnet_host_when_available():
    session = _Session([_Response(200, _payload(_rows()))])
    result = fetch_closed_klines(
        "BTCUSDT",
        "15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
        limit=2,
        session=session,
    )
    assert len(result) == 2
    assert session.urls == [OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline"]
    request_id = session.requests[0]["headers"]["cdn-request-id"]
    assert request_id.startswith("nexus-") and len(request_id) == 38


def test_fetch_tries_second_official_host_after_unclassified_403(capsys):
    session = _Session([
        _Response(403, content=b"Forbidden", headers={"Server": "cloudflare", "Content-Type": "text/html"}),
        _Response(200, _payload(_rows())),
    ])
    result = fetch_closed_klines(
        "BTCUSDT",
        "15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
        limit=2,
        session=session,
    )
    assert len(result) == 2
    assert session.urls == [
        OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline",
        OFFICIAL_MAINNET_BASE_URLS[1] + "/v5/market/kline",
    ]
    line = capsys.readouterr().out.strip()
    prefix = "bybit_http403_diagnostic="
    assert line.startswith(prefix)
    diagnostic = json.loads(line[len(prefix):])
    assert diagnostic["classification"] == "unclassified"
    assert diagnostic["ret_code"] is None
    assert diagnostic["ret_code_category"] == "missing"
    assert diagnostic["ret_msg_category"] == "not_json"
    assert diagnostic["edge"] == "cloudflare"
    assert diagnostic["content_type"] == "text/html"
    assert diagnostic["body_bytes"] == len(b"Forbidden")
    assert len(diagnostic["body_sha256"]) == 64
    assert "Forbidden" not in line


def test_access_too_frequent_403_closes_session_and_does_not_retry(capsys):
    session = _Session([
        _Response(
            403,
            content=b"403, access too frequent",
            headers={"X-Amz-Cf-Id": "opaque", "Content-Type": "text/plain; charset=utf-8"},
        ),
        _Response(200, _payload(_rows())),
    ])
    with pytest.raises(BybitKlineError, match="repeated requests suppressed"):
        fetch_closed_klines(
            "ETHUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert session.urls == [OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline"]
    assert session.closed is True
    output = capsys.readouterr().out
    assert '"classification":"access_too_frequent"' in output
    assert '"ret_code":null' in output
    assert '"ret_code_category":"missing"' in output
    assert '"ret_msg_category":"not_json"' in output
    assert '"edge":"cloudfront"' in output
    assert "access too frequent" not in output.lower()


def test_json_region_restriction_10009_exposes_only_code_and_categories(capsys):
    raw_message = "Service Restricted: Access is currently unavailable for your region."
    payload = {"retCode": 10009, "retMsg": raw_message, "result": {}, "retExtInfo": {}}
    session = _Session([
        _Response(
            403,
            payload=payload,
            headers={"X-Amz-Cf-Id": "opaque", "Content-Type": "application/json"},
        ),
        _Response(200, _payload(_rows())),
    ])
    with pytest.raises(BybitKlineError, match="HTTP 403 region_restricted"):
        fetch_closed_klines(
            "BTCUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert session.closed is True
    assert len(session.urls) == 1
    output = capsys.readouterr().out
    assert '"classification":"region_restricted"' in output
    assert '"ret_code":10009' in output
    assert '"ret_code_category":"region_restricted"' in output
    assert '"ret_msg_category":"region_restricted"' in output
    assert raw_message not in output


def test_json_api_rate_limit_10006_suppresses_repeated_requests(capsys):
    raw_message = "Too many visits!"
    payload = {"retCode": 10006, "retMsg": raw_message, "result": {}, "retExtInfo": {}}
    session = _Session([
        _Response(403, payload=payload, headers={"Content-Type": "application/json"}),
        _Response(200, _payload(_rows())),
    ])
    with pytest.raises(BybitKlineError, match="HTTP 403 api_rate_limited"):
        fetch_closed_klines(
            "ETHUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert session.closed is True
    assert len(session.urls) == 1
    output = capsys.readouterr().out
    assert '"classification":"api_rate_limited"' in output
    assert '"ret_code":10006' in output
    assert '"ret_code_category":"api_rate_limited"' in output
    assert '"ret_msg_category":"access_too_frequent"' in output
    assert raw_message not in output


def test_unknown_json_403_does_not_leak_ret_msg_and_remains_bounded(capsys, monkeypatch):
    raw_message = "provider-private-diagnostic-that-must-not-leak"
    first = {"retCode": 54321, "retMsg": raw_message, "result": {}}
    sleeps = []
    monkeypatch.setattr(bybit_klines.time, "sleep", sleeps.append)
    request_count = len(OFFICIAL_MAINNET_BASE_URLS) * (
        len(UNCLASSIFIED_403_RETRY_DELAYS_SECONDS) + 1
    )
    session = _Session([
        _Response(403, payload=first, headers={"Content-Type": "application/json"})
        for _ in range(request_count)
    ])
    with pytest.raises(BybitKlineError, match="all approved Bybit Mainnet endpoints"):
        fetch_closed_klines(
            "ETHUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert len(session.urls) == request_count
    assert sleeps == list(UNCLASSIFIED_403_RETRY_DELAYS_SECONDS)
    output = capsys.readouterr().out
    assert output.count('"classification":"unclassified"') == request_count
    assert output.count('"ret_code":54321') == request_count
    assert output.count('"ret_code_category":"unknown"') == request_count
    assert output.count('"ret_msg_category":"other"') == request_count
    assert raw_message not in output


def test_all_host_unclassified_403_gets_one_bounded_retry_round_and_recovers(monkeypatch):
    sleeps = []
    monkeypatch.setattr(bybit_klines.time, "sleep", sleeps.append)
    session = _Session([
        _Response(403),
        _Response(403),
        _Response(200, _payload(_rows())),
    ])
    result = fetch_closed_klines(
        "BTCUSDT",
        "15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
        limit=2,
        session=session,
    )
    assert len(result) == 2
    assert session.urls == [
        OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline",
        OFFICIAL_MAINNET_BASE_URLS[1] + "/v5/market/kline",
        OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline",
    ]
    assert sleeps == [UNCLASSIFIED_403_RETRY_DELAYS_SECONDS[0]]
    request_ids = [row["headers"]["cdn-request-id"] for row in session.requests]
    assert len(request_ids) == len(set(request_ids))


def test_unclassified_403_still_fails_closed_after_bounded_retry_rounds(monkeypatch):
    sleeps = []
    monkeypatch.setattr(bybit_klines.time, "sleep", sleeps.append)
    request_count = len(OFFICIAL_MAINNET_BASE_URLS) * (
        len(UNCLASSIFIED_403_RETRY_DELAYS_SECONDS) + 1
    )
    session = _Session([_Response(403) for _ in range(request_count)])
    with pytest.raises(BybitKlineError, match="all approved Bybit Mainnet endpoints"):
        fetch_closed_klines(
            "ETHUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert len(session.urls) == request_count
    assert sleeps == list(UNCLASSIFIED_403_RETRY_DELAYS_SECONDS)


def test_non_geographic_http_failure_does_not_fall_through_to_another_host():
    session = _Session([_Response(429), _Response(200, _payload(_rows()))])
    with pytest.raises(BybitKlineError, match="HTTP 429"):
        fetch_closed_klines(
            "BTCUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert session.urls == [OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline"]


def test_unclassified_403_backoff_is_explicitly_bounded():
    assert UNCLASSIFIED_403_RETRY_DELAYS_SECONDS == (2.0, 5.0, 15.0, 30.0)


def test_classified_403_after_unclassified_round_still_fails_fast(monkeypatch):
    sleeps = []
    monkeypatch.setattr(bybit_klines.time, "sleep", sleeps.append)
    classified = {
        "retCode": 10009,
        "retMsg": "Service Restricted: unavailable for this region.",
        "result": {},
    }
    session = _Session([
        *[_Response(403) for _ in OFFICIAL_MAINNET_BASE_URLS],
        _Response(403, payload=classified, headers={"Content-Type": "application/json"}),
        _Response(200, _payload(_rows())),
    ])
    with pytest.raises(BybitKlineError, match="HTTP 403 region_restricted"):
        fetch_closed_klines(
            "BTCUSDT",
            "60",
            now_ms=1710010000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000000000,
            limit=1,
            session=session,
        )
    assert len(session.urls) == len(OFFICIAL_MAINNET_BASE_URLS) + 1
    assert sleeps == [UNCLASSIFIED_403_RETRY_DELAYS_SECONDS[0]]
    assert session.closed is True
