"""V117 synthetic predeclared comparison; never tune on July 2024 prices."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v106_early_partial import synthetic,pivot,MIN
from research.elliott_v117_alternative_grammar import grammar_v117 as v117
from research.elliott_v107_prefix_census import census_v107 as v107


def fabricate_counts(count1=4,count2=2,bearish=False):
    coarse,old_fine,t=synthetic(bearish)
    ends=(30,40,50)
    fine=[pivot(coarse[3].kind,30,coarse[3].center_close,1)]
    for start,end,count,endpoint in (
        (30,40,count1,coarse[4]),(40,50,count2,coarse[5])):
        if count>=end-start:
            raise ValueError("not enough 1m precision for synthetic turns")
        for j in range(count):
            ix=start+(j+1)*(end-start)//(count+1)
            next_kind=("HIGH" if fine[-1].kind=="LOW" else "LOW")
            fine.append(pivot(next_kind,ix,100+ix,1))
        fine.append(pivot(endpoint.kind,end,endpoint.center_close,1))
    return coarse,fine,t


def flags(out):
    return [out["arms"][name]["necessary_partial_geometry_pass"]
            for name,_,_ in v117.ARMS]


class V117FrozenAlternativePartialGrammar(unittest.TestCase):
    def test_exact_original_4_2_passes_all_predeclared_arms(self):
        coarse,fine,t=fabricate_counts(4,2)
        x=v117.compare_one(coarse,fine,t)
        self.assertEqual(flags(x),[True,True,True])
        self.assertEqual(x["original_v106_all_failures"],[])
        self.assertFalse(x["certified_elliott_wave"])

    def test_six_wave1_two_wave2_fine_turns_predeclared_near_admits(self):
        coarse,fine,t=fabricate_counts(6,2)
        x=v117.compare_one(coarse,fine,t)
        self.assertEqual(flags(x),[False,True,True])
        self.assertEqual(x["arms"][v117.ARMS[0][0]][
            "failure_codes"],["WAVE1_UNPRUNED_FINE_COUNT_NOT_PREDECLARED"])

    def test_eight_wave1_two_wave2_requires_broad_exploratory_arm(self):
        coarse,fine,t=fabricate_counts(8,2)
        self.assertEqual(flags(v117.compare_one(coarse,fine,t)),
                         [False,False,True])

    def test_wave2_four_interior_exploratory_arm_preserves_other_rules(self):
        coarse,fine,t=fabricate_counts(4,4)
        self.assertEqual(flags(v117.compare_one(coarse,fine,t)),
                         [False,True,True])

    def test_wave2_six_only_broad_allowed(self):
        coarse,fine,t=fabricate_counts(4,6)
        self.assertEqual(flags(v117.compare_one(coarse,fine,t)),
                         [False,False,True])

    def test_wave1_2_wave2_2_alt_near_pass_not_control(self):
        coarse,fine,t=fabricate_counts(2,2)
        self.assertEqual(flags(v117.compare_one(coarse,fine,t)),
                         [False,True,True])

    def test_noncount_origin_breach_refuses_all_even_if_count_near_matches(self):
        coarse,fine,t=fabricate_counts(6,2)
        coarse[-1]=replace(coarse[-1],center_close=D("99"))
        fine[-1]=replace(fine[-1],center_close=D("99"))
        x=v117.compare_one(coarse,fine,t)
        self.assertEqual(flags(x),[False,False,False])
        self.assertIn("WAVE2_BREACHES_OR_TOUCHES_WAVE0_ORIGIN",
                      x["original_v106_all_failures"])

    def test_wrong_context_lower_high_refuses_all(self):
        coarse,fine,t=fabricate_counts(6,2)
        coarse[2]=replace(coarse[2],center_close=D("135"))
        x=v117.compare_one(coarse,fine,t)
        self.assertEqual(flags(x),[False,False,False])
        self.assertIn("PRIOR_TREND_LOWER_HIGH_NOT_ATTESTED",
                      x["original_v106_all_failures"])

    def test_boundary_price_mismatch_cannot_be_relaxed(self):
        coarse,fine,t=fabricate_counts(6,2)
        fine[-1]=replace(fine[-1],center_close=D("109"))
        x=v117.compare_one(coarse,fine,t)
        self.assertEqual(flags(x),[False,False,False])
        self.assertIn("WAVE2_RIGHT_CAUSAL_FINE_BOUNDARY_MISMATCH",
                      x["original_v106_all_failures"])

    def test_fine_event_only_confirmed_after_decision_refused(self):
        coarse,fine,t=fabricate_counts(6,2)
        fine[-1]=replace(fine[-1],confirmed_ms=t+MIN,confirmed_index=53)
        with self.assertRaises(ValueError):
            v117.compare_one(coarse,fine,t)

    def test_wrong_decision_cutoff_refused_not_future_retrofit(self):
        coarse,fine,t=fabricate_counts()
        with self.assertRaisesRegex(ValueError,"right-confirmation"):
            v117.compare_one(coarse,fine,t+MIN)

    def test_complete_one_window_denominator_and_control_equal_v107(self):
        coarse,fine,t=fabricate_counts(6,2)
        out=v117.compare_all(fine,coarse,t)
        baseline=v107.enumerate_event_prefixes(fine,coarse,t)
        self.assertEqual(out["all_original_unpruned_six_event_windows"],1)
        self.assertEqual(out["original_v107_necessary_passes"],
                         baseline["necessary_partial_skeleton_passes"])
        self.assertEqual(list(out["all_predeclared_arm_necessary_passes"].values()),
                         [0,1,1])
        self.assertEqual(len(out["all_original_candidate_arms"]),1)
        self.assertEqual(out["elliott_degree_certificates"],0)
        self.assertIsNone(out["net_pnl"])

    def test_multiple_family_counts_not_assumed_independent_market_truth(self):
        coarse,fine,t=fabricate_counts(8,2)
        out=v117.compare_all(fine,coarse,t)
        self.assertTrue(out["each_arm_same_denominator"])
        self.assertEqual(sum(out["mutually_exclusive_arm_pass_combinations"].values()),1)
        self.assertTrue(out["no_trading_performance_measurements"])
        self.assertEqual(out["orders"],0)

    def test_source_with_less_than_six_coarse_has_no_invented_candidates(self):
        coarse,fine,t=fabricate_counts()
        out=v117.compare_all(fine,coarse[:5],t)
        self.assertEqual(out["all_original_unpruned_six_event_windows"],0)
        self.assertEqual(out["all_original_candidate_arms"],[])

    def test_control_failure_order_remains_exact_even_multiple_errors(self):
        coarse,fine,t=fabricate_counts(6,4)
        coarse[2]=replace(coarse[2],center_close=D("132"))
        x=v117.compare_one(coarse,fine,t)
        self.assertEqual(x["arms"][v117.ARMS[0][0]]["failure_codes"],
                         x["original_v106_all_failures"])
        self.assertFalse(any(flags(x)))

    def test_original_alternation_cannot_be_faked_with_odd_fine_count(self):
        coarse,fine,t=fabricate_counts(3,2)
        with self.assertRaises(ValueError):
            v117.compare_one(coarse,fine,t)

    def test_full_future_period_hard_date_gate_before_source_read(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(v117,"datetime",wraps=datetime) as fake:
                fake.now.return_value=datetime(2026,10,17,tzinfo=timezone.utc)
                with patch.object(v107,"evaluate_future_sealed_archive") as source:
                    with self.assertRaisesRegex(ValueError,"NO_ARCHIVE_READ"):
                        v117.evaluate_future_sealed_archive(Path(td))
                    source.assert_not_called()

    def test_frozen_no_market_preregistration_cannot_be_rewritten(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"V117_RULEBOOK.json"
            receipt=v117.freeze(path)
            self.assertEqual(receipt,v117.freeze(path))
            self.assertEqual(receipt["market_rows"],0)
            original=json.loads(path.read_text())
            self.assertEqual(original["source_market_candles_examined_during_v117"],0)
            self.assertEqual(original["orders"],0)
            self.assertEqual(len(original["arms"]),3)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"RULEBOOK CHANGED"):
                v117.freeze(path)

    def test_source_is_not_bybit_execution_and_live_is_disabled(self):
        p=v117.protocol()
        self.assertTrue(p["no_independent_market_elliott_truth_labels"])
        self.assertTrue(p["historical_july_2024_market_returns_not_used_to_choose_alternatives"])
        self.assertIsNone(v117.ORDER_ADAPTER)
        self.assertFalse(v117.PAPER_ELIGIBLE)
        self.assertFalse(v117.LIVE_ENABLED)
        self.assertTrue(v117.V52_UNCHANGED)
