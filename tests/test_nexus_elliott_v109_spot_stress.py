"""V109 source-free synthetic spot-long latency and cost stress tests."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v106_early_partial import synthetic,MIN
from test_nexus_elliott_v108_forward_outcomes import bar,follow
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v108_forward_outcomes import outcomes_v108 as v108
from research.elliott_v109_spot_stress import stress_v109 as v109


def one(bars=None,bear=False,reject=False):
    six,fine,t=synthetic(bear)
    if reject:
        six[2]=replace(six[2],center_close=six[0].center_close)
    candle_list=bars if bars is not None else follow(t)
    return six,fine,t,candle_list


def evaluate(six,t,bars):
    return v109.stress_one_synthetic_window(
        six,True,bars,t,t+len(bars)*MIN)


class V109CostStressDiagnostics(unittest.TestCase):
    def test_long_target_touch_is_net_stress_not_actual_profit(self):
        six,fine,t,_=one()
        bars=follow(t)
        bars[1]=bar(t+MIN,110,122,105,117)
        out=evaluate(six,t,bars)
        self.assertEqual(out["category"],"STRESS_WAVE1_TARGET_TOUCH")
        self.assertGreater(D(out["illustrative_net_R_after_fixed_cost_stress"]),0)
        self.assertLess(D(out["illustrative_net_R_after_fixed_cost_stress"]),1)
        self.assertFalse(out["real_fill_or_fee_verified"])
        self.assertFalse(out["entry_signal"])
        self.assertIsNone(out["actual_net_pnl"])

    def test_stop_long_is_net_worse_than_minus_one_r_due_to_two_side_cost(self):
        six,fine,t,_=one()
        bars=follow(t)
        bars[1]=bar(t+MIN,110,115,95,105)
        out=evaluate(six,t,bars)
        self.assertEqual(out["category"],"STRESS_ORIGIN_STOP_FIRST")
        self.assertLess(D(out["illustrative_net_R_after_fixed_cost_stress"]),D("-1"))

    def test_same_bar_stop_and_target_counts_as_stop_even_close_is_high(self):
        six,fine,t,_=one()
        bars=follow(t)
        bars[1]=bar(t+MIN,110,122,95,119)
        out=evaluate(six,t,bars)
        self.assertEqual(out["category"],"STRESS_SAME_BAR_BOTH_ASSUME_STOP_FIRST")
        self.assertLess(D(out["illustrative_net_R_after_fixed_cost_stress"]),0)

    def test_gap_open_below_stop_after_entry_is_worse_than_stop(self):
        six,fine,t,_=one()
        bars=follow(t)
        bars[2]=bar(t+2*MIN,90,96,85,91)
        out=evaluate(six,t,bars)
        self.assertEqual(out["category"],"STRESS_ORIGIN_STOP_FIRST")
        self.assertEqual(out["hypothetical_barrier_exit_reference"],"90")
        self.assertLess(D(out["illustrative_net_R_after_fixed_cost_stress"]),D("-1.5"))

    def test_latency_barrier_touch_never_retrofits_entry(self):
        six,fine,t,_=one()
        for first in (bar(t,110,123,105,118),
                      bar(t,110,115,95,111),
                      bar(t,110,122,95,101)):
            with self.subTest(first=first):
                bars=follow(t,240,first)
                out=evaluate(six,t,bars)
                self.assertEqual(out["category"],"LATENCY_BARRIER_TOUCHED_ABSTAIN")
                self.assertIsNone(out["illustrative_net_R_after_fixed_cost_stress"])

    def test_first_delayed_open_past_target_or_stop_refuses_chasing(self):
        six,fine,t,_=one()
        for opening in (98,123):
            with self.subTest(opening=opening):
                bars=follow(t)
                if opening==98:
                    bars[1]=bar(t+MIN,98,115,95,110)
                else:
                    bars[1]=bar(t+MIN,123,125,105,110)
                out=evaluate(six,t,bars)
                self.assertEqual(out["category"],
                                 "SECOND_BAR_OPEN_OUTSIDE_STOP_TARGET_ABSTAIN")

    def test_fee_spread_slippage_stress_eliminates_near_target_reward(self):
        six,fine,t,_=one()
        bars=follow(t)
        bars[1]=bar(t+MIN,D("119.9"),120,110,D("119.95"))
        out=evaluate(six,t,bars)
        self.assertEqual(out["category"],"STRESS_COST_REMOVES_POSITIVE_REWARD")
        self.assertIsNone(out["illustrative_net_R_after_fixed_cost_stress"])

    def test_spot_short_abstains_though_price_path_may_be_observable(self):
        six,fine,t,_=one(bear=True)
        out=evaluate(six,t,follow(t))
        self.assertEqual(out["category"],"SPOT_SHORT_UNSUPPORTED_NO_BORROW_ASSUMED")
        self.assertIsNone(out["illustrative_net_R_after_fixed_cost_stress"])
        self.assertIsNone(out["actual_net_pnl"])

    def test_rejected_original_v107_candidate_is_not_newly_promoted(self):
        six,fine,t,_=one(reject=True)
        out=v109.stress_one_synthetic_window(six,False,follow(t),
                                             t,t+240*MIN)
        self.assertEqual(out["category"],"REJECTED_ORIGINAL_V107_GATE")
        self.assertIsNone(out["hypothetical_long_entry_after_stress"])

    def test_no_hit_full_240_bars_remains_open_without_realized_pnl(self):
        six,fine,t,_=one()
        out=evaluate(six,t,follow(t))
        self.assertEqual(out["category"],"STRESS_NO_EXIT_WITHIN_FIXED_HORIZON")
        self.assertIsNone(out["illustrative_net_R_after_fixed_cost_stress"])
        self.assertIsNone(out["actual_net_pnl"])

    def test_incomplete_followup_near_source_end_is_censored(self):
        six,fine,t,_=one()
        out=evaluate(six,t,follow(t,2))
        self.assertEqual(out["category"],"STRESS_RIGHT_CENSORED_UNCLOSED_POSITION")
        self.assertIsNone(out["illustrative_net_R_after_fixed_cost_stress"])

    def test_one_remaining_bar_cannot_provide_delayed_entry(self):
        six,fine,t,_=one()
        out=evaluate(six,t,follow(t,1))
        self.assertEqual(out["category"],"CENSORED_BEFORE_LATENCY_ENTRY")

    def test_no_future_ohlc_can_be_used_at_original_decision_time(self):
        six,fine,t,_=one()
        with self.assertRaisesRegex(ValueError,"missing original postdecision"):
            v109.stress_one_synthetic_window(six,True,follow(t,1),
                                             t,t+240*MIN)

    def test_wrong_wave2_cutoff_rejected(self):
        six,fine,t,_=one()
        with self.assertRaisesRegex(ValueError,"causal"):
            v109.stress_one_synthetic_window(
                six,True,follow(t),t-MIN,t+240*MIN)

    def test_bad_source_ohlc_rejected(self):
        six,fine,t,_=one()
        bars=follow(t)
        bars[1]=bar(t+MIN,110,105,90,103)
        with self.assertRaisesRegex(ValueError,"unphysical"):
            evaluate(six,t,bars)

    def test_whole_source_denominator_rejected_windows_preserved(self):
        six,fine,t,bars=one(reject=True)
        ledger=v107.enumerate_event_prefixes(fine,six,t)
        original=v108.assess_every_v107_window(ledger,six,bars)
        stress=v109.stress_every_original_window(ledger,original,six,bars)
        self.assertEqual(stress["all_original_v107_candidates"],1)
        self.assertEqual(stress["original_necessary_reject_count"],1)
        self.assertEqual(stress["status_by_original_gate"]["necessary_reject"],
                         {"REJECTED_ORIGINAL_V107_GATE":1})
        self.assertEqual(stress["orders"],0)

    def test_whole_source_passed_window_with_delayed_hypothetical_target(self):
        six,fine,t,bars=one()
        bars[1]=bar(t+MIN,110,122,105,117)
        ledger=v107.enumerate_event_prefixes(fine,six,t)
        observed=v108.assess_every_v107_window(ledger,six,bars)
        stress=v109.stress_every_original_window(ledger,observed,six,bars)
        self.assertEqual(stress["original_necessary_pass_count"],1)
        self.assertEqual(stress["status_by_original_gate"]["necessary_pass"],
                         {"STRESS_WAVE1_TARGET_TOUCH":1})
        self.assertTrue(stress["no_actual_net_pnl_or_win_rate"])

    def test_replaced_original_v108_observation_refused(self):
        six,fine,t,bars=one()
        ledger=v107.enumerate_event_prefixes(fine,six,t)
        observed=v108.assess_every_v107_window(ledger,six,bars)
        observed["separate_forward_only_outcome_ledger"][0][
            "forward_observation"]["outcome"]="WAVE1_BARRIER_FIRST"
        with self.assertRaisesRegex(ValueError,"REWRITTEN"):
            v109.stress_every_original_window(ledger,observed,six,bars)

    def test_replaced_original_pass_flag_refused(self):
        six,fine,t,bars=one()
        ledger=v107.enumerate_event_prefixes(fine,six,t)
        observed=v108.assess_every_v107_window(ledger,six,bars)
        ledger["candidate_ledger"][0]["necessary_partial_skeleton_pass"]=False
        with self.assertRaises(ValueError):
            v109.stress_every_original_window(ledger,observed,six,bars)

    def test_outcome_after_240_candles_does_not_revise_fixed_horizon(self):
        six,fine,t,bars=one()
        ledger=v107.enumerate_event_prefixes(fine,six,t)
        observed=v108.assess_every_v107_window(ledger,six,bars)
        result=v109.stress_every_original_window(ledger,observed,six,bars)
        extra=bars+[bar(t+240*MIN,110,130,90,105)]
        observed_extra=v108.assess_every_v107_window(ledger,six,extra)
        after=v109.stress_every_original_window(ledger,observed_extra,six,extra)
        self.assertEqual(result,after)

    def test_future_archive_gate_before_any_real_source_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v109,"datetime",wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,17,tzinfo=timezone.utc)
                with patch.object(v108,"evaluate_future_archive_only") as upstream:
                    with self.assertRaisesRegex(ValueError,"NO_ARCHIVE_READ"):
                        v109.evaluate_future_archive_only(Path(tmp))
                    upstream.assert_not_called()

    def test_frozen_cost_rate_and_no_broker(self):
        contract=v109.manifest()
        self.assertEqual(contract["fee_each_side_bps_assumed_not_verified_Bybit"],"10")
        self.assertEqual(contract["half_spread_each_side_bps_assumed"],"2")
        self.assertEqual(contract["slippage_each_side_bps_assumed"],"5")
        self.assertEqual(contract["latency_complete_one_minute_bars"],1)
        self.assertTrue(contract["short_market_context_kept_but_execution_abstains"])
        self.assertTrue(contract["no_false_positive_rate_or_win_rate_computed"]
                        if "no_false_positive_rate_or_win_rate_computed" in contract
                        else contract["not_measured"]!=[])
        self.assertFalse(contract["paper_eligible"])
        self.assertFalse(contract["live_enabled"])
        self.assertIsNone(v109.ORDER_ADAPTER)

    def test_frozen_original_v108_preregistration_is_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/"V109_RULEBOOK.json"
            receipt=v109.freeze_manifest(target)
            self.assertEqual(receipt,v109.freeze_manifest(target))
            self.assertEqual(receipt["market_rows_fetched"],0)
            self.assertEqual(receipt["actual_orders"],0)
            target.write_text("{}")
            with self.assertRaisesRegex(ValueError,"modified"):
                v109.freeze_manifest(target)

    def test_audited_v108_extra_source_receipts_retained_and_crosschecked(self):
        six,fine,t,bars=one()
        ledger=v107.enumerate_event_prefixes(fine,six,t)
        original=v108.assess_every_v107_window(ledger,six,bars)
        rows=[[c.ms,str(c.open),str(c.high),str(c.low),str(c.close),
               str(c.volume),str(c.turnover)] for c in bars]
        raw=v109.json.dumps(rows,ensure_ascii=False,separators=(",",":")).encode()
        original["source_candles"]=len(bars)
        original["physical_source_sha256"]=v109.hashlib.sha256(raw).hexdigest()
        original["authenticity_caveat"]=(
            "two_offline_parsers_same_archive_not_Bybit_payload_signature")
        out=v109.stress_every_original_window(ledger,original,six,bars)
        self.assertEqual(out["all_original_v107_candidates"],1)
        original["physical_source_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"audited provenance"):
            v109.stress_every_original_window(ledger,original,six,bars)

    def test_unrecognized_v108_added_field_refused_not_silently_ignored(self):
        six,fine,t,bars=one()
        ledger=v107.enumerate_event_prefixes(fine,six,t)
        original=v108.assess_every_v107_window(ledger,six,bars)
        original["secret_claim"]=True
        with self.assertRaisesRegex(ValueError,"REWRITTEN"):
            v109.stress_every_original_window(ledger,original,six,bars)
