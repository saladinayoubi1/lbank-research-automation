"""1m real-time source semantics synthetic tests; no network and no trades."""
import unittest
from datetime import datetime,timezone
from research.nexus_mr40_ws_minute_raw_forensics_v1 import inspect_message


def item(*,confirmed,bar_start=600000,server_ms=660563,trade_ms=660563,received_ms=662728):
    return {"received_utc":datetime.fromtimestamp(received_ms/1000,timezone.utc).isoformat(),
        "payload":{"topic":"kline.1.BTCUSDT","ts":server_ms,
          "data":[{"start":bar_start,"end":bar_start+59999,"interval":"1",
                   "open":"100","high":"101","low":"99","close":"100.5",
                   "volume":"1.0","confirm":confirmed,"timestamp":trade_ms}]}
    }


class TestMinuteWSPostCapture(unittest.TestCase):
    def test_observed_confirm_true_and_timestamp_after_end_is_flagged_not_four_hour(self):
        z=inspect_message(item(confirmed=True))[0]
        self.assertTrue(z["eligible_evidence_of_one_minute_closed_source"])
        self.assertEqual(z["trade_timestamp_beyond_candle_end_ms"],564)
        self.assertFalse(z["eligible_MR40_fourhour_signal_input"])

    def test_unconfirmed_not_evidence_even_if_received_after_end(self):
        z=inspect_message(item(confirmed=False))[0]
        self.assertFalse(z["eligible_evidence_of_one_minute_closed_source"])

    def test_true_before_end_rejected(self):
        with self.assertRaisesRegex(ValueError,"premature_confirm_true"):
            inspect_message(item(confirmed=True,server_ms=650000,trade_ms=650000,received_ms=650000))

    def test_string_confirm_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,"invalid_confirm"):
            inspect_message(item(confirmed="true"))

    def test_invalid_ohlcv_cannot_pass(self):
        r=item(confirmed=True)
        r["payload"]["data"][0]["low"]="101"
        with self.assertRaisesRegex(ValueError,"bad_minute_ohlcv"):
            inspect_message(r)

    def test_synthetic_wrong_topic_rejected(self):
        r=item(confirmed=True)
        r["payload"]["topic"]="kline.1.ETHUSDT"
        with self.assertRaisesRegex(ValueError,"not_a_public_spot_minute"):
            inspect_message(r)


if __name__=="__main__":
    unittest.main()
