import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
import nexus_mr40_fixed_path_robustness_v1 as audit


def pair(index, buy, sell, gross, net_return):
    return {"position_index": index, "entry_ms": buy * audit.STEP, "exit_ms": sell * audit.STEP,
            "entry_index": buy, "exit_index": sell, "buy_signal_index": buy - 1,
            "sell_signal_index": sell - 1, "entry_reference": 100,
            "exit_reference": 100 * gross, "net_return_pct": net_return}


class RobustnessTests(unittest.TestCase):
    def test_zero_cost_compounding_and_missed_winner(self):
        pairs = [pair(0, 1, 3, 1.2, 20), pair(1, 5, 7, 0.9, -10)]
        self.assertAlmostEqual(audit.independent_product(pairs, 0, 0), 10800)
        omitted = audit.best_positive(pairs, 1)
        kept = [p for p in pairs if p not in omitted]
        self.assertAlmostEqual(audit.independent_product(kept, 0, 0), 9000)
        self.assertNotAlmostEqual(audit.independent_product(kept, 0, 0), 8800)

    def test_closed_form_known_root(self):
        pairs = [pair(0, 1, 2, 1.1, 10), pair(1, 4, 5, 1.1, 10)]
        result = audit.cost_boundary(pairs)
        effective = (1.1 - 1) / (1.1 + 1)
        root_fee = (effective - 0.0015) / (1 - effective * 0.0015) * 10000
        root_slip = (effective - 0.0025) / (1 - effective * 0.0025) * 10000
        self.assertAlmostEqual(result["break_even_fee_bps_at_slippage_15bps"], root_fee)
        self.assertAlmostEqual(result["break_even_slippage_bps_at_fee_25bps"], root_slip)
        self.assertAlmostEqual(audit.independent_product(pairs, root_fee, 15), 10000)
        self.assertAlmostEqual(audit.independent_product(pairs, 25, root_slip), 10000)

    def test_cost_monotonicity_and_component_symmetry(self):
        pairs = [pair(0, 1, 3, 1.2, 20)]
        self.assertGreater(audit.independent_product(pairs, 25, 15), audit.independent_product(pairs, 25, 20))
        self.assertEqual(audit.independent_product(pairs, 25, 15), audit.independent_product(pairs, 15, 25))
        with self.assertRaises(ValueError):
            audit.independent_product(pairs, -1, 0)

    def test_returns_rank_instead_of_dollar_profit_and_tie_is_earliest(self):
        pairs = [pair(0, 5, 7, 1.05, 5), pair(1, 1, 3, 1.05, 5), pair(2, 8, 9, 1.01, 1)]
        self.assertEqual([p["position_index"] for p in audit.best_positive(pairs, 2)], [1, 0])
        with self.assertRaises(ValueError):
            audit.best_positive(pairs, 4)

    def test_omitted_episode_stays_cash_and_original_entry_times_survive(self):
        path = ROOT / "inputs" / "nexus_mean_reversion_40_m2_retest_v1.py"
        if not path.exists():
            path = ROOT / "research" / "nexus_mean_reversion_40_m2_retest_v1.py"
        spec = importlib.util.spec_from_file_location("test_frozen_core", path)
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        prices = [100, 100, 115, 120, 100, 100, 95, 90, 90]
        rows = [[i * audit.STEP, str(p), str(p), str(p), str(p), "1"] for i, p in enumerate(prices)]
        pairs = [pair(0, 1, 3, 1.2, 20), pair(1, 5, 7, 0.9, -10)]
        baseline = core.simulate(rows, audit.fixed_mask(len(rows), pairs), 0, len(rows), 0, 0)
        omitted = core.simulate(rows, audit.fixed_mask(len(rows), pairs[1:]), 0, len(rows), 0, 0)
        self.assertAlmostEqual(baseline["metrics"]["final_usdt"], 10800)
        self.assertAlmostEqual(omitted["metrics"]["final_usdt"], 9000)
        self.assertEqual([(f["bar_index"], f["side"]) for f in omitted["fills"]], [(5, "buy"), (7, "sell")])
        self.assertTrue(all(r["equity"] == 10000 and not r["in_market"] for r in omitted["equity_curve"][:5]))
        accepted = {**baseline["metrics"], "positions": baseline["positions"], "fills": baseline["fills"]}
        accepted["fill_count"] = len(accepted["fills"])
        self.assertEqual(len(audit.closed_pairs(accepted, rows)), 2)
        accepted["fills"][1]["side"] = "buy"
        with self.assertRaises(ValueError):
            audit.closed_pairs(accepted, rows)

    def test_invalid_intervals_and_empty_product(self):
        with self.assertRaises(ValueError):
            audit.fixed_mask(10, [pair(0, 1, 6, 1, 0), pair(1, 4, 8, 1, 0)])
        self.assertEqual(audit.independent_product([], 25, 15), 10000)
        with self.assertRaises(ValueError):
            audit.cost_boundary([])

    def test_substituted_digest_is_rejected(self):
        value = {"x": 1}
        value["digest"] = audit.digest(value)
        audit.check_digest(value, "digest", value["digest"])
        value["x"] = 2
        with self.assertRaises(ValueError):
            audit.check_digest(value, "digest", value["digest"])


if __name__ == "__main__":
    unittest.main()
