"""V106 pure synthetic six-coarse-event / two-leg causal admission screen."""
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from research.elliott_v99_causal_scale.scale_v99 import ObservedSwing
from research.elliott_v102_bybit_intake.intake_v102 import Candle
from research.elliott_v106_early_partial import early_v106 as v106

BASE=1792368000000
MIN=60000


def pivot(kind,index,price,lag):
    return ObservedSwing(kind,BASE+index*MIN,BASE+(index+lag+1)*MIN,
                         D(str(price)),D(str(price)),index,index+lag)


def synthetic(bearish=False):
    indices=[0,10,20,30,40,50]
    prices=[200,220,205,230,210,220] if bearish else [130,110,125,100,120,110]
    labels=(["LOW","HIGH","LOW","HIGH","LOW","HIGH"] if bearish
            else ["HIGH","LOW","HIGH","LOW","HIGH","LOW"])
    coarse=[pivot(kind,i,p,2) for kind,i,p in zip(labels,indices,prices)]
    fine=[pivot(labels[3],indices[3],prices[3],1)]
    for leg,count in enumerate(v106.EARLY_LEG_FINE_COUNTS):
        start=indices[3+leg]
        last=indices[4+leg]
        for j in range(count):
            k=start+(j+1)*(last-start)//(count+1)
            next_kind="HIGH" if fine[-1].kind=="LOW" else "LOW"
            fine.append(pivot(next_kind,k,100+k,1))
        fine.append(pivot(labels[4+leg],last,prices[4+leg],1))
    return coarse,fine,coarse[-1].confirmed_ms


def bar(start,op,hi,lo,cl):
    return Candle(start,D(str(op)),D(str(hi)),D(str(lo)),D(str(cl)),
                  D("1"),D("100"))


class V106SyntheticPartialWaveTests(unittest.TestCase):
    def test_bullish_wave2_confirmed_skeleton_but_never_signal(self):
        coarse,fine,t=synthetic()
        x=v106.inspect_partial(coarse,fine,t)
        self.assertTrue(x["partial_skeleton_and_context_necessary_pass"])
        self.assertEqual(x["observed_unpruned_counts"],[4,2])
        self.assertEqual(x["rejections"],[])
        self.assertEqual(x["direction"],"UP")
        self.assertFalse(x["full_five_wave_observed"])
        self.assertFalse(x["elliott_degree_certified"])
        self.assertFalse(x["new_trade_entry_signal"])
        self.assertFalse(x["market_wave_position_proven"])

    def test_bearish_mirrored_partial_skeleton(self):
        coarse,fine,t=synthetic(True)
        x=v106.inspect_partial(coarse,fine,t)
        self.assertTrue(x["partial_skeleton_and_context_necessary_pass"])
        self.assertEqual(x["direction"],"DOWN")
        self.assertFalse(x["paper_eligible"])

    def test_w3_w4_w5_not_required_or_inputs(self):
        coarse,fine,t=synthetic()
        self.assertEqual(len(coarse),6)
        self.assertEqual(coarse[-1].center_index,50)
        self.assertTrue(v106.inspect_partial(coarse,fine,t)[
            "partial_skeleton_and_context_necessary_pass"])

    def test_forged_future_wave3_rejected_as_extra_coarse(self):
        coarse,fine,t=synthetic()
        extra=pivot("HIGH",60,140,2)
        with self.assertRaisesRegex(ValueError,"six"):
            v106.inspect_partial(coarse+[extra],fine,t)

    def test_backdated_wave2_confirmation_rejected(self):
        coarse,fine,t=synthetic()
        with self.assertRaisesRegex(ValueError,"equal wave2"):
            v106.inspect_partial(coarse,fine,t-MIN)

    def test_delayed_decision_refused_not_causal_w2(self):
        coarse,fine,t=synthetic()
        with self.assertRaisesRegex(ValueError,"equal wave2"):
            v106.inspect_partial(coarse,fine,t+MIN)

    def test_no_predecessor_context_rejected(self):
        coarse,fine,t=synthetic()
        with self.assertRaisesRegex(ValueError,"six"):
            v106.inspect_partial(coarse[3:],fine,t)

    def test_invalid_pretrend_lower_high_refused(self):
        coarse,fine,t=synthetic()
        coarse[2]=replace(coarse[2],center_close=D("131"))
        x=v106.inspect_partial(coarse,fine,t)
        self.assertIn("PRIOR_TREND_LOWER_HIGH_NOT_ATTESTED",x["rejections"])

    def test_invalid_prior_low_refused(self):
        coarse,fine,t=synthetic()
        coarse[1]=replace(coarse[1],center_close=D("99"))
        x=v106.inspect_partial(coarse,fine,t)
        self.assertIn("PRIOR_TREND_LOWER_LOW_NOT_ATTESTED",x["rejections"])

    def test_wave2_origin_breach_refused(self):
        coarse,fine,t=synthetic()
        coarse[5]=replace(coarse[5],center_close=D("99"))
        fine[-1]=replace(fine[-1],center_close=D("99"))
        x=v106.inspect_partial(coarse,fine,t)
        self.assertIn("WAVE2_BREACHES_OR_TOUCHES_WAVE0_ORIGIN",x["rejections"])

    def test_wave2_no_retracement_refused(self):
        coarse,fine,t=synthetic()
        coarse[5]=replace(coarse[5],center_close=D("122"))
        fine[-1]=replace(fine[-1],center_close=D("122"))
        x=v106.inspect_partial(coarse,fine,t)
        self.assertIn("WAVE2_NOT_A_STRICT_RETRACE_OF_WAVE1",x["rejections"])

    def test_pruning_fine_pivot_refused(self):
        coarse,fine,t=synthetic()
        subset=[e for e in fine if e.center_index!=32]
        with self.assertRaisesRegex(ValueError,"nonchronological or relabeled"):
            v106.inspect_partial(coarse,subset,t)

    def test_extra_fine_pivot_refused_no_posthoc_select(self):
        coarse,fine,t=synthetic()
        extra=pivot("HIGH",37,137,1)
        # insert in order, maintaining strict alternating fine directions:
        # replace two fine interior points by four extra turns instead.
        fine=[e for e in fine if e.center_index!=34 and e.center_index!=36]
        a=pivot("LOW",33,135,1)
        b=pivot("HIGH",34,135,1)
        c=pivot("LOW",35,134,1)
        d=pivot("HIGH",36,136,1)
        fine=sorted(fine+[a,b,c,d],key=lambda x:x.center_ms)
        x=v106.inspect_partial(coarse,fine,t)
        self.assertIn("WAVE1_UNPRUNED_FINE_COUNT_NOT_PREDECLARED",x["rejections"])

    def test_mismatched_fine_price_at_wave2_boundary_refused(self):
        coarse,fine,t=synthetic()
        fine[-1]=replace(fine[-1],center_close=D("111"))
        x=v106.inspect_partial(coarse,fine,t)
        self.assertIn("WAVE2_RIGHT_CAUSAL_FINE_BOUNDARY_MISMATCH",x["rejections"])

    def test_future_fine_confirmation_refused(self):
        coarse,fine,t=synthetic()
        fine[-1]=replace(fine[-1],confirmed_ms=t+MIN,confirmed_index=53)
        with self.assertRaisesRegex(ValueError,"future"):
            v106.inspect_partial(coarse,fine,t)

    def test_forged_source_index_or_epoch_refused(self):
        coarse,fine,t=synthetic()
        fine[1]=replace(fine[1],center_index=5)
        with self.assertRaisesRegex(ValueError,"index/time"):
            v106.inspect_partial(coarse,fine,t)

    def test_both_stop_and_target_assume_stop_first(self):
        coarse,fine,t=synthetic()
        x=v106.counterfactual_first_complete_minute(
            coarse,fine,bar(t,112,150,90,120),t+MIN)
        self.assertEqual(x["conservative_one_bar_outcome"],
                         "BOTH_LEVELS_TOUCHED_ASSUME_STOP_FIRST")
        self.assertEqual(x["hypothetical_stop_at_wave0_center"],"100")
        self.assertEqual(x["hypothetical_target_2r"],"136")
        self.assertFalse(x["entry_signal"])
        self.assertIsNone(x["net_pnl"])

    def test_only_stop_touched(self):
        coarse,fine,t=synthetic()
        x=v106.counterfactual_first_complete_minute(
            coarse,fine,bar(t,112,120,95,110),t+MIN)
        self.assertEqual(x["conservative_one_bar_outcome"],
                         "HYPOTHETICAL_STOP_TOUCHED")

    def test_only_target_touched(self):
        coarse,fine,t=synthetic()
        x=v106.counterfactual_first_complete_minute(
            coarse,fine,bar(t,112,140,110,120),t+MIN)
        self.assertEqual(x["conservative_one_bar_outcome"],
                         "HYPOTHETICAL_TARGET_TOUCHED")

    def test_no_first_bar_exit_cannot_claim_success(self):
        coarse,fine,t=synthetic()
        x=v106.counterfactual_first_complete_minute(
            coarse,fine,bar(t,112,125,110,115),t+MIN)
        self.assertEqual(x["conservative_one_bar_outcome"],
                         "NO_EXIT_SEEN_IN_FIRST_CLOSED_MINUTE")

    def test_wrong_side_gap_abstains(self):
        coarse,fine,t=synthetic()
        x=v106.counterfactual_first_complete_minute(
            coarse,fine,bar(t,98,150,90,110),t+MIN)
        self.assertIn("FIRST_OPEN_BEYOND_OR_AT_WAVE0_DEFENSIVE_STOP",x["rejections"])
        self.assertIsNone(x["hypothetical_target_2r"])

    def test_bearish_both_levels_assume_stop_first(self):
        coarse,fine,t=synthetic(True)
        x=v106.counterfactual_first_complete_minute(
            coarse,fine,bar(t,218,240,180,215),t+MIN)
        self.assertEqual(x["hypothetical_stop_at_wave0_center"],"230")
        self.assertEqual(x["hypothetical_target_2r"],"194")
        self.assertEqual(x["conservative_one_bar_outcome"],
                         "BOTH_LEVELS_TOUCHED_ASSUME_STOP_FIRST")

    def test_closed_bar_not_visible_at_earlier_time(self):
        coarse,fine,t=synthetic()
        with self.assertRaisesRegex(ValueError,"fully closed"):
            v106.counterfactual_first_complete_minute(
                coarse,fine,bar(t,112,140,110,115),t)

    def test_future_bar_cannot_be_used_as_immediate_next_bar(self):
        coarse,fine,t=synthetic()
        with self.assertRaisesRegex(ValueError,"equal wave2"):
            v106.counterfactual_first_complete_minute(
                coarse,fine,bar(t+MIN,112,140,110,115),t+2*MIN)

    def test_invalid_ohlc_or_nan_refused(self):
        coarse,fine,t=synthetic()
        for b in (bar(t,112,110,100,108),bar(t,112,140,110,"NaN")):
            with self.assertRaisesRegex(ValueError,"source|OHLC"):
                v106.counterfactual_first_complete_minute(coarse,fine,b,t+MIN)

    def test_no_broker_or_historical_market_claims(self):
        self.assertTrue(v106.RESEARCH_ONLY)
        self.assertTrue(v106.V52_UNCHANGED)
        self.assertIsNone(v106.ORDER_ADAPTER)
        self.assertFalse(v106.LIVE_ENABLED)
        self.assertFalse(v106.PAPER_ELIGIBLE)
        self.assertFalse(v106.ENTRY_SIGNAL)
        self.assertFalse(v106.MARKET_WAVE_POSITION_CERTIFIED)

    def test_manifest_frozen_and_no_real_source(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"V106_FROZEN_EARLY_RULES.json"
            first=v106.freeze(path)
            self.assertEqual(first,v106.freeze(path))
            self.assertEqual(first["source_rows_accessed"],0)
            self.assertEqual(json.loads(path.read_text())["orders"],0)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"modified"):
                v106.freeze(path)
