"""Boundary and coverage checks for public alternative feeds; no Paper activity."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("alternative_audit", Path(__file__).parents[1] / "scripts/audit_alternative_demo_data.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_full_300_day_grid_rejects_gaps_conflicts_nan_and_open_candle():
    end = 1800 * audit.BAR
    rows = [[t, 10, 12, 9, 11, 3] for t in range(0, end, audit.BAR)]
    result = audit.check_bars(rows, 0, end)
    assert result["complete"] and result["valid"] == 1800
    assert not audit.check_bars(rows[1:], 0, end)["complete"]
    assert not audit.check_bars(rows + [[0, 10, 13, 9, 12, 3]], 0, end)["complete"]
    assert not audit.check_bars(rows + [[0, 10, float("nan"), 9, 11, 3]], 0, end)["complete"]
    result = audit.check_bars(rows[1:] + [[end, 10, 12, 9, 11, 3]], 0, end)
    assert result["missing"] == 1 and result["outside_requested_closed_grid"] == 1


def test_bitget_pages_preserve_candle_boundaries_instead_of_skipping_each_page():
    class Reader:
        def get(self, host, endpoint, params):
            assert host == "api.bitget.com"
            assert endpoint == "/api/v2/spot/market/history-candles"
            # Native API floors milliseconds and excludes the end boundary.
            end = int(params["endTime"]) // (audit.BAR * 1000) * audit.BAR
            return {"data": [[t * 1000, 10, 12, 9, 11, 3] for t in range(max(0, end - 200 * audit.BAR), end, audit.BAR)]}
    result = audit.spot_warmup(Reader(), "bitget", "BTC", 0, 1800 * audit.BAR)
    assert result["complete"] and result["valid"] == 1800


def test_public_reader_denies_nonmarket_routes_and_cache_tampering(tmp_path):
    reader = audit.PublicReader(tmp_path)
    with pytest.raises(audit.AuditFailure, match="DESTINATION_NOT_ALLOWED"):
        reader.get("api.bitget.com", "/api/v2/mix/order/place-order")
    assert reader.requests == 0
    endpoint = "/api/v2/spot/market/history-candles"
    url = "https://api.bitget.com" + endpoint
    key = audit.hashlib.sha256(url.encode()).hexdigest()
    audit.atomic_json(tmp_path / (key + ".json"), {"url": url, "body": {}, "body_sha256": "tampered"})
    with pytest.raises(audit.AuditFailure, match="CACHE_DIGEST_MISMATCH"):
        reader.get("api.bitget.com", endpoint)


def test_access_denial_stops_both_kucoin_hosts_without_retry_or_host_rotation(tmp_path):
    class Denied:
        calls = 0
        def open(self, request, timeout):
            self.calls += 1
            raise audit.urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
    reader = audit.PublicReader(tmp_path)
    reader.opener = Denied()
    with pytest.raises(audit.AuditFailure, match="PROVIDER_ACCESS_DENIED"):
        reader.get("api.kucoin.com", "/api/ua/v1/market/kline")
    with pytest.raises(audit.AuditFailure, match="PROVIDER_ACCESS_DENIED"):
        reader.get("api-futures.kucoin.com", "/api/v1/contracts/XBTUSDTM")
    assert reader.opener.calls == 1
