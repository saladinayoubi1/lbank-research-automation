"""V108 synthetic barrier observations; ZERO real market source or orders."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v106_early_partial import synthetic, MIN
from research.elliott_v102_bybit_intake.intake_v102 import Candle
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v108_forward_outcomes import outcomes_v108 as v108

def bar(at,opening=110,high=115,low=105,close=110):
    return Candle(at,D(str(opening)),D(str(high)),D(str(low)),
                  D(str(close)),D("1"),D("100"))


def follow(asof,n=240,first=None):
    candles=[bar(asof+i*MIN) for i in range(n)]
    if first is not None:
        candles[0]=first
    return candles


class V108ForwardBarrierTests(unittest.TestCase):
    def test_bull_wave1_barrier_first_after_causal_wave2(self):
        coarse,_,t=synthetic()
        b=follow(t,240,bar(t,110,130,105,112))
        x=v108.first_barrier_outcome(coarse,t,b,t+240*MIN)
        self.assertEqual(x["outcome"],"WAVE1_BARRIER_FIRST")
        self.assertEqual(x["first_touch_lag_completed_minutes"],1)
        self.assertFalse(x["actual_entry_filled"])
        self.assertFalse(x["trade_opened"])
        self.assertIsNone(x["net_pnl"])

    def test_origin_barrier_first(self):
        coarse,_,t=synthetic()
        x=v108.first_barrier_outcome(
            coarse,t,follow(t,240,bar(t,110,115,90,101)),t+240*MIN)
        self.assertEqual(x["outcome"],"WAVE0_ORIGIN_FIRST")

    def test_both_same_one_minute_treat_as_invalidation_first(self):
        coarse,_,t=synthetic()
        x=v108.first_barrier_outcome(
            coarse,t,follow(t,240,bar(t,110,130,90,110)),t+240*MIN)
        self.assertEqual(x["outcome"],"SAME_MINUTE_BOTH_ASSUME_ORIGIN_FIRST")
        self.assertTrue(x["simultaneous_touch_not_counted_as_breakout"])

    def test_complete_four_hour_no_touch_unresolved(self):
        coarse,_,t=synthetic()
        x=v108.first_barrier_outcome(coarse,t,follow(t),t+240*MIN)
        self.assertEqual(x["outcome"],"NO_BARRIER_BY_240_CLOSED_MINUTES")
        self.assertIsNone(x["first_touch_lag_completed_minutes"])
        self.assertEqual(x["up_to_closed_followup_minutes_observed"],240)

    def test_last_two_minutes_no_hit_is_right_censored(self):
        coarse,_,t=synthetic()
        x=v108.first_barrier_outcome(coarse,t,follow(t,2),t+2*MIN)
        self.assertEqual(x["outcome"],"RIGHT_CENSORED_AFTER_SOURCE_END")
        self.assertNotEqual(x["outcome"],"NO_BARRIER_BY_240_CLOSED_MINUTES")

    def test_touch_before_window_end_is_still_observable_even_if_followup_short(self):
        coarse,_,t=synthetic()
        x=v108.first_barrier_outcome(
            coarse,t,follow(t,2,bar(t,110,130,105,112)),t+2*MIN)
        self.assertEqual(x["outcome"],"WAVE1_BARRIER_FIRST")

    def test_invalid_wave1_geometry_is_noncomparable_not_fabricated_winner(self):
        coarse,_,t=synthetic()
        coarse[4]=replace(coarse[4],center_close=D("99"))
        x=v108.first_barrier_outcome(coarse,t,follow(t),t+240*MIN)
        self.assertEqual(x["outcome"],"NONCOMPARABLE_GEOMETRY")

    def test_bearish_first_barrier_mirrored(self):
        coarse,_,t=synthetic(True)
        b=follow(t,240,bar(t,220,225,205,215))
        x=v108.first_barrier_outcome(coarse,t,b,t+240*MIN)
        self.assertEqual(x["outcome"],"WAVE1_BARRIER_FIRST")
        self.assertEqual(x["hypothesis_direction"],"DOWN")

    def test_bearish_same_bar_both_is_invalidated(self):
        coarse,_,t=synthetic(True)
        b=follow(t,240,bar(t,220,240,190,215))
        x=v108.first_barrier_outcome(coarse,t,b,t+240*MIN)
        self.assertEqual(x["outcome"],"SAME_MINUTE_BOTH_ASSUME_ORIGIN_FIRST")

    def test_no_entry_before_wave2_right_confirmation(self):
        coarse,_,t=synthetic()
        with self.assertRaisesRegex(ValueError,"not wave2 causal"):
            v108.first_barrier_outcome(coarse,t-MIN,follow(t),t+240*MIN)

    def test_wrong_start_postdecision_minute_rejected(self):
        coarse,_,t=synthetic()
        with self.assertRaisesRegex(ValueError,"offset"):
            v108.first_barrier_outcome(
                coarse,t,follow(t+MIN),t+241*MIN)

    def test_duplicate_or_gap_source_rejected(self):
        coarse,_,t=synthetic()
        bars=follow(t)
        bars[1]=replace(bars[1],ms=t)
        with self.assertRaisesRegex(ValueError,"gap/duplicate"):
            v108.first_barrier_outcome(coarse,t,bars,t+240*MIN)

    def test_partial_source_not_matching_declared_end_is_rejected(self):
        coarse,_,t=synthetic()
        with self.assertRaisesRegex(ValueError,"missing original"):
            v108.first_barrier_outcome(coarse,t,follow(t,3),t+240*MIN)

    def test_corrupted_unclosed_ohlc_rejected(self):
        coarse,_,t=synthetic()
        with self.assertRaisesRegex(ValueError,"unphysical"):
            v108.first_barrier_outcome(coarse,t,follow(t,240,
                bar(t,110,100,90,105)),t+240*MIN)

    def test_nan_price_rejected(self):
        coarse,_,t=synthetic()
        with self.assertRaisesRegex(ValueError,"invalid nonfinite"):
            v108.first_barrier_outcome(coarse,t,follow(t,240,
                bar(t,110,"NaN",105,110)),t+240*MIN)

    def test_excessive_future_bars_refused(self):
        coarse,_,t=synthetic()
        with self.assertRaisesRegex(ValueError,"bounded"):
            v108.first_barrier_outcome(coarse,t,follow(t,241),t+241*MIN)

    def test_all_passed_candidates_in_original_denominator(self):
        coarse,fine,t=synthetic()
        original=v107.enumerate_event_prefixes(fine,coarse,t)
        scored=v108.assess_every_v107_window(original,coarse,follow(t,240))
        self.assertEqual(scored["original_v107_candidate_count"],1)
        self.assertEqual(scored["original_v107_gate_passes"],1)
        self.assertEqual(scored["outcome_group_tallies"]["necessary_pass"],
                         {"NO_BARRIER_BY_240_CLOSED_MINUTES":1})
        self.assertEqual(scored["outcome_group_tallies"]["necessary_reject"],{})
        self.assertEqual(scored["separate_forward_only_outcome_ledger"][0][
            "original_decision_asof_ms"],t)
        self.assertIsNone(scored["trade_win_rate"])

    def test_all_rejected_candidates_still_in_original_denominator(self):
        coarse,fine,t=synthetic()
        coarse[2]=replace(coarse[2],center_close=coarse[0].center_close)
        original=v107.enumerate_event_prefixes(fine,coarse,t)
        scored=v108.assess_every_v107_window(original,coarse,follow(t,240))
        self.assertEqual(scored["original_v107_gate_rejections"],1)
        self.assertEqual(sum(scored["outcome_group_tallies"]["necessary_reject"].values()),1)
        self.assertFalse(scored["separate_forward_only_outcome_ledger"][0][
            "original_gate_pass"])
        self.assertFalse(scored["paper_eligible"])

    def test_original_v107_candidate_fingerprint_mismatch_rejected(self):
        coarse,fine,t=synthetic()
        original=v107.enumerate_event_prefixes(fine,coarse,t)
        original["candidate_ledger"][0]["coarse_window_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"changed"):
            v108.assess_every_v107_window(original,coarse,follow(t,240))

    def test_original_v107_pass_flag_cannot_be_falsified(self):
        coarse,fine,t=synthetic()
        original=v107.enumerate_event_prefixes(fine,coarse,t)
        original["candidate_ledger"][0]["necessary_partial_skeleton_pass"]=False
        with self.assertRaisesRegex(ValueError,"changed"):
            v108.assess_every_v107_window(original,coarse,follow(t,240))

    def test_future_beyond_horizon_cannot_change_original_outcome(self):
        coarse,fine,t=synthetic()
        original=v107.enumerate_event_prefixes(fine,coarse,t)
        a=v108.assess_every_v107_window(original,coarse,follow(t,240))
        extra=follow(t,241)
        extra[240]=bar(t+240*MIN,110,130,90,110)
        b=v108.assess_every_v107_window(original,coarse,extra)
        self.assertEqual(a,b)

    def test_future_window_forbidden_without_reading_before_nov30(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(v108,"datetime",wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,17,tzinfo=timezone.utc)
                with patch.object(v107,"evaluate_future_sealed_archive") as audit:
                    with self.assertRaisesRegex(ValueError,"NO_ARCHIVE_READ"):
                        v108.evaluate_future_archive_only(Path(temp))
                    audit.assert_not_called()

    def test_write_once_plan_and_frozen_upstream(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/"V108_FROZEN.json"
            before=v108.freeze_rulebook(target)
            self.assertEqual(before,v108.freeze_rulebook(target))
            self.assertEqual(before["real_market_rows_observed"],0)
            self.assertEqual(before["trades"],0)
            target.write_text("{}")
            with self.assertRaisesRegex(ValueError,"modified"):
                v108.freeze_rulebook(target)

    def test_no_market_elliott_ground_truth_or_demo_fill(self):
        p=v108.plan()
        self.assertEqual(p["fixed_followup_closed_one_minute_bars"],240)
        self.assertTrue(p["no_real_elliott_ground_truth_labels"])
        self.assertTrue(p["no_false_positive_rate_or_win_rate_computed"])
        self.assertFalse(p["live_enabled"])
        self.assertFalse(p["paper_eligible"])
        self.assertIsNone(v108.ORDER_ADAPTER)
        self.assertTrue(v108.V52_UNCHANGED)
