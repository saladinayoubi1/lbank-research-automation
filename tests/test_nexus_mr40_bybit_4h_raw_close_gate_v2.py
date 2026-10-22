"""Standalone no-network Spot 4h *raw JSON* close-gate synthetic tests."""
from __future__ import annotations
import copy
import json
import unittest
from datetime import datetime,timezone
from research.nexus_mr40_bybit_4h_raw_close_gate_v2 import (
    BAR_START,BAR_END,TOPIC,URL,STEP4,classify_capture,strict_bar
)


def utc(ms):
    return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()


def raw_bar(confirm=True, data_ts=None):
    return {
        "start":BAR_START,"end":BAR_END,"interval":"240",
        "open":"81677.3","high":"81800.0","low":"80900.0","close":"81400.0",
        "volume":"2730.5","confirm":confirm,
        "timestamp":BAR_END+564 if data_ts is None else data_ts
    }


def container(bar=None,server_ms=BAR_END+1000,recv_ms=BAR_END+2000):
    msg={
        "topic":TOPIC,"type":"snapshot","ts":server_ms,
        "data":[raw_bar() if bar is None else bar]
    }
    return {
        "schema":"nexus.mr40.bybit.public_spot_fourhour_raw_close_v2.results.v1",
        "endpoint":URL,"topic":TOPIC,
        "public_ws_connected":True,"subscribe_ack_success":True,
        "paper_modified":False,"orders_sent":0,
        "private_api_used":False,"live_enabled":False,
        "raw_topic_receipts":[{"received_utc":utc(recv_ms),"raw_text":json.dumps(msg)}],
    }


class TestSourceOnlyRawFourHourGate(unittest.TestCase):
    def test_genuine_confirm_after_close_is_not_mr40_due_to_four_bar_gap(self):
        x=classify_capture(container())
        self.assertTrue(x["confirmed_4h_closed_seen"])
        self.assertFalse(x["MR40_source_ready"])
        self.assertEqual(x["missing_fourhour_bars"],4)
        self.assertEqual(x["snapshots"],1)

    def test_string_true_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,"not_native_bool"):
            classify_capture(container(raw_bar("true")))

    def test_integer_true_cannot_pass(self):
        with self.assertRaisesRegex(ValueError,"not_native_bool"):
            classify_capture(container(raw_bar(1)))

    def test_unconfirmed_does_not_pass_even_if_received_after_close(self):
        x=classify_capture(container(raw_bar(False)))
        self.assertFalse(x["confirmed_4h_closed_seen"])
        self.assertFalse(x["MR40_source_ready"])

    def test_preclose_server_timestamp_never_authorizes_true(self):
        with self.assertRaisesRegex(ValueError,"premature_true"):
            classify_capture(container(server_ms=BAR_END-2))

    def test_early_receipt_never_authorizes_true(self):
        with self.assertRaisesRegex(ValueError,"premature_true"):
            classify_capture(container(recv_ms=BAR_END-2))

    def test_data_timestamp_after_bar_end_is_only_warned(self):
        x=classify_capture(container(raw_bar(True,BAR_END+564)))
        self.assertEqual(x["confirmed_source_4h_evidence"][0]["ancillary_timestamp_after_bar_end_ms"],564)
        self.assertFalse(x["MR40_source_ready"])

    def test_duplicate_true_source_event_refused(self):
        p=container()
        p["raw_topic_receipts"].append(copy.deepcopy(p["raw_topic_receipts"][0]))
        with self.assertRaisesRegex(ValueError,"duplicate_true"):
            classify_capture(p)

    def test_non_spot_topic_refused(self):
        p=container()
        msg=json.loads(p["raw_topic_receipts"][0]["raw_text"])
        msg["topic"]="kline.240.ETHUSDT"
        p["raw_topic_receipts"][0]["raw_text"]=json.dumps(msg)
        with self.assertRaisesRegex(ValueError,"wrong_topic"):
            classify_capture(p)

    def test_invalid_ohlc_refused(self):
        bad=raw_bar();bad["low"]="81900"
        with self.assertRaisesRegex(ValueError,"invalid_ohlcv_envelope"):
            classify_capture(container(bad))

    def test_wrong_4h_bar_identity_refused(self):
        bad=raw_bar();bad["start"]+=STEP4;bad["end"]+=STEP4
        with self.assertRaisesRegex(ValueError,"identity_mismatch"):
            classify_capture(container(bad,server_ms=BAR_END+STEP4+1,recv_ms=BAR_END+STEP4+2000))

    def test_no_subscription_ack_no_signal(self):
        p=container();p["subscribe_ack_success"]=False
        x=classify_capture(p)
        self.assertFalse(x["confirmed_4h_closed_seen"])
        self.assertFalse(x["MR40_source_ready"])


if __name__=="__main__":
    unittest.main()
