"""V24 Elliott entry/exit safety tests. All OHLC is synthetic, NOT Bybit data."""
import unittest
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import patch

import nexus_elliott_entry_exit_integrity_v24 as qa
from nexus_elliott_prospective_exit_v17 import evaluate_prospective_study

DECISION=datetime(2026,10,16,0,15,tzinfo=timezone.utc)

def event(**override):
    obj={
        "symbol":"BTCUSDT", "event_id":"SYNTHETIC-EVENT-1",
        "decision_close_utc":DECISION, "previous_close":"109",
        "decision_close":"112", "fifth_high":"110",
        "correction_low":"100", "source_bound_seven_pivot":True,
        "closed_first_breakout":True,"post_correction_path_valid":True,
    }
    obj.update(override)
    return obj

def bar(i=0,**kwargs):
    a={"open_at":DECISION+timedelta(minutes=i*15),
       "open":"112","high":"113","low":"111","close":"112"}
    a.update(kwargs)
    return a

def run(rows=None,profile="conservative",obs=None,at=None,receipt=None):
    if rows is None:
        rows=[bar()]
    return qa.audit_single(
        event() if obs is None else obs,rows,profile=profile,
        observed_at_utc=at if at is not None else rows[-1]["open_at"]+timedelta(minutes=15),
        supplied_v17_receipt=receipt,
    )


class ElliottV24EntryExitIntegrityTests(unittest.TestCase):
    def test_no_trading_authority_or_recursive_wave_claim(self):
        self.assertTrue(qa.RESEARCH_ONLY)
        for flag in (qa.LIVE_ENABLED,qa.AUTO_DEMO,qa.PAPER_ELIGIBLE,
                     qa.CAN_PLACE_ORDER,qa.TUNES_ENTRY_EXIT_USING_HISTORICAL_PNL,
                     qa.RECURSIVE_ELLIOTT_COUNT_PROVEN):
            self.assertFalse(flag)
        self.assertEqual(set(qa.COST_PROFILES_FROZEN),{"conservative","stress"})

    def test_clean_pending_is_not_fabricated_winner_or_zero_loss(self):
        x=run()
        self.assertEqual(x["v17_hypothetical_status_unmodified"],
                         "AWAITING_MORE_CLOSED_BARS")
        self.assertIsNone(x["v17_hypothetical_net_pnl_unmodified"])
        self.assertIn("NO_FULLY_OBSERVED_EXIT_PENDING_NOT_ZERO_PNL",x["warning_codes"])
        self.assertFalse(x["paper_eligible"])

    def test_next_open_falls_back_below_breakout_level(self):
        x=run([bar(open="109",high="112",low="108",close="111")])
        self.assertIn("NEXT_OPEN_REENTERED_PRE_BREAKOUT_RANGE",x["warning_codes"])
        self.assertEqual(x["next_open_minus_breakout_high"],"-1")
        self.assertEqual(x["v17_hypothetical_status_unmodified"],
                         "AWAITING_MORE_CLOSED_BARS")

    def test_next_open_equal_breakout_level_also_warns(self):
        x=run([bar(open="110",high="112",low="109",close="111")])
        self.assertIn("NEXT_OPEN_REENTERED_PRE_BREAKOUT_RANGE",x["warning_codes"])

    def test_valid_next_open_over_breakout_not_falsely_warned(self):
        x=run()
        self.assertNotIn("NEXT_OPEN_REENTERED_PRE_BREAKOUT_RANGE",x["warning_codes"])

    def test_next_open_below_correction_refuses_entry(self):
        x=run([bar(open="99",high="112",low="98",close="108")])
        self.assertIn("NEXT_OPEN_INVALIDATES_CORRECTION_STOP_NO_ENTRY",x["warning_codes"])
        self.assertEqual(x["v17_hypothetical_status_unmodified"],
                         "NO_ENTRY_OPEN_AT_OR_BELOW_CORRECTION")
        self.assertIsNone(x["v17_hypothetical_net_pnl_unmodified"])

    def test_both_stop_and_target_in_first_bar_is_stop_first(self):
        x=run([bar(high="145",low="99")])
        self.assertEqual(x["v17_hypothetical_exit_reason_unmodified"],"stop")
        self.assertIn("BOTH_STOP_AND_TARGET_INSIDE_CANDLE_STOP_FIRST",x["warning_codes"])
        self.assertIn("STOP_TOUCHED_INSIDE_ENTRY_CANDLE_ORDER_UNOBSERVED",x["warning_codes"])
        self.assertLess(Decimal(x["v17_hypothetical_net_pnl_unmodified"]),0)

    def test_immediate_target_positive_is_still_research_quarantine(self):
        x=run([bar(high="145")])
        self.assertEqual(x["v17_hypothetical_exit_reason_unmodified"],"target")
        self.assertGreater(Decimal(x["v17_hypothetical_net_pnl_unmodified"]),0)
        self.assertEqual(x["audit_status"],"RESEARCH_QUARANTINED_NO_PROMOTION")
        self.assertIn("FULL_RECURSIVE_ELLIOTT_5_3_5_3_5_NOT_CERTIFIED",x["warning_codes"])
        self.assertFalse(x["source_market_authenticity_verified_here"])
        self.assertEqual(x["orders_placed"],0)

    def test_gap_through_stop_is_worse_than_stated_stop(self):
        x=run([bar(),bar(1,open="95",high="110",low="94",close="100")])
        self.assertEqual(x["v17_hypothetical_exit_reason_unmodified"],"stop")
        self.assertIn("STOP_GAP_OPEN_WORSE_THAN_STRUCTURAL_LEVEL",x["warning_codes"])
        self.assertLess(Decimal(x["v17_hypothetical_net_pnl_unmodified"]),Decimal("-10"))

    def test_favorable_gap_capped_target_no_extra_free_profit(self):
        x=run([bar(),bar(1,open="145",high="146",low="141",close="145")])
        self.assertEqual(x["v17_hypothetical_exit_reason_unmodified"],"target")
        self.assertIn("FAVORABLE_GAP_PROFIT_CAPPED_AT_TARGET",x["warning_codes"])

    def test_time_limit_64th_complete_candle(self):
        x=run([bar(i) for i in range(64)])
        self.assertEqual(x["v17_hypothetical_exit_reason_unmodified"],"time_limit")
        self.assertIn("TIME_LIMIT_EXIT_AT_LAST_CLOSED_BAR",x["warning_codes"])

    def test_incomplete_63_candles_not_time_exit(self):
        x=run([bar(i) for i in range(63)])
        self.assertEqual(x["v17_hypothetical_status_unmodified"],
                         "AWAITING_MORE_CLOSED_BARS")
        self.assertIsNone(x["v17_hypothetical_net_pnl_unmodified"])

    def test_conservative_and_stress_independent_ledger(self):
        closed=[bar(high="145")]
        for profile in ("conservative","stress"):
            with self.subTest(profile=profile):
                x=run(closed,profile=profile)
                self.assertTrue(x["friction_reconciled"])
                self.assertTrue(x["entry_model_validated"])
                self.assertTrue(x["exit_model_validated"])

    def test_forged_profit_receipt_refused(self):
        bars=[bar(high="145",low="99")]
        receipt=evaluate_prospective_study(
            event(),bars,profile="conservative",
            observed_at_utc=DECISION+timedelta(minutes=15))
        fake=deepcopy(receipt)
        fake["net_pnl"]="999999"
        with self.assertRaisesRegex(ValueError,"differs from canonical"):
            run(bars,receipt=fake)

    def test_forged_exit_reason_refused(self):
        bars=[bar(high="145",low="99")]
        receipt=evaluate_prospective_study(
            event(),bars,profile="conservative",
            observed_at_utc=DECISION+timedelta(minutes=15))
        fake=deepcopy(receipt)
        fake["exit_reason"]="target"
        with self.assertRaisesRegex(ValueError,"differs from canonical"):
            run(bars,receipt=fake)

    def test_exact_canonical_receipt_is_admissible_for_audit_only(self):
        bars=[bar(high="145")]
        receipt=evaluate_prospective_study(
            event(),bars,profile="conservative",
            observed_at_utc=DECISION+timedelta(minutes=15))
        x=run(bars,receipt=receipt)
        self.assertEqual(x["v17_hypothetical_net_pnl_unmodified"],receipt["net_pnl"])

    def test_corrupted_internal_ledger_can_not_be_certified(self):
        bars=[bar(high="145")]
        original=evaluate_prospective_study
        def fake(*args,**kwargs):
            obj=original(*args,**kwargs)
            obj["entry_fee"]="1"
            return obj
        with patch.object(qa,"evaluate_prospective_study",side_effect=fake):
            with self.assertRaisesRegex(ValueError,"independent ledger mismatch"):
                run(bars)

    def test_future_unclosed_bar_rejected(self):
        with self.assertRaisesRegex(ValueError,"forming/unavailable"):
            run([bar(),bar(1)],at=DECISION+timedelta(minutes=15))

    def test_discontinuous_future_source_rejected(self):
        with self.assertRaisesRegex(ValueError,"contiguous"):
            run([bar(),bar(2)])

    def test_duplicate_event_id_profile_rejected(self):
        request={"observation":event(),"closed_future_bars":[bar()],
                 "profile":"conservative",
                 "observed_at_utc":DECISION+timedelta(minutes=15)}
        with self.assertRaisesRegex(ValueError,"duplicate"):
            qa.audit_unique_batch([request,request])

    def test_same_symbol_decision_cannot_double_count_with_new_id(self):
        req={"observation":event(),"closed_future_bars":[bar()],
             "profile":"conservative",
             "observed_at_utc":DECISION+timedelta(minutes=15)}
        two={**req,"observation":event(event_id="SYNTHETIC-EVENT-2")}
        with self.assertRaisesRegex(ValueError,"duplicate"):
            qa.audit_unique_batch([req,two])

    def test_different_fee_profiles_preserved_without_double_count(self):
        req={"observation":event(),"closed_future_bars":[bar(high="145")],
             "observed_at_utc":DECISION+timedelta(minutes=15)}
        out=qa.audit_unique_batch([
            {**req,"profile":"conservative"}, {**req,"profile":"stress"}])
        self.assertEqual(len(out),2)
        self.assertGreater(Decimal(out[0]["v17_hypothetical_net_pnl_unmodified"]),
                           Decimal(out[1]["v17_hypothetical_net_pnl_unmodified"]))
        self.assertTrue(all(not z["paper_eligible"] for z in out))


if __name__=="__main__":
    unittest.main()
