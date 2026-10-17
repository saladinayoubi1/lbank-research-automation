"""Synthetic, deterministic, source-only tests. No market retrieval or trade."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from nexus_elliott_five_swing_review import ConfirmedPivot
from nexus_elliott_quality_audit_v14 import (
    RESEARCH_ONLY, AUTO_DEMO, ENTRY_SIGNAL, COMPLETE_RECURSIVE_ELLIOTT_COUNT,
    causal_asof_check, true_range, review_quality_observation,
)


def post_correction_path():
    # Corrected pivot at bar 70, confirmed at 73; first breakout at 74.
    timestamps = (datetime(2026, 10, 16, 3, 15, tzinfo=timezone.utc)
                  + timedelta(minutes=15*i) for i in range(5))
    return tuple(zip(timestamps, (130, 139, 149, 158, 151),
                     (132, 140, 150, 159, 161)))


def seven_pivots():
    # Already confirmed strictly before decision index=74. (5 nested swings
    # then one parent correction); NOT a certified recursive count.
    levels = (100, 120, 112, 140, 125, 160, 130)
    kinds = ("low", "high", "low", "high", "low", "high", "low")
    return tuple(ConfirmedPivot(k, i, i+3, p)
                 for k, i, p in zip(kinds, range(10, 80, 10), levels))


class ElliottQualityAuditV14Tests(unittest.TestCase):
    def setUp(self):
        self.args = dict(
            pivots=seven_pivots(), decision_index=74,
            decision_close_utc=datetime(2026, 10, 16, 4, 15, tzinfo=timezone.utc),
            h1_closed_utc=datetime(2026, 10, 16, 4, tzinfo=timezone.utc),
            h4_closed_utc=datetime(2026, 10, 16, 4, tzinfo=timezone.utc),
            previous_close_price=159, decision_close_price=161,
            decision_low_price=151,
            post_correction_closed_path=post_correction_path(),
            prior_14_true_ranges=[2] * 14,
            h4_closed_up=True, h1_normalized_range_ok=True,
            actual_traded_volume_ratio=Decimal("1.05"),
        )

    def audit(self, **updates):
        return review_quality_observation(**{**self.args, **updates})

    def test_research_only_never_order(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(AUTO_DEMO)
        self.assertFalse(ENTRY_SIGNAL)
        self.assertFalse(COMPLETE_RECURSIVE_ELLIOTT_COUNT)
        r = self.audit()
        self.assertTrue(r["study_eligible"])
        self.assertFalse(r["entry_signal"])
        self.assertFalse(r["paper_eligible"])
        self.assertFalse(r["complete_elliott_count"])
        self.assertFalse(r["next_open_fill_verified"])

    def test_stop_uses_correction_low_not_atr(self):
        r = self.audit()
        self.assertEqual(r["structural_stop_price"], "130")
        self.assertEqual(Decimal(r["prior_true_range_mean"]), Decimal("2"))
        self.assertEqual(Decimal(r["projected_2r_target_price"]),
                         Decimal(r["projected_next_open_entry_proxy"]) * 3 - Decimal("260"))

    def test_cost_projections_stress(self):
        r = self.audit()
        self.assertGreater(Decimal(r["projected_stress_target_net_per_unit"]), 0)
        self.assertLess(Decimal(r["projected_stress_stop_net_per_unit"]), 0)

    def test_not_an_atr_or_traded_volume_alias(self):
        r = self.audit()
        self.assertIn("not_traded_volume", r["range_label"])
        self.assertEqual(r["actual_traded_volume_ratio"], "1.05")
        r2 = self.audit(actual_traded_volume_ratio=None)
        self.assertIsNone(r2["actual_traded_volume_ratio"])

    def test_breach_at_correction_low_denied(self):
        path = list(post_correction_path())
        path[-1] = (path[-1][0], 130, 161)
        r = self.audit(decision_low_price=130, post_correction_closed_path=path)
        self.assertFalse(r["study_eligible"])
        self.assertIn("CORRECTION_LOW_TOUCHED_OR_BROKEN", r["reasons"])

    def test_first_closed_break_only(self):
        path = list(post_correction_path())
        path[-2] = (path[-2][0], 158, 161)
        r = self.audit(previous_close_price=161, post_correction_closed_path=path)
        self.assertFalse(r["study_eligible"])
        self.assertIn("NO_FIRST_CLOSED_BREAKOUT", r["reasons"])

    def test_wave_not_yet_confirmed(self):
        r = self.audit(decision_index=73)
        self.assertFalse(r["study_eligible"])
        self.assertIn("SEVEN_PIVOT_STRUCTURE_NOT_CONFIRMED", r["reasons"])

    def test_bad_degree_shape_denied(self):
        pivots = list(seven_pivots())
        pivots[3] = ConfirmedPivot("high", 40, 43, 119)
        r = self.audit(pivots=pivots)
        self.assertFalse(r["study_eligible"])

    def test_h4_context_denial(self):
        r = self.audit(h4_closed_up=False)
        self.assertEqual(r["reasons"], ["H4_CONTEXT_FALSE"])

    def test_h1_range_context_denial(self):
        r = self.audit(h1_normalized_range_ok=False)
        self.assertEqual(r["reasons"], ["H1_NORMALIZED_RANGE_CONTEXT_FALSE"])

    def test_future_h1_rejected(self):
        with self.assertRaisesRegex(ValueError, "after decision"):
            self.audit(h1_closed_utc=self.args["decision_close_utc"]+timedelta(minutes=45))

    def test_forming_4h_rejected(self):
        with self.assertRaises(ValueError):
            self.audit(h4_closed_utc=datetime(2026, 10, 16, 8, tzinfo=timezone.utc))

    def test_stale_context_rejected(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            self.audit(h1_closed_utc=datetime(2026, 10, 16, 3, tzinfo=timezone.utc))

    def test_naive_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError, "aware"):
            self.audit(decision_close_utc=datetime(2026, 10, 16, 4, 15))

    def test_grid_rejected(self):
        with self.assertRaisesRegex(ValueError, "aligned"):
            self.audit(decision_close_utc=datetime(2026, 10, 16, 4, 14, tzinfo=timezone.utc))

    def test_bool_context_type_rejected(self):
        with self.assertRaisesRegex(ValueError, "booleans"):
            self.audit(h1_normalized_range_ok=1)

    def test_prior_14_mandatory(self):
        with self.assertRaisesRegex(ValueError, "exactly 14"):
            self.audit(prior_14_true_ranges=[2] * 13)

    def test_numeric_nan_rejected(self):
        with self.assertRaises(ValueError):
            self.audit(decision_close_price=float("nan"))

    def test_prior_break_is_not_reused(self):
        extended = list(post_correction_path())
        initial = self.args["decision_close_utc"]
        extended.extend([
            (initial + timedelta(minutes=15), 154, 158),
            (initial + timedelta(minutes=30), 153, 155),
            (initial + timedelta(minutes=45), 154, 159),
            (initial + timedelta(minutes=60), 151, 161),
        ])
        r = self.audit(
            decision_index=78,
            decision_close_utc=initial + timedelta(hours=1),
            h1_closed_utc=datetime(2026, 10, 16, 5, tzinfo=timezone.utc),
            post_correction_closed_path=extended,
        )
        self.assertFalse(r["study_eligible"])
        self.assertIn("FIRST_BREAK_ALREADY_CONSUMED", r["reasons"])

    def test_prior_correction_breach_rejects_recovery(self):
        path = list(post_correction_path())
        path[2] = (path[2][0], 129, 150)
        r = self.audit(post_correction_closed_path=path)
        self.assertFalse(r["study_eligible"])
        self.assertIn("POST_CORRECTION_LOW_ALREADY_INVALIDATED", r["reasons"])

    def test_missing_path_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "complete post-correction"):
            self.audit(post_correction_closed_path=[])

    def test_gapped_path_fails_closed(self):
        path = list(post_correction_path())
        path[1] = (path[1][0] + timedelta(minutes=15), 139, 140)
        with self.assertRaisesRegex(ValueError, "chronology"):
            self.audit(post_correction_closed_path=path)

    def test_path_source_close_mismatch_fails_closed(self):
        path = list(post_correction_path())
        path[-2] = (path[-2][0], 158, 158)
        with self.assertRaisesRegex(ValueError, "previous close differs"):
            self.audit(post_correction_closed_path=path)

    def test_zero_true_range_is_valid_but_baseline_must_not_be_zero(self):
        r = self.audit(prior_14_true_ranges=[0] + [2] * 13)
        self.assertTrue(r["study_eligible"])
        with self.assertRaisesRegex(ValueError, "positive mean"):
            self.audit(prior_14_true_ranges=[0] * 14)

    def test_zero_traded_volume_ratio_is_valid_diagnostic(self):
        r = self.audit(actual_traded_volume_ratio=0)
        self.assertEqual(r["actual_traded_volume_ratio"], "0")

    def test_true_range_gap(self):
        self.assertEqual(true_range("102", "99", "110"), Decimal("11"))

    def test_true_range_bad(self):
        with self.assertRaises(ValueError):
            true_range("99", "102", "100")

    def test_prospective_only_not_explicitly_evaluated(self):
        r=self.audit()
        self.assertFalse(r["future_target_or_stop_outcome_known"])
        self.assertFalse(r["live_enabled"])


if __name__ == "__main__":
    unittest.main()
