"""No-data, synthetic-only test of future Bybit capture embargo."""
from datetime import datetime, timezone
from io import BytesIO
import json
import unittest
from unittest.mock import patch

import nexus_v13_forward_readiness as gate


class ForwardEmbargoTests(unittest.TestCase):
    def moment(self,text):
        return datetime.fromisoformat(text.replace("Z","+00:00"))

    def test_before_future_data_exists(self):
        r=gate.eligibility(self.moment("2026-10-15T23:59:59Z"))
        self.assertEqual(r["status"],"BEFORE_PROSPECTIVE_WINDOW")
        self.assertFalse(r["eligible_to_capture_only_closed_future_bars"])
        self.assertEqual(r["market_bars_retrieved"],0)

    def test_first_fifteen_minute_bar_must_fully_close(self):
        self.assertFalse(gate.eligibility(self.moment(
            "2026-10-16T00:14:59Z"))["eligible_to_capture_only_closed_future_bars"])
        self.assertTrue(gate.eligibility(self.moment(
            "2026-10-16T00:15:00Z"))["eligible_to_capture_only_closed_future_bars"])

    def test_exclusive_end_of_forward_window(self):
        self.assertTrue(gate.eligibility(self.moment(
            "2026-12-15T23:59:59Z"))["eligible_to_capture_only_closed_future_bars"])
        r=gate.eligibility(self.moment("2026-12-16T00:00:00Z"))
        self.assertFalse(r["eligible_to_capture_only_closed_future_bars"])
        self.assertEqual(r["status"],"PROSPECTIVE_WINDOW_ENDED")

    def test_utc_offset_and_naive_fail_closed(self):
        with self.assertRaises(ValueError):
            gate.eligibility(datetime(2026,10,16,0,15))
        self.assertTrue(gate.eligibility(self.moment(
            "2026-10-16T02:15:00+02:00"))["eligible_to_capture_only_closed_future_bars"])

    def test_public_time_only_mock_does_not_ask_market_candles(self):
        payload={"retCode":0,"retMsg":"OK","result":{"timeSecond":"1792109700"}}
        with patch.object(gate,"urlopen",return_value=BytesIO(json.dumps(payload).encode())) as get:
            r=gate.fetch_public_server_time()
        self.assertEqual(r.tzinfo,timezone.utc)
        self.assertEqual(get.call_count,1)
        request=get.call_args.args[0]
        self.assertEqual(request.full_url,"https://api.bybit.com/v5/market/time")
        self.assertNotIn("kline",request.full_url)

    def test_non_success_or_missing_clock_denied(self):
        for obj in ({"retCode":10001,"retMsg":"error"},{"retCode":0,"result":{}}):
            with self.subTest(obj=obj),patch.object(gate,"urlopen",
                  return_value=BytesIO(json.dumps(obj).encode())):
                with self.assertRaises((ValueError,RuntimeError)):
                    gate.fetch_public_server_time()

    def test_never_fetch_market_or_place_orders(self):
        self.assertTrue(gate.RESEARCH_ONLY)
        self.assertFalse(gate.FETCHES_MARKET_BARS)
        self.assertFalse(gate.ORDERS_ENABLED)
        self.assertFalse(gate.LIVE_ENABLED)


if __name__=="__main__":
    unittest.main()
