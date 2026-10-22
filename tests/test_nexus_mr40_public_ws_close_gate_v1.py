"""Synthetic Bybit public WebSocket confirmed-close gate: no network, no orders."""
from copy import deepcopy
from datetime import datetime, timezone
import unittest
from research.nexus_mr40_public_ws_close_gate_v1 import evaluate,STEP4,BRIDGE_END


def frame(start,closed):
    ts=start+STEP4+3000 if closed else start+3_000_000
    return {
        "received_utc":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),
        "bar_start_ms":start,"interval":"240",
        "open":"100","high":"105","low":"95","close":"98",
        "base_volume":"0.25",
        "confirmed_closed":closed,"bybit_message_ts":ts
    }


def probe(sample):
    return {
        "schema":"nexus.mr40.bybit.public_spot_ws_one_shot_result.v1",
        "endpoint":"wss://stream.bybit.com/v5/public/spot",
        "topic":"kline.240.BTCUSDT",
        "public_ws_connected":True,"subscribe_ack_success":True,
        "failure_type":None,"orders_sent":0,"paper_modified":False,
        "private_api_used":False,"received_frames":[sample]
    }


class TestMR40ClosedWSGate(unittest.TestCase):
    def test_unconfirmed_never_accepted(self):
        x=evaluate(probe(frame(BRIDGE_END+STEP4,False)),BRIDGE_END)
        self.assertTrue(x["transport_qualified_for_market_read_only"])
        self.assertFalse(x["may_feed_mr40_from_this_probe"])
        self.assertEqual(x["confirmed_closed_samples_seen"],0)

    def test_missing_four_prior_bars_blocks_even_confirmed(self):
        current=BRIDGE_END+5*STEP4
        x=evaluate(probe(frame(current,True)),BRIDGE_END)
        self.assertFalse(x["may_feed_mr40_from_this_probe"])
        self.assertEqual(x["missing_completed_4h_bars_before_latest_ws_bar"],4)

    def test_only_properly_confirmed_immediately_next_bar_accepted(self):
        x=evaluate(probe(frame(BRIDGE_END+STEP4,True)),BRIDGE_END)
        self.assertTrue(x["may_feed_mr40_from_this_probe"])
        self.assertEqual(x["confirmed_4h_contiguous_rows_accepted"],1)
        self.assertEqual(x["orders_sent"],0)

    def test_false_boolean_string_is_rejected(self):
        x=frame(BRIDGE_END+STEP4,True)
        x["confirmed_closed"]="true"
        with self.assertRaisesRegex(ValueError,"malformed_spot_kline"):
            evaluate(probe(x),BRIDGE_END)

    def test_future_confirm_before_bar_end_is_rejected(self):
        x=frame(BRIDGE_END+STEP4,True)
        x["bybit_message_ts"]=x["bar_start_ms"]+STEP4-1000
        with self.assertRaisesRegex(ValueError,"confirmed_before"):
            evaluate(probe(x),BRIDGE_END)

    def test_wrong_price_envelope_rejected_even_if_not_confirmed(self):
        x=frame(BRIDGE_END+STEP4,False)
        x["low"]="101"
        with self.assertRaisesRegex(ValueError,"invalid_spot_public_ohlcv"):
            evaluate(probe(x),BRIDGE_END)

    def test_wrong_topic_never_accepted(self):
        x=probe(frame(BRIDGE_END+STEP4,True))
        x["topic"]="kline.240.ETHUSDT"
        with self.assertRaisesRegex(ValueError,"invalid_live_public_probe"):
            evaluate(x,BRIDGE_END)

    def test_duplicate_confirmed_bar_fails_closed(self):
        q=frame(BRIDGE_END+STEP4,True)
        duplicate=deepcopy(q)
        duplicate["bybit_message_ts"]+=1000
        p=probe(q)
        p["received_frames"].append(duplicate)
        with self.assertRaisesRegex(ValueError,"repeat_closed_market_candle"):
            evaluate(p,BRIDGE_END)

    def test_subscription_only_not_enough(self):
        x=probe(frame(BRIDGE_END+STEP4,True))
        x["subscribe_ack_success"]=False
        self.assertFalse(evaluate(x,BRIDGE_END)["may_feed_mr40_from_this_probe"])


if __name__=="__main__":
    unittest.main()
