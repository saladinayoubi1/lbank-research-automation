"""V105 synthetic-only causal wave-position and first-minute risk gates."""
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from research.elliott_v99_causal_scale.scale_v99 import ObservedSwing
from research.elliott_v102_bybit_intake.intake_v102 import Candle
from research.elliott_v105_causal_position import position_v105 as v105

T=1792368000000
M=60000


def swing(kind,index,price,lag):
    return ObservedSwing(kind,T+index*M,T+(index+lag+1)*M,
                         D(str(price)),D(str(price)),index,index+lag)


def fixture(bear=False):
    indices=[0,10,20,30,40,50,60,70,80]
    if bear:
        prices=[200,220,205,230,210,220,190,205,180]
        types=["LOW" if i%2==0 else "HIGH" for i in range(9)]
    else:
        prices=[130,110,125,100,120,110,140,125,150]
        types=["HIGH" if i%2==0 else "LOW" for i in range(9)]
    coarse=[swing(kind,idx,price,2)
            for kind,idx,price in zip(types,indices,prices)]
    fine=[swing(types[3],indices[3],prices[3],1)]
    for leg,n in enumerate((4,2,4,2,4)):
        begin,end=indices[3+leg:5+leg]
        for count in range(n):
            idx=begin+(count+1)*(end-begin)//(n+1)
            kind="LOW" if fine[-1].kind=="HIGH" else "HIGH"
            fine.append(swing(kind,idx,100+idx,1))
        fine.append(swing(types[4+leg],end,prices[4+leg],1))
    asof=coarse[-1].confirmed_ms
    return coarse,fine,asof


def candle(start,op,high,low,close):
    return Candle(start,D(str(op)),D(str(high)),D(str(low)),
                  D(str(close)),D("1"),D("100"))


class V105CausalPositionTests(unittest.TestCase):
    def test_upward_synthetic_context_passes_but_is_not_market_elliott(self):
        coarse,fine,t=fixture()
        x=v105.inspect_context(coarse,fine,t)
        self.assertTrue(x["necessary_context_and_impulse_skeleton_pass"])
        self.assertEqual(x["hard_rejections"],[])
        self.assertEqual(x["direction"],"UP")
        self.assertFalse(x["market_pattern_position_proven"])
        self.assertFalse(x["historical_wave2_or_wave3_entry_valid"])
        self.assertFalse(x["entry_signal"])

    def test_mirrored_downward_synthetic_context_passes(self):
        coarse,fine,t=fixture(True)
        x=v105.inspect_context(coarse,fine,t)
        self.assertTrue(x["necessary_context_and_impulse_skeleton_pass"])
        self.assertEqual(x["direction"],"DOWN")
        self.assertFalse(x["paper_eligible"])

    def test_rejected_if_previous_high_not_lower(self):
        coarse,fine,t=fixture()
        coarse[2]=replace(coarse[2],center_close=D("131"))
        x=v105.inspect_context(coarse,fine,t)
        self.assertIn("OLDER_TREND_REVERSAL_LOWER_HIGH_UNPROVEN",x["hard_rejections"])

    def test_rejected_if_prior_wave_zero_not_new_low(self):
        coarse,fine,t=fixture()
        coarse[1]=replace(coarse[1],center_close=D("99"))
        x=v105.inspect_context(coarse,fine,t)
        self.assertIn("OLDER_TREND_REVERSAL_LOWER_LOW_UNPROVEN",x["hard_rejections"])

    def test_invalid_five_wave_geometry_cannot_pass_context(self):
        coarse,fine,t=fixture()
        coarse[7]=replace(coarse[7],center_close=D("118"))
        fine=[replace(e,center_close=D("118"))
              if e.center_ms==coarse[7].center_ms else e for e in fine]
        x=v105.inspect_context(coarse,fine,t)
        self.assertIn("WAVE4_OVERLAPS_WAVE1_NONDIAGONAL",x["hard_rejections"])

    def test_not_enough_predecessors_never_fill_with_future(self):
        coarse,fine,t=fixture()
        with self.assertRaisesRegex(ValueError,"exact nine"):
            v105.inspect_context(coarse[2:],fine,t)

    def test_backdated_decision_cannot_see_wave5(self):
        coarse,fine,t=fixture()
        with self.assertRaisesRegex(ValueError,"no wave-5 hindsight"):
            v105.inspect_context(coarse,fine,t-M)

    def test_nonoriginal_late_decision_is_rejected(self):
        coarse,fine,t=fixture()
        with self.assertRaisesRegex(ValueError,"no wave-5 hindsight"):
            v105.inspect_context(coarse,fine,t+M)

    def test_any_unconfirmed_fine_event_is_refused(self):
        coarse,fine,t=fixture()
        fine[-1]=replace(fine[-1],confirmed_index=83,
                         confirmed_ms=T+84*M)
        with self.assertRaisesRegex(ValueError,"future"):
            v105.inspect_context(coarse,fine,t)

    def test_first_completed_bar_both_levels_touched_stop_first(self):
        coarse,fine,t=fixture()
        x=v105.hypothetical_first_postconfirmation_bar(
            coarse,fine,candle(t,146,200,110,170),t+M)
        self.assertEqual(x["conservative_firstbar_diagnostic"],
                         "BOTH_TOUCHED_ASSUMED_STOP_FIRST_NO_INTRABAR_SEQUENCE")
        self.assertEqual(x["projected_wave4_stop"],"125")
        self.assertEqual(x["projected_2R_target"],"188")
        self.assertFalse(x["entry_signal"])
        self.assertIsNone(x["net_pnl"])

    def test_one_closed_bar_stop_first(self):
        coarse,fine,t=fixture()
        x=v105.hypothetical_first_postconfirmation_bar(
            coarse,fine,candle(t,146,170,120,151),t+M)
        self.assertEqual(x["conservative_firstbar_diagnostic"],
                         "HYPOTHETICAL_STOP_TOUCH")

    def test_one_closed_bar_target_only(self):
        coarse,fine,t=fixture()
        x=v105.hypothetical_first_postconfirmation_bar(
            coarse,fine,candle(t,146,190,140,174),t+M)
        self.assertEqual(x["conservative_firstbar_diagnostic"],
                         "HYPOTHETICAL_TARGET_TOUCH")
        self.assertEqual(x["real_entry_or_exit_count"],0)

    def test_first_closed_bar_without_exit_is_unresolved(self):
        coarse,fine,t=fixture()
        x=v105.hypothetical_first_postconfirmation_bar(
            coarse,fine,candle(t,146,160,140,151),t+M)
        self.assertEqual(x["conservative_firstbar_diagnostic"],
                         "NO_EXIT_IN_FIRST_CLOSED_MINUTE")

    def test_gap_below_defensive_stop_rejected_not_profitable(self):
        coarse,fine,t=fixture()
        x=v105.hypothetical_first_postconfirmation_bar(
            coarse,fine,candle(t,120,210,110,140),t+M)
        self.assertIn("NEXT_OPEN_BEYOND_OR_AT_DEFENSIVE_WAVE4_STOP",
                      x["rejections"])
        self.assertEqual(x["conservative_firstbar_diagnostic"],
                         "ABSTAIN_INVALID_CONTEXT_OR_RISK")

    def test_wrong_wave_position_must_abstain_from_pnl(self):
        coarse,fine,t=fixture()
        coarse[2]=replace(coarse[2],center_close=D("131"))
        x=v105.hypothetical_first_postconfirmation_bar(
            coarse,fine,candle(t,146,200,110,170),t+M)
        self.assertEqual(x["conservative_firstbar_diagnostic"],
                         "ABSTAIN_INVALID_CONTEXT_OR_RISK")
        self.assertIsNone(x["net_pnl"])

    def test_bar_itself_cannot_be_read_before_bar_close(self):
        coarse,fine,t=fixture()
        with self.assertRaisesRegex(ValueError,"fully closed"):
            v105.hypothetical_first_postconfirmation_bar(
                coarse,fine,candle(t,146,190,140,174),t)

    def test_a_later_bar_cannot_replace_immediate_next_bar(self):
        coarse,fine,t=fixture()
        with self.assertRaisesRegex(ValueError,"no wave-5 hindsight"):
            v105.hypothetical_first_postconfirmation_bar(
                coarse,fine,candle(t+M,146,190,140,174),t+2*M)

    def test_invalid_ohlc_or_nan_is_rejected(self):
        coarse,fine,t=fixture()
        for bad in (
            candle(t,146,140,135,144),
            candle(t,146,170,140,float("nan")),
        ):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError,"invalid|nonfinite"):
                    v105.hypothetical_first_postconfirmation_bar(
                        coarse,fine,bad,t+M)

    def test_bearish_both_stop_and_target_touch_always_stop_first(self):
        coarse,fine,t=fixture(True)
        # Last confirmed low follows bearish wave 5; stop is wave4 HIGH 205.
        x=v105.hypothetical_first_postconfirmation_bar(
            coarse,fine,candle(t,198,215,120,170),t+M)
        self.assertEqual(x["projected_wave4_stop"],"205")
        self.assertEqual(x["projected_2R_target"],"184")
        self.assertEqual(x["conservative_firstbar_diagnostic"],
                         "BOTH_TOUCHED_ASSUMED_STOP_FIRST_NO_INTRABAR_SEQUENCE")

    def test_freeze_rulebook_immutable_with_no_research_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            dest=Path(td)/"V105_FROZEN.json"
            result=v105.freeze_manifest(dest)
            self.assertEqual(result,v105.freeze_manifest(dest))
            self.assertEqual(result["sha256"],v105.manifest_sha())
            self.assertEqual(result["market_examples"],0)
            self.assertEqual(json.loads(dest.read_bytes())["orders"],0)
            dest.write_text("{}")
            with self.assertRaisesRegex(ValueError,"changed"):
                v105.freeze_manifest(dest)

    def test_explicit_no_adapter_and_v52_holdout_untouched(self):
        self.assertTrue(v105.RESEARCH_ONLY)
        self.assertTrue(v105.V52_UNCHANGED)
        self.assertIsNone(v105.ORDER_ADAPTER)
        self.assertFalse(v105.LIVE_ENABLED)
        self.assertFalse(v105.PAPER_ELIGIBLE)
        self.assertFalse(v105.ENTRY_SIGNAL)
        self.assertFalse(v105.MARKET_WAVE_PROVEN)
