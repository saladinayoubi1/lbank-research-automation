import json
from urllib.parse import parse_qs, urlsplit

import pytest

from bitget_public_demo_collector import (
    BitgetCollectorError,
    BitgetPublicReader,
    BitgetRequestBudgetExceeded,
    PublicResponse,
    TRADE_CANDLES_PATH,
    canonical_url,
    collect_trade_candle_window,
    collection_manifest,
)


def response(rows, *, status=200, code="00000"):
    return PublicResponse(status, json.dumps({"code": code, "data": rows}).encode())


def row(stamp, close="101"):
    return [str(stamp), "100", "105", "99", close, "10", "1000"]


def test_canonical_url_is_sorted_and_official_only():
    url = canonical_url(TRADE_CANDLES_PATH, {"symbol": "BTCUSDT", "limit": 200})
    assert url == (
        "https://api.bitget.com/api/v2/mix/market/history-candles?"
        "limit=200&symbol=BTCUSDT"
    )
    with pytest.raises(BitgetCollectorError, match="DESTINATION_NOT_ALLOWED"):
        canonical_url("/api/v2/mix/order/place-order", {})


def test_reader_writes_and_reuses_immutable_cache(tmp_path):
    calls = []

    def transport(url):
        calls.append(url)
        return response([row(0)])

    first = BitgetPublicReader(
        tmp_path, transport=transport, observed_at=lambda: "2026-10-04T00:00:00+00:00"
    )
    body = first.get(TRADE_CANDLES_PATH, {"symbol": "BTCUSDT"})
    assert body["data"][0][0] == "0"
    assert first.requests == 1
    second = BitgetPublicReader(tmp_path, transport=transport)
    assert second.get(TRADE_CANDLES_PATH, {"symbol": "BTCUSDT"}) == body
    assert second.requests == 0
    assert len(calls) == 1
    assert second.receipts[0]["body_sha256"] == first.receipts[0]["body_sha256"]


def test_tampered_cache_fails_closed(tmp_path):
    reader = BitgetPublicReader(tmp_path, transport=lambda _url: response([row(0)]))
    reader.get(TRADE_CANDLES_PATH, {"symbol": "BTCUSDT"})
    cache = next(tmp_path.glob("*.json"))
    payload = json.loads(cache.read_text())
    payload["body"]["data"][0][4] = "999"
    cache.write_text(json.dumps(payload))
    with pytest.raises(BitgetCollectorError, match="CACHE_DIGEST_MISMATCH"):
        BitgetPublicReader(tmp_path).get(
            TRADE_CANDLES_PATH, {"symbol": "BTCUSDT"}
        )


def test_one_transient_retry_then_success(tmp_path):
    results = [PublicResponse(503, b""), response([row(0)])]
    reader = BitgetPublicReader(tmp_path, transport=lambda _url: results.pop(0))
    assert reader.get(TRADE_CANDLES_PATH, {"symbol": "BTCUSDT"})["code"] == "00000"
    assert reader.requests == 2
    assert reader.receipts[0]["attempts"] == 2


def test_access_denial_stops_provider_without_retry(tmp_path):
    calls = []

    def transport(url):
        calls.append(url)
        return PublicResponse(403, b"")

    reader = BitgetPublicReader(tmp_path, transport=transport)
    with pytest.raises(BitgetCollectorError, match="PROVIDER_ACCESS_DENIED"):
        reader.get(TRADE_CANDLES_PATH, {"symbol": "BTCUSDT"})
    with pytest.raises(BitgetCollectorError, match="PROVIDER_ACCESS_DENIED"):
        reader.get(TRADE_CANDLES_PATH, {"symbol": "ETHUSDT"})
    assert len(calls) == 1


def test_request_budget_is_fail_closed(tmp_path):
    reader = BitgetPublicReader(
        tmp_path, request_budget=1, transport=lambda _url: PublicResponse(503, b"")
    )
    with pytest.raises(BitgetRequestBudgetExceeded, match="CHECKPOINT"):
        reader.get(TRADE_CANDLES_PATH, {"symbol": "BTCUSDT"})
    assert reader.requests == 1


def test_collects_exact_window_over_reverse_pages(tmp_path):
    calls = []

    def transport(url):
        query = parse_qs(urlsplit(url).query)
        calls.append(query)
        end = int(query["endTime"][0])
        if end == 43_200_000:
            return response([row(28_800_000, "103"), row(14_400_000, "102")])
        if end == 14_400_000:
            return response([row(0, "101")])
        raise AssertionError(f"unexpected cursor {end}")

    reader = BitgetPublicReader(tmp_path, transport=transport)
    bars = collect_trade_candle_window(
        reader,
        symbol="BTCUSDT",
        interval="4H",
        interval_ms=14_400_000,
        start_ms=0,
        end_exclusive_ms=43_200_000,
    )
    assert [bar.open_time_ms for bar in bars] == [0, 14_400_000, 28_800_000]
    assert len(calls) == 2
    assert calls[1]["endTime"] == ["14400000"]


def test_missing_or_conflicting_candles_fail_closed(tmp_path):
    reader = BitgetPublicReader(tmp_path / "missing", transport=lambda _url: response([row(0)]))
    with pytest.raises(ValueError, match="incomplete"):
        collect_trade_candle_window(
            reader, symbol="BTCUSDT", interval="4H", interval_ms=14_400_000,
            start_ms=0, end_exclusive_ms=28_800_000,
        )

    responses = [
        response([row(14_400_000, "101"), row(28_800_000, "102")]),
        response([row(14_400_000, "999"), row(0, "100")]),
    ]
    reader = BitgetPublicReader(tmp_path / "conflict", transport=lambda _url: responses.pop(0))
    with pytest.raises(BitgetCollectorError, match="CONFLICTING"):
        collect_trade_candle_window(
            reader, symbol="BTCUSDT", interval="4H", interval_ms=14_400_000,
            start_ms=0, end_exclusive_ms=43_200_000,
        )


def test_manifest_has_lineage_and_no_authority(tmp_path):
    reader = BitgetPublicReader(tmp_path, transport=lambda _url: response([row(0)]))
    bars = collect_trade_candle_window(
        reader, symbol="ETHUSDT", interval="4H", interval_ms=14_400_000,
        start_ms=0, end_exclusive_ms=14_400_000,
    )
    manifest = collection_manifest(
        reader, symbol="ETHUSDT", interval="4H", interval_ms=14_400_000,
        start_ms=0, end_exclusive_ms=14_400_000, bars=bars,
    )
    assert manifest["bar_count"] == 1
    assert len(manifest["normalized_sha256"]) == 64
    assert len(manifest["http_receipts"]) == 1
    assert manifest["private_credentials_used"] is False
    assert manifest["orders_sent"] is False
    assert manifest["owner_paper_mutated"] is False
    assert manifest["demo_replacement_authorized"] is False
    assert manifest["strategy_promotion_authority"] is False
    assert manifest["live_trading_authority"] is False


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"symbol": "SOLUSDT"}, "SYMBOL_NOT_ALLOWED"),
        ({"interval": "5m"}, "INTERVAL_NOT_ALLOWED"),
        ({"end_exclusive_ms": 0}, "INVALID_WINDOW"),
    ],
)
def test_collection_inputs_are_bounded(tmp_path, kwargs, message):
    values = dict(
        symbol="BTCUSDT", interval="4H", interval_ms=14_400_000,
        start_ms=0, end_exclusive_ms=14_400_000,
    )
    values.update(kwargs)
    reader = BitgetPublicReader(tmp_path, transport=lambda _url: response([row(0)]))
    with pytest.raises(BitgetCollectorError, match=message):
        collect_trade_candle_window(reader, **values)
