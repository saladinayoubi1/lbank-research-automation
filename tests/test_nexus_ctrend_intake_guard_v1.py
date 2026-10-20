"""No network: request mutations and synthetic metadata payloads only."""
from copy import deepcopy
import unittest

from research.nexus_ctrend_intake_guard_v1 import (
    IntakeRejected, check_response_metadata, preflight,
)

BYBIT = "https://api.bybit.com/v5/market/instruments-info"
CMC = "https://pro-api.coinmarketcap.com/public-api/v1/cryptocurrency/map"


class IntakeGuardTests(unittest.TestCase):
    def test_valid_instrument_metadata_carries_no_financial_authority(self):
        result = preflight(BYBIT + "?symbol=BTCUSDT&category=spot")
        self.assertEqual(result["canonical_url"], BYBIT + "?category=spot&symbol=BTCUSDT")
        self.assertIsNone(result["coverage"])
        self.assertTrue(result["metadata_only"])
        for flag in ("historical_vintage_certified", "complete_universe_certified",
                     "price_fetch_authorized", "label_fetch_authorized",
                     "financial_fetch_authorized", "financial_backtest_authorized",
                     "demo_admitted", "paper_writer_enabled", "live_enabled"):
            self.assertFalse(result[flag])
        self.assertEqual(result["network_requests"], 0)

    def test_status_selection_is_explicit_and_canonical_url_is_idempotent(self):
        with self.assertRaises(IntakeRejected): preflight(CMC)
        full = preflight(CMC + "?listing_status=untracked,active,inactive&limit=5000&start=1")
        self.assertTrue(full["all_cmc_statuses_requested"])
        self.assertIn("listing_status=active%2Cinactive%2Cuntracked", full["canonical_url"])
        self.assertEqual(preflight(full["canonical_url"]), full)
        subset = preflight(CMC + "?listing_status=inactive")
        self.assertEqual(subset["status_coverage_requested"], ["inactive"])
        self.assertFalse(subset["all_cmc_statuses_requested"])
        self.assertFalse(full["complete_universe_certified"])

    def test_prices_cannot_be_disguised_as_metadata(self):
        endpoints = [BYBIT.replace("instruments-info", name) + "?category=spot"
                     for name in ("kline", "tickers", "recent-trade", "orderbook")]
        endpoints += [CMC.replace("/map", ending) + "?listing_status=active"
                      for ending in ("/quotes/latest", "/ohlcv/historical", "/listings/historical")]
        for url in endpoints:
            with self.subTest(url=url):
                with self.assertRaises(IntakeRejected): preflight(url, request_kind="metadata")

    def test_credentials_ports_fragments_aliases_and_url_controls_are_rejected(self):
        valid = BYBIT + "?category=spot"
        cases = [valid.replace("https://", "http://"),
                 valid.replace("api.bybit.com", "user:password@api.bybit.com"),
                 valid.replace("api.bybit.com", "api.bybit.com:443"),
                 valid.replace("api.bybit.com", "api.bybit.com.attacker.example"),
                 valid.replace("api.bybit.com", "API.BYBIT.COM"),
                 valid.replace("api.bybit.com", "api.bybit.com."),
                 valid + "#", valid + "#metadata", "\n" + valid, valid + "\t",
                 valid + "&api_key=secret", valid + "&X-CMC_PRO_API_KEY=secret"]
        for url in cases:
            with self.subTest(url=url):
                with self.assertRaises(IntakeRejected): preflight(url)

    def test_query_mutations_never_expand_the_metadata_allowlist(self):
        cases = [BYBIT, BYBIT + "?category=linear", BYBIT + "?category=spot&category=spot",
                 BYBIT + "?category=spot&%63ategory=spot", BYBIT + "?category=spot&symbol=btcusdt",
                 BYBIT + "?category=spot&symbol=", BYBIT + "?category=spot&start=1",
                 BYBIT + "?category=spot&symbol=BTCUSDT%00", BYBIT + "?category=spot&symbol",
                 CMC + "?listing_status=active&sort=cmc_rank",
                 CMC + "?listing_status=active&convert=USD",
                 CMC + "?listing_status=active&limit=5001",
                 CMC + "?listing_status=active&start=0",
                 CMC + "?listing_status=active&start=+1",
                 CMC + "?listing_status=active&limit=1&limit=1"]
        for url in cases:
            with self.subTest(url=url):
                with self.assertRaises(IntakeRejected): preflight(url)

    def test_statuses_cannot_hide_omitted_duplicate_or_unknown_coverage(self):
        for value in ("", "all", "active,active", "active,", "active,delisted", "Active"):
            with self.subTest(status=value):
                with self.assertRaises(IntakeRejected): preflight(CMC + "?listing_status=" + value)

    def test_coverage_boundaries_do_not_authorize_market_data(self):
        result = preflight(BYBIT + "?category=spot", coverage_start="2021-01-01T00:00Z",
                           coverage_end="2026-10-19T00:00:00Z")
        self.assertEqual(result["coverage"]["end_exclusive"], "2026-10-19T00:00:00Z")
        self.assertTrue(result["coverage_is_caller_annotation_only"])
        self.assertFalse(result["financial_fetch_authorized"])
        self.assertFalse(result["historical_vintage_certified"])
        ranges = [("2020-12-31T23:59Z", "2021-01-01T00:00Z"),
                  ("2026-10-19T00:00Z", "2027-01-17T00:00Z"),
                  ("2026-10-18T00:00Z", "2026-10-19T00:00:01Z"),
                  ("2022-01-01T00:00Z", "2022-01-01T00:00Z"),
                  ("2022-01-02T00:00Z", "2022-01-01T00:00Z"),
                  ("2022-01-01T00:00+00:00", "2023-01-01T00:00Z"),
                  ("2022-02-30T00:00Z", "2023-01-01T00:00Z"),
                  (None, "2023-01-01T00:00Z")]
        for first, last in ranges:
            with self.subTest(first=first, last=last):
                with self.assertRaises(IntakeRejected):
                    preflight(BYBIT + "?category=spot", coverage_start=first, coverage_end=last)

    def test_caller_labels_cannot_grant_price_or_financial_authority(self):
        for kind in ("prices", "labels", "financial", "historical_metadata", "demo", None):
            with self.subTest(kind=kind):
                with self.assertRaises(IntakeRejected):
                    preflight(BYBIT + "?category=spot", request_kind=kind)

    def test_instrument_price_constraints_are_metadata_and_payload_is_not_mutated(self):
        payload = {"retCode": 0, "result": {"category": "spot", "list": [
            {"symbol": "BTCUSDT", "quoteCoin": "USDT", "priceFilter": {
                "tickSize": "0.1", "minPrice": "0.1", "maxPrice": "1000000"},
             "lotSizeFilter": {"minOrderAmt": "5", "basePrecision": "0.000001",
                               "quotePrecision": "0.00000001"}}]}}
        before = deepcopy(payload)
        result = check_response_metadata(payload)
        self.assertEqual(payload, before)
        self.assertFalse(result["provider_authenticity_verified"])
        self.assertFalse(result["complete_payload_security_validation"])
        self.assertFalse(result["provider_success_verified"])

    def test_obvious_nested_market_fields_are_rejected_without_schema_claims(self):
        for key in ("price", "Price_USD", "quote", "OHLCV", "lastPrice", "volume_24h",
                    "return_1d", "percent_change_24h", "high24h", "market_cap",
                    "market_cap_usd", "self_reported_market_cap"):
            with self.subTest(field=key):
                with self.assertRaises(IntakeRejected):
                    check_response_metadata({"result": [{"attributes": {key: "123"}}]})
        cycle = []; cycle.append(cycle)
        for invalid in (cycle, {1: "not-json"}, {"x": float("nan")}, {"x": object()}):
            with self.assertRaises(IntakeRejected): check_response_metadata(invalid)
        error_payload = check_response_metadata({"retCode": 10006, "retMsg": "Denied"})
        self.assertFalse(error_payload["provider_success_verified"])


if __name__ == "__main__":
    unittest.main()
