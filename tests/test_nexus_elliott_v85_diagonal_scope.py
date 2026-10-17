"""V85 deterministic diagonal fail-closed tests; no external IO or trading."""
import unittest
from research.elliott_v85_diagonal_scope.diagonal_scope_v85 import (
    evaluate_diagonal_preconditions,
)

ETH = ["3460.04", "3441.97", "3460.00", "3434.73", "3446.80", "3424.71"]
BTC = ["62123.00", "61884.80", "61966.29", "61790.97", "61898.00", "61641.10"]
START = 1709251200000
STEP = 60000

def record(prices=ETH, orientation="bearish"):
    centers = [START + i*10*STEP for i in range(1, 7)]
    return {
        "state":"REJECT_HARD_MOTIVE_GEOMETRY",
        "orientation":orientation,
        "price_vertices":list(prices),
        "vertex_center_ms":centers,
        "vertex_confirmed_ms":[i+4*STEP for i in centers],
        "first_observable_ms":START+100*STEP,
        "physical_failures":[],
        "entry_signal":False,
        "paper_eligible":False,
    }

class V85DiagonalVetoTests(unittest.TestCase):
    def test_btc_short_third_rejected(self):
        got=evaluate_diagonal_preconditions(record(BTC))
        self.assertIn("WAVE3_SHORTEST_FORBIDDEN_IN_DIAGONAL",
                      got["hard_veto_reasons"])
        self.assertEqual(got["state"],"DIAGONAL_HARD_VETO")

    def test_eth_preliminary_does_not_become_pattern_or_signal(self):
        got=evaluate_diagonal_preconditions(record())
        self.assertEqual(got["state"],
                         "PRELIMINARY_GEOMETRY_ONLY_DIAGONAL_NOT_PROVEN")
        self.assertTrue(got["wave4_overlaps_wave1"])
        self.assertFalse(got["ending_diagonal_proven"])
        self.assertFalse(got["leading_diagonal_proven"])
        self.assertFalse(got["three_subwaves_per_leg_verified"])
        self.assertFalse(got["entry_signal"])
        self.assertFalse(got["paper_eligible"])
        self.assertIsNone(got["pnl"])

    def test_bullish_mirror_only_preliminary(self):
        mirrored=[str(7000-float(x)) for x in ETH]
        got=evaluate_diagonal_preconditions(record(mirrored,"bullish"))
        self.assertEqual(got["state"],
                         "PRELIMINARY_GEOMETRY_ONLY_DIAGONAL_NOT_PROVEN")
        self.assertEqual(got["orientation"],"bullish")

    def test_wave2_full_retrace_rejected(self):
        x=record()
        x["price_vertices"][2]="3461.00"
        got=evaluate_diagonal_preconditions(x)
        self.assertIn("WAVE2_FULL_RETRACE_W1",got["hard_veto_reasons"])

    def test_wave4_full_retrace_rejected(self):
        x=record()
        x["price_vertices"][4]="3460.01"
        got=evaluate_diagonal_preconditions(x)
        self.assertIn("WAVE4_FULL_RETRACE_W3",got["hard_veto_reasons"])

    def test_wave3_must_progress(self):
        x=record()
        x["price_vertices"][3]="3445.00"
        got=evaluate_diagonal_preconditions(x)
        self.assertIn("WAVE3_NOT_BEYOND_W1",got["hard_veto_reasons"])

    def test_invalid_physical_path_veto(self):
        x=record()
        x["physical_failures"]=["LEG2_INTERVENING_LOW_BELOW_ENDPOINT"]
        got=evaluate_diagonal_preconditions(x)
        self.assertIn("PHYSICAL_SOURCE_PATH_INVALIDATED",got["hard_veto_reasons"])

    def test_future_confirmed_pivot_rejected(self):
        x=record()
        x["vertex_confirmed_ms"][4]=x["first_observable_ms"]+STEP
        with self.assertRaisesRegex(ValueError,"noncausal"):
            evaluate_diagonal_preconditions(x)

    def test_duplicate_or_misordered_pivot_rejected(self):
        x=record()
        x["vertex_center_ms"][3]=x["vertex_center_ms"][2]
        with self.assertRaisesRegex(ValueError,"not in source-time order"):
            evaluate_diagonal_preconditions(x)

    def test_executable_record_rejected(self):
        x=record()
        x["entry_signal"]=True
        with self.assertRaisesRegex(ValueError,"executable"):
            evaluate_diagonal_preconditions(x)

    def test_bad_prices_rejected(self):
        for malformed in ("NaN","-1","Infinity"):
            with self.subTest(value=malformed):
                x=record()
                x["price_vertices"][4]=malformed
                with self.assertRaises(ValueError):
                    evaluate_diagonal_preconditions(x)

    def test_bad_vertex_count_rejected(self):
        x=record()
        x["price_vertices"].pop()
        with self.assertRaisesRegex(ValueError,"exactly six"):
            evaluate_diagonal_preconditions(x)

    def test_no_unreviewed_pattern_records(self):
        x=record()
        x["state"]="SYNTHETIC_PROFITABLE"
        with self.assertRaisesRegex(ValueError,"verified V83"):
            evaluate_diagonal_preconditions(x)
