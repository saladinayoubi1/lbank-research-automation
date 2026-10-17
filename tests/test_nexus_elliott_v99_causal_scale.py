"""V99 deterministic causal close-only scaling: synthetic CI fixtures."""
import copy
import unittest
from decimal import Decimal as D

from research.elliott_v99_causal_scale import scale_v99 as v99

T=1709251200000
MIN=v99.MINUTE


def source(raw):
    return [v99.CloseMinute(T+i*MIN,D(str(v)))
            for i,v in enumerate(raw)]


def alternating_sequence():
    prices=([100]*65+
            list(range(101,111))+
            list(range(109,89,-1))+
            list(range(91,125))+
            list(range(123,95,-1))+
            [96]*25)
    return source(prices)


class V99CausalMultiscaleTests(unittest.TestCase):
    def test_synthetic_directional_changes_are_distinct_confirmed(self):
        m=alternating_sequence()
        a=v99.observe_scale(m,D("3"))
        self.assertGreaterEqual(len(a),3)
        self.assertEqual([x.kind for x in a[:3]],["HIGH","LOW","HIGH"])
        self.assertTrue(all(x.center_ms<x.confirmed_ms<=m[-1].ms+MIN
                            for x in a))
        self.assertFalse(v99.ENTRY_SIGNAL)

    def test_higher_scale_is_computed_independently(self):
        m=alternating_sequence()
        coarse=v99.observe_scale(m,D("8"))
        fine=v99.observe_scale(m,D("3"))
        self.assertTrue(all(type(x) is v99.ObservedSwing for x in coarse))
        self.assertTrue(all(type(x) is v99.ObservedSwing for x in fine))
        self.assertFalse(v99.HAS_CERTIFIED_ELLIOTT_DEGREE)

    def test_no_bar_current_close_in_own_threshold(self):
        m=alternating_sequence()
        index=80
        before=v99.trailing_threshold(m,index,D("3"))
        bad=copy.deepcopy(m)
        bad[index]=v99.CloseMinute(bad[index].ms,D("1000000"))
        self.assertEqual(v99.trailing_threshold(bad,index,D("3")),before)

    def test_future_tail_does_not_rewrite_prefix(self):
        m=alternating_sequence()
        cut=T+110*MIN
        early=v99.observe_scale(m,D("3"),cut)
        full=v99.observe_scale(m,D("3"))
        self.assertEqual(early,[e for e in full if e.confirmed_ms<=cut])

    def test_identical_prefix_with_corrupted_future_is_ignored(self):
        m=alternating_sequence()
        cut=T+105*MIN
        baseline=v99.observe_scale(m,D("3"),cut)
        later=copy.deepcopy(m)
        later[-1]=v99.CloseMinute(later[-1].ms,D("99999"))
        self.assertEqual(baseline,v99.observe_scale(later,D("3"),cut))

    def test_lookback_must_be_fully_closed(self):
        m=source([100]*62)
        with self.assertRaisesRegex(ValueError,"warmup"):
            v99.observe_scale(m,D("3"))

    def test_future_asof_rejected(self):
        m=alternating_sequence()
        with self.assertRaisesRegex(ValueError,"unavailable"):
            v99.observe_scale(m,D("3"),m[-1].ms+3*MIN)

    def test_unaligned_time_rejected(self):
        with self.assertRaisesRegex(ValueError,"unaligned"):
            v99.observe_scale(alternating_sequence(),D("3"),T+MIN+1)

    def test_no_future_confirmation_for_latest_tentative_high(self):
        m=source([100]*65+list(range(101,120)))
        a=v99.observe_scale(m,D("3"))
        self.assertEqual(a,[])

    def test_strictly_gapless_source_required(self):
        m=alternating_sequence()
        q=m[68];m[68]=v99.CloseMinute(q.ms-MIN,q.close)
        with self.assertRaisesRegex(ValueError,"gapped"):
            v99.observe_scale(m,D("3"))

    def test_nan_price_rejected(self):
        m=alternating_sequence()
        q=m[90];m[90]=v99.CloseMinute(q.ms,D("NaN"))
        with self.assertRaisesRegex(ValueError,"invalid"):
            v99.observe_scale(m,D("3"))

    def test_negative_close_rejected(self):
        m=alternating_sequence()
        q=m[90];m[90]=v99.CloseMinute(q.ms,D("-50"))
        with self.assertRaisesRegex(ValueError,"invalid"):
            v99.observe_scale(m,D("3"))

    def test_bool_close_rejected(self):
        m=alternating_sequence()
        q=m[90];m[90]=v99.CloseMinute(q.ms,True)
        with self.assertRaisesRegex(ValueError,"invalid"):
            v99.observe_scale(m,D("3"))

    def test_unregistered_scale_rejected(self):
        with self.assertRaisesRegex(ValueError,"unregistered"):
            v99.observe_scale(alternating_sequence(),D("9"))

    def test_fixed_parameters_no_demo_order_path(self):
        self.assertEqual(v99.LOOKBACK_CLOSED_RETURNS,60)
        self.assertEqual(v99.TRAILING_MEDIAN_MULTIPLIERS,(D("3"),D("8")))
        self.assertEqual(v99.ABSOLUTE_PAST_PRICE_FLOOR,D("0.0003"))
        self.assertIsNone(v99.ORDER_ADAPTER)
        self.assertTrue(v99.RESEARCH_ONLY)
        self.assertTrue(v99.V52_UNCHANGED)
        self.assertFalse(v99.ENTRY_SIGNAL)
        self.assertFalse(v99.PAPER_ELIGIBLE)
        self.assertFalse(v99.LIVE_ENABLED)

    def test_ambiguous_intrabar_is_not_an_input_to_close_observer(self):
        m=alternating_sequence()
        self.assertTrue(all(set(x.__dataclass_fields__)=={"ms","close"} for x in m))
        a=v99.observe_scale(m,D("3"))
        self.assertGreater(len(a),0)
        self.assertTrue(all(x.kind in ("HIGH","LOW") for x in a))

    def test_events_summary_no_elliott_status_or_pnl(self):
        m=alternating_sequence()
        a=v99.observe_scale(m,D("3"))
        stat=v99.summarize(a,T+100*MIN)
        self.assertEqual(stat["confirmed_swings"],len(a))
        self.assertEqual(stat["high_swings"]+stat["low_swings"],len(a))
        self.assertFalse(stat["elliott_degree_certificate"])
        self.assertFalse(stat["order_or_entry_eligible"])
