"""V26 post-signal quote guards; entirely synthetic, no exchange or order IO."""
import unittest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal

from nexus_elliott_post_signal_quote_v26 import (
    RESEARCH_ONLY,LIVE_ENABLED,AUTO_DEMO,PAPER_ELIGIBLE,
    BROKER_ORDER_AUTHORITY,BROKER_FILL_VERIFIED,SOURCE_AND_QUOTE_ATTESTED,
    assess_quote_only,
)
START=datetime(2026,10,16,0,15,tzinfo=timezone.utc)
MS=timedelta(milliseconds=100)


def event(**kw):
    obj={"symbol":"BTCUSDT","event_id":"synthetic-20261016-BTC-1",
         "decision_close_utc":START,
         "previous_close":"109","decision_close":"112",
         "fifth_high":"110","correction_low":"100",
         "source_bound_seven_pivot":True,"closed_first_breakout":True,
         "post_correction_path_valid":True}
    obj.update(kw)
    return obj


def book(**kw):
    obj={"symbol":"BTCUSDT","best_bid":"112.0","best_ask":"112.2",
         "market_quoted_at_utc":START+MS,
         "client_received_at_utc":START+2*MS}
    obj.update(kw)
    return obj


def evaluate(*,o=None,q=None,profile="conservative",source=None,signal=None,asof=None):
    return assess_quote_only(event() if o is None else o,
                             book() if q is None else q,
                             profile=profile,
                             source_received_at_utc=START if source is None else source,
                             signal_committed_at_utc=START if signal is None else signal,
                             examined_at_utc=START+3*MS if asof is None else asof)


class QuoteOnlyV26Tests(unittest.TestCase):
    def test_no_authority_and_no_future_exit_in_module(self):
        self.assertTrue(RESEARCH_ONLY)
        for flag in (LIVE_ENABLED,AUTO_DEMO,PAPER_ELIGIBLE,
                     BROKER_ORDER_AUTHORITY,BROKER_FILL_VERIFIED,
                     SOURCE_AND_QUOTE_ATTESTED):
            self.assertFalse(flag)

    def test_clean_quote_is_never_a_broker_fill_or_pnl(self):
        r=evaluate()
        self.assertEqual(r["disposition"],
                         "ADVISORY_QUOTED_PRICE_PATH_ONLY_NOT_EXECUTABLE")
        self.assertIsNone(r["observed_trade_pnl"])
        self.assertEqual(r["exit_bars_consulted"],0)
        self.assertFalse(r["actual_position_filled"])
        self.assertFalse(r["promotable_to_demo"])
        self.assertFalse(r["recursive_elliott_count_proven"])
        self.assertEqual(r["orders_placed"],0)

    def test_cannot_infer_profitable_trade_from_2r_projection(self):
        r=evaluate()
        self.assertGreater(Decimal(r["conditional_target_net_per_unit_not_observed"]),0)
        self.assertLess(Decimal(r["conditional_stop_net_per_unit_not_observed"]),0)
        self.assertIsNone(r["observed_trade_pnl"])

    def test_stress_profile_worse_conditional_target(self):
        a=evaluate(profile="conservative")
        b=evaluate(profile="stress")
        self.assertLess(Decimal(b["conditional_target_net_per_unit_not_observed"]),
                        Decimal(a["conditional_target_net_per_unit_not_observed"]))
        self.assertNotEqual(a["quote_and_decision_sha256"],b["quote_and_decision_sha256"])

    def test_ask_only_above_high_is_not_accepted_as_breakout(self):
        r=evaluate(q=book(best_bid="109.9",best_ask="112.2"))
        self.assertEqual(r["disposition"],
                         "REJECT_BID_NOT_ABOVE_FIFTH_PIVOT_HIGH")
        self.assertFalse(r["bid_above_breakout_high"])

    def test_exact_fifth_high_bid_is_rejected(self):
        r=evaluate(q=book(best_bid="110",best_ask="110.1"))
        self.assertEqual(r["disposition"],
                         "REJECT_BID_NOT_ABOVE_FIFTH_PIVOT_HIGH")

    def test_very_wide_spread_reported_not_hidden(self):
        r=evaluate(q=book(best_bid="111",best_ask="140"))
        self.assertGreater(Decimal(r["raw_spread_bps"]),Decimal("1000"))
        self.assertEqual(r["orders_placed"],0)

    def test_crossed_and_locked_book_rejected(self):
        for ask in ("110","109"):
            with self.subTest(ask=ask),self.assertRaisesRegex(
                ValueError,"crossed/locked"
            ):
                evaluate(q=book(best_bid="110",best_ask=ask))

    def test_zero_nan_or_negative_prices_fail_closed(self):
        for invalid in ("nan","0","-5","Infinity"):
            with self.subTest(value=invalid),self.assertRaisesRegex(
                ValueError,"finite positive"
            ):
                evaluate(q=book(best_bid=invalid))

    def test_source_receipt_before_decision_rejected(self):
        with self.assertRaisesRegex(ValueError,"source received before"):
            evaluate(source=START-MS)

    def test_signal_cannot_precede_source_receipt(self):
        with self.assertRaisesRegex(ValueError,"signal before"):
            evaluate(source=START+MS,signal=START)

    def test_market_quote_cannot_precede_signal(self):
        with self.assertRaisesRegex(ValueError,"precedes signal"):
            evaluate(signal=START+2*MS)

    def test_quote_receive_cannot_precede_quote_market_clock(self):
        with self.assertRaisesRegex(ValueError,"client receipt precedes"):
            evaluate(q=book(client_received_at_utc=START))

    def test_quote_receipt_cannot_be_a_future_observation(self):
        with self.assertRaisesRegex(ValueError,"future of review"):
            evaluate(asof=START+MS)

    def test_stale_two_second_quote_rejected(self):
        r=evaluate(q=book(client_received_at_utc=START+timedelta(seconds=3)),
                   asof=START+timedelta(seconds=4))
        self.assertEqual(r["disposition"],"REJECT_STALE_QUOTE_DELIVERY")
        self.assertEqual(r["quote_delivery_lag_ms"],"2900.0")

    def test_delivery_lag_two_seconds_is_boundary_not_tuned(self):
        r=evaluate(q=book(client_received_at_utc=START+timedelta(seconds=2, milliseconds=100)),
                   asof=START+timedelta(seconds=3))
        self.assertEqual(r["disposition"],
                         "ADVISORY_QUOTED_PRICE_PATH_ONLY_NOT_EXECUTABLE")

    def test_not_a_next_bar_after_bar_ends(self):
        with self.assertRaisesRegex(ValueError,"after next 15m"):
            evaluate(q=book(market_quoted_at_utc=START+timedelta(minutes=15),
                            client_received_at_utc=START+timedelta(minutes=15)),
                     asof=START+timedelta(minutes=15))

    def test_inspection_must_be_before_next_bar_closes(self):
        with self.assertRaisesRegex(ValueError,"after next 15m"):
            evaluate(asof=START+timedelta(minutes=15))

    def test_ohlc_after_signal_not_accepted_or_required(self):
        book_with_future=book()
        book_with_future["future_bars"]=[{"high":"1000000","low":"1","open":"1","close":"1"}]
        r=evaluate(q=book_with_future)
        clean=evaluate()
        self.assertEqual(r["quote_and_decision_sha256"],clean["quote_and_decision_sha256"])
        self.assertIsNone(r["observed_trade_pnl"])
        self.assertEqual(r["exit_bars_consulted"],0)

    def test_decision_after_prospective_window_rejected(self):
        with self.assertRaisesRegex(ValueError,"outside fixed future"):
            evaluate(o=event(decision_close_utc=datetime(2026,11,16,tzinfo=timezone.utc)))

    def test_wrong_market_pair_quote_fails(self):
        with self.assertRaisesRegex(ValueError,"source symbol mismatches"):
            evaluate(q=book(symbol="ETHUSDT"))

    def test_no_causal_source_boolean_or_first_breakout(self):
        for name in ("source_bound_seven_pivot","closed_first_breakout",
                     "post_correction_path_valid"):
            with self.subTest(name=name),self.assertRaisesRegex(
                ValueError,"causal seven-pivot"
            ):
                evaluate(o=event(**{name:False}))

    def test_quote_fingerprint_changes_with_bid_or_timestamp(self):
        a=evaluate()
        b=evaluate(q=book(best_bid="112.1"))
        c=evaluate(q=book(market_quoted_at_utc=START+timedelta(milliseconds=110)))
        self.assertNotEqual(a["quote_and_decision_sha256"],b["quote_and_decision_sha256"])
        self.assertNotEqual(a["quote_and_decision_sha256"],c["quote_and_decision_sha256"])


if __name__=="__main__":
    unittest.main()
