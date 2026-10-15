"""Synthetic-only tests for preregistered spring structural review, no archive."""
from dataclasses import replace
from decimal import Decimal
import unittest

from nexus_causal_liquidity_spring_review import (
    ConfirmedSpringPivot, review_spring_shape, RESEARCH_ONLY, LIVE_ENABLED,
    PAPER_ENABLED, AUTO_DEMO, FACTORY_REGISTERED, MARKET_RUNS
)


def pattern():
    return [
        ConfirmedSpringPivot("low",10,13,"100"),
        ConfirmedSpringPivot("high",20,23,"120"),
        ConfirmedSpringPivot("low",30,33,"95"),
    ]


class SpringStructureSyntheticTests(unittest.TestCase):
    def test_valid_structural_identity_and_sweep_ratio(self):
        v=review_spring_shape(pattern(),34)
        self.assertEqual(v["identity"],(10,30))
        self.assertEqual(v["sweep_depth_ratio"],Decimal("0.25"))
        self.assertEqual(v["cost_span"],Decimal(25))
        self.assertFalse(v["signal_generated"])
        self.assertFalse(v["path_verified"])

    def test_requires_all_three_pivots(self):
        self.assertIsNone(review_spring_shape(pattern()[:2],34))

    def test_requires_low_high_low(self):
        p=pattern();p[0]=replace(p[0],kind="high")
        self.assertIsNone(review_spring_shape(p,34))

    def test_later_confirmed_pivot_must_not_enter_earlier_decision(self):
        self.assertIsNone(review_spring_shape(pattern(),33))
        self.assertIsNotNone(review_spring_shape(pattern(),34))

    def test_missing_right_side_confirmations(self):
        p=pattern();p[2]=replace(p[2],confirmed_at=32)
        self.assertIsNone(review_spring_shape(p,34))

    def test_no_future_center_can_be_used(self):
        p=pattern();p[2]=replace(p[2],index=36,confirmed_at=39)
        self.assertIsNone(review_spring_shape(p,34))

    def test_ordered_centers(self):
        p=pattern();p[1]=replace(p[1],index=31,confirmed_at=34)
        self.assertIsNone(review_spring_shape(p,35))

    def test_exact_confirmation_last_age_allowed(self):
        self.assertIsNotNone(review_spring_shape(pattern(),49))

    def test_expired_at_age_17(self):
        self.assertIsNone(review_spring_shape(pattern(),50))

    def test_span_96_allowed_when_age_valid(self):
        p=pattern()
        p[2]=replace(p[2],index=106,confirmed_at=109)
        self.assertIsNotNone(review_spring_shape(p,110))

    def test_span_97_rejected(self):
        p=pattern()
        p[2]=replace(p[2],index=107,confirmed_at=110)
        self.assertIsNone(review_spring_shape(p,111))

    def test_deep_sweep_rejected(self):
        p=pattern();p[2]=replace(p[2],price="90")
        self.assertIsNone(review_spring_shape(p,34))

    def test_shallow_sweep_passes(self):
        p=pattern();p[2]=replace(p[2],price="99.999")
        self.assertIsNotNone(review_spring_shape(p,34))

    def test_exact_upper_ratio_passes(self):
        p=pattern();p[2]=replace(p[2],price="92.36")
        self.assertEqual(review_spring_shape(p,34)["sweep_depth_ratio"],Decimal("0.382"))

    def test_above_upper_ratio_fails(self):
        p=pattern();p[2]=replace(p[2],price="92.359")
        self.assertIsNone(review_spring_shape(p,34))

    def test_h1_must_be_above_l0(self):
        p=pattern();p[1]=replace(p[1],price="100")
        self.assertIsNone(review_spring_shape(p,34))

    def test_l2_must_sweep_below_l0(self):
        p=pattern();p[2]=replace(p[2],price="100")
        self.assertIsNone(review_spring_shape(p,34))

    def test_nonfinite_prices_rejected(self):
        for value in ("nan","inf","-inf","-1","0",None):
            p=pattern();p[2]=replace(p[2],price=value)
            with self.subTest(value=value):
                self.assertIsNone(review_spring_shape(p,34))

    def test_bool_indices_and_confirmation_fail_closed(self):
        p=pattern();p[0]=replace(p[0],index=True)
        self.assertIsNone(review_spring_shape(p,34))
        p=pattern();p[2]=replace(p[2],confirmed_at=True)
        self.assertIsNone(review_spring_shape(p,34))

    def test_decision_type_is_exact_integer(self):
        for invalid in (-1,True,34.0,"34",None):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                review_spring_shape(pattern(),invalid)

    def test_tail_future_pivots_do_not_change_past_when_causally_censored(self):
        original=review_spring_shape(pattern(),34)
        future=pattern()+[ConfirmedSpringPivot("high",37,40,"140")]
        self.assertEqual(original,review_spring_shape(future[:3],34))
        self.assertIsNone(review_spring_shape(future,41))

    def test_new_higher_order_support_sweep_not_old_abc_sequence(self):
        self.assertEqual([p.kind for p in pattern()],["low","high","low"])
        self.assertFalse(review_spring_shape(pattern(),34)["signal_generated"])

    def test_all_execution_side_effect_flags_off(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED)
        self.assertFalse(PAPER_ENABLED)
        self.assertFalse(AUTO_DEMO)
        self.assertFalse(FACTORY_REGISTERED)
        self.assertEqual(MARKET_RUNS,0)


if __name__=="__main__":
    unittest.main(verbosity=2)
