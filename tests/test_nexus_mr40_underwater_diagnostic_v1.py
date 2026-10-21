import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research"))
import nexus_mr40_underwater_diagnostic_v1 as audit


def curve(values):
    return [{"bar_open_ms": i * audit.STEP, "equity": float(v), "in_market": True}
            for i, v in enumerate(values)]


class UnderwaterTests(unittest.TestCase):
    def test_flat_peak_is_not_underwater(self):
        out = audit.summarize(curve([10000, 10000, 11000, 11000]))
        self.assertEqual(out["episodes"], [])
        self.assertEqual(out["underwater_close_observations"], 0)
        self.assertEqual(out["ending_drawdown_pct"], 0)

    def test_last_equal_peak_and_exact_recovery(self):
        out = audit.summarize(curve([10000, 10000, 9000, 9500, 10000]))
        e = out["episodes"][0]
        self.assertEqual(e["peak_close_ms"], 2 * audit.STEP)
        self.assertEqual(e["recovery_close_ms"], 5 * audit.STEP)
        self.assertEqual(e["peak_to_end_hours"], 12)
        self.assertAlmostEqual(e["drawdown_pct"], 10)
        self.assertTrue(e["recovered"])
        self.assertEqual(out["underwater_close_observations_pct"], 40)

    def test_initial_capital_anchor_and_right_censoring(self):
        out = audit.summarize(curve([9000, 8000, 9000]))
        e = out["episodes"][0]
        self.assertEqual(e["peak_close_ms"], 0)
        self.assertEqual(e["peak_to_end_hours"], 12)
        self.assertIsNone(e["recovery_close_ms"])
        self.assertTrue(e["right_censored"])
        self.assertAlmostEqual(e["drawdown_pct"], 20)
        self.assertEqual(out["open_episodes"], 1)
        self.assertIsNone(out["longest_completed_peak_to_recovery_days"])

    def test_profitable_final_can_still_be_underwater(self):
        out = audit.summarize(curve([12000, 10800, 11000]))
        self.assertEqual(out["net_pnl_usdt"], 1000)
        self.assertGreater(out["ending_drawdown_pct"], 8)
        self.assertEqual(out["below_initial_capital_close_observations"], 0)
        self.assertEqual(out["open_episodes"], 1)

    def test_longest_episode_is_distinct_from_deepest(self):
        out = audit.summarize(curve([10000, 8000, 10000, 9900, 9800, 9900, 10000]))
        self.assertAlmostEqual(out["worst_episode"]["drawdown_pct"], 20)
        self.assertAlmostEqual(out["longest_observed_episode"]["drawdown_pct"], 2)
        self.assertEqual(out["longest_observed_episode"]["peak_to_end_hours"], 16)

    def test_independent_run_detector_for_multiple_episodes(self):
        values = curve([10000, 10000, 9000, 10000, 12000, 11500, 11900, 12000, 12100, 10000])
        out = audit.summarize(values)
        self.assertLess(audit.assert_oracle(out["episodes"], audit.independent_episodes(values)), 1e-9)
        self.assertEqual(out["drawdown_episodes"], 3)
        self.assertEqual(out["recovered_episodes"], 2)

    def test_invalid_frame_is_rejected(self):
        for values in ([], curve([0]), curve([float("nan")])):
            with self.assertRaises(ValueError):
                audit.summarize(values)
        gap = curve([10000, 9000]);gap[1]["bar_open_ms"] += audit.STEP
        with self.assertRaises(ValueError):
            audit.summarize(gap)


if __name__ == "__main__":
    unittest.main()
