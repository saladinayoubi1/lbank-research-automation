"""Synthetic quote-walk and public Bybit Spot L50 source-validation tests."""
import copy,json,unittest
from datetime import datetime,timezone
from decimal import Decimal as D
from research.nexus_mr40_bybit_spot_ob50_visible_cost_v1 import (
    inspect,validate_side,buy_quote,sell_base
)

P={"schema":"nexus.mr40.bybit_public_spot_orderbook50_cost_snapshot.v1",
   "endpoint":"wss://stream.bybit.com/v5/public/spot",
   "topic":"orderbook.50.BTCUSDT",
   "quote_notional_usdt":"500",
   "safety":{"orders":0}}


def source(bids=None,asks=None):
    bids=bids if bids is not None else [["100","2.0"],["99","5.0"]]
    asks=asks if asks is not None else [["101","2.0"],["102","5.0"]]
    ts=1792600000000
    payload={"topic":"orderbook.50.BTCUSDT","type":"snapshot","ts":ts,
             "data":{"s":"BTCUSDT","b":bids,"a":asks,"u":5,"seq":7}}
    return {
        "schema":"nexus.mr40.bybit_public_spot_ob50_snapshot_capture.results.v1",
        "endpoint":P["endpoint"],"topic":P["topic"],
        "connected":True,"subscription_ack":True,"snapshot_received":True,
        "source_received_utc":datetime.fromtimestamp((ts+250)/1000,timezone.utc).isoformat(),
        "raw_snapshot_text":json.dumps(payload),
        "orders_sent":0,"paper_modified":False,"private_api_used":False
    }


class TestVisibleCostBook(unittest.TestCase):
    def test_valid_single_snapshot_positive_spread_and_friction(self):
        a=inspect(source(),P)
        self.assertEqual(a["best_bid_usdt_per_btc"],"100")
        self.assertEqual(a["best_ask_usdt_per_btc"],"101")
        self.assertGreater(D(a["hypothetical_roundtrip_visible_book_friction_bps"]),D(0))
        self.assertEqual(a["ask_levels_needed"],2)
        self.assertEqual(a["bid_levels_needed"],2)
        self.assertFalse(a["real_fill_proven"])

    def test_cannot_claim_sufficient_visible_asks(self):
        with self.assertRaisesRegex(ValueError,"visible_asks_cannot_cover"):
            inspect(source(asks=[["101","0.001"]]),P)

    def test_cannot_claim_sufficient_visible_bids(self):
        with self.assertRaisesRegex(ValueError,"visible_bids_cannot_cover"):
            inspect(source(bids=[["100","0.001"]]),P)

    def test_crossed_or_locked_book_rejected(self):
        with self.assertRaisesRegex(ValueError,"crossed_or_locked"):
            inspect(source(bids=[["101","1.0"]]),P)

    def test_duplicate_bid_level_is_invalid(self):
        with self.assertRaisesRegex(ValueError,"nonmonotonic"):
            inspect(source(bids=[["100","1"],["100","2"]]),P)

    def test_outdated_snapshot_staleness_guard(self):
        s=source()
        s["source_received_utc"]=datetime.fromtimestamp((1792600000000+35000)/1000,timezone.utc).isoformat()
        with self.assertRaisesRegex(ValueError,"stale_or_future"):
            inspect(s,P)

    def test_wrong_topic_or_market_rejected(self):
        s=source()
        q=json.loads(s["raw_snapshot_text"])
        q["topic"]="orderbook.50.ETHUSDT"
        s["raw_snapshot_text"]=json.dumps(q)
        with self.assertRaisesRegex(ValueError,"not_original_spot"):
            inspect(s,P)

    def test_no_ack_and_no_money_auth(self):
        s=source()
        s["subscription_ack"]=False
        with self.assertRaisesRegex(ValueError,"untrusted_market_only_transport"):
            inspect(s,P)

    def test_depth_walk_never_uses_price_levels_twice(self):
        asks=[(D("100"),D("1")), (D("110"),D("1"))]
        got,k=buy_quote(asks,D("150"))
        self.assertEqual(k,2)
        self.assertEqual(got,D("1")+D("50")/D("110"))
        bids=[(D("99"),D("1")),(D("98"),D("2"))]
        proceeds,j=sell_base(bids,got)
        self.assertEqual(j,2)
        self.assertEqual(proceeds,D("99")+(got-D("1"))*D("98"))


if __name__=="__main__":
    unittest.main()
