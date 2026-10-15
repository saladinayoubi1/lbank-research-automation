"""Synthetic, no-market regression tests for one frozen ABC correction topology."""
from dataclasses import replace
import unittest

from nexus_causal_abc_corrective_review import (
    ConfirmedABCPivot, review_abc_corrective_shape, WIDTH,
    RESEARCH_ONLY, LIVE_ENABLED, MARKET_EXECUTION_ENABLED,
    AUTOMATIC_FACTORY_REGISTRATION,
)


def points():
    return [
        ConfirmedABCPivot("high", 10, 13, "120"),
        ConfirmedABCPivot("low", 20, 23, "100"),
        ConfirmedABCPivot("high", 30, 33, "110"),
        ConfirmedABCPivot("low", 40, 43, "95"),
    ]


class ReviewSynthetic(unittest.TestCase):
    def test_valid_four_pivot_geometry(self):
        r=review_abc_corrective_shape(points(),44)
        self.assertEqual(r["identity"],(10,40))
        self.assertEqual(str(r["B_retracement"]),"0.5")
        self.assertEqual(str(r["C_extension"]),"0.75")

    def test_earliest_eligible_after_right_confirmation(self):
        self.assertIsNone(review_abc_corrective_shape(points(),43))
        self.assertIsNotNone(review_abc_corrective_shape(points(),44))

    def test_future_bar_can_only_change_future_decision(self):
        original=review_abc_corrective_shape(points(),44)
        altered=points()+[ConfirmedABCPivot("high",45,48,999)]
        self.assertEqual(review_abc_corrective_shape(altered[:4],44),original)
        self.assertIsNone(review_abc_corrective_shape(altered,49))

    def test_age_last_inclusive(self):
        self.assertIsNotNone(review_abc_corrective_shape(points(),75))

    def test_age_expired(self):
        self.assertIsNone(review_abc_corrective_shape(points(),76))

    def test_wrong_pivot_confirmation_delay(self):
        p=points();p[-1]=replace(p[-1],confirmed_at=44)
        self.assertIsNone(review_abc_corrective_shape(p,45))

    def test_missing_final_pivot(self):
        self.assertIsNone(review_abc_corrective_shape(points()[:3],44))

    def test_out_of_order_pivot_kind(self):
        p=points();p[2]=replace(p[2],kind="low")
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_out_of_order_pivot_indices(self):
        p=points();p[2]=replace(p[2],index=19,confirmed_at=22)
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_upper_b_retrace_exceeds_contract(self):
        p=points();p[2]=replace(p[2],price="119")
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_lower_b_retrace_below_contract(self):
        p=points();p[2]=replace(p[2],price="101")
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_lower_c_extension_below_contract(self):
        p=points();p[3]=replace(p[3],price="99")
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_upper_c_extension_exceeds_contract(self):
        p=points();p[3]=replace(p[3],price="70")
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_c_must_break_a(self):
        p=points();p[3]=replace(p[3],price="100")
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_max_span_rejects_outside(self):
        p=points();p[-1]=replace(p[-1],index=210,confirmed_at=213)
        self.assertIsNone(review_abc_corrective_shape(p,214))

    def test_nan_or_infinite_rejected(self):
        for val in ["nan","inf","-inf"]:
            p=points();p[0]=replace(p[0],price=val)
            self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_invalid_decision_index_fail_closed(self):
        for val in [-1,0.0,True,"44"]:
            with self.assertRaises(ValueError):
                review_abc_corrective_shape(points(),val)

    def test_invalid_pivot_index_bool_rejected(self):
        p=points();p[0]=replace(p[0],index=True)
        self.assertIsNone(review_abc_corrective_shape(p,44))

    def test_no_live_or_factory_and_no_entry_signals(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED)
        self.assertFalse(MARKET_EXECUTION_ENABLED)
        self.assertFalse(AUTOMATIC_FACTORY_REGISTRATION)
        r=review_abc_corrective_shape(points(),44)
        self.assertFalse(r["trade_signal"])
        self.assertFalse(r["full_recursive_elliott_classification"])


if __name__=="__main__":
    unittest.main(verbosity=2)
