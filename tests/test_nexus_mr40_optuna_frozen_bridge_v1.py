"""Optional dependency tests; run them with Optuna 4.8 in isolated research."""
import importlib.util
import unittest

from research.nexus_mr40_optuna_frozen_bridge_v1 import (
    AdapterError, FROZEN_CASES, frozen_optuna_replay,
)

ARCHIVE_500_STRESS = {
    "baseline": (74.91102448, 25.05553569186334, 39.64310400, 15.625670358403099),
    "vol40_only": (69.12801416, 20.97234213100806, 31.55918129, 15.60607660822788),
    "stop4_arm2_only": (20.24495083, 12.058911828449315, 4.52393289, 13.040305592622914),
    "vol40_stop4_arm2": (28.07828191, 8.974527160739676, 5.41744086, 12.492083879848826),
}


@unittest.skipUnless(importlib.util.find_spec("optuna"), "Optuna optional, run separately")
class TestOptunaFrozenBridge(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def evaluator(self, case, window, cost):
        self.calls.append((case, window, cost))
        self.assertIn(case, FROZEN_CASES)
        self.assertEqual(cost, "stress")
        self.assertIn(window, ("train", "evaluation"))
        t_pnl, t_dd, v_pnl, v_dd = ARCHIVE_500_STRESS[case]
        return {
            "net_pnl_usdt": t_pnl if window == "train" else v_pnl,
            "max_intrabar_low_bound_pct": t_dd if window == "train" else v_dd,
            "closed_positions": 25 if window == "train" else 22,
        }

    def test_train_first_and_negative_economic_gate(self):
        result = frozen_optuna_replay(self.evaluator)
        self.assertEqual(result["training_trials"], 4)
        self.assertEqual(set(x[0] for x in self.calls[:4]), set(FROZEN_CASES))
        self.assertTrue(all(x[1:] == ("train", "stress") for x in self.calls[:4]))
        self.assertEqual(self.calls[4:], [
            ("baseline", "evaluation", "stress"),
            ("vol40_only", "evaluation", "stress"),
        ])
        self.assertEqual(result["train_selected_case"], "vol40_only")
        self.assertAlmostEqual(result["evaluation_baseline"]["net_pnl_usdt"], 39.643104)
        self.assertAlmostEqual(result["evaluation_selected"]["net_pnl_usdt"], 31.55918129)
        self.assertFalse(result["eval_profit_noninferior"])
        self.assertFalse(result["paper_promotion_authorized"])
        self.assertFalse(result["genuine_prospective_oos"])

    def test_reproducible(self):
        a = frozen_optuna_replay(self.evaluator)
        b = frozen_optuna_replay(self.evaluator)
        self.assertEqual(a, b)

    def test_no_new_parameter_set_or_seed(self):
        with self.assertRaisesRegex(AdapterError, "unregistered_cases"):
            frozen_optuna_replay(self.evaluator, cases=("new_candidate",))
        with self.assertRaisesRegex(AdapterError, "seed_drift"):
            frozen_optuna_replay(self.evaluator, seed=15)
        self.assertEqual(self.calls, [])

    def test_nan_fails_closed_before_evaluation(self):
        def bad(case, window, cost):
            m = self.evaluator(case, window, cost)
            m["net_pnl_usdt"] = float("nan")
            return m
        with self.assertRaisesRegex(AdapterError, "nonfinite_or_missing"):
            frozen_optuna_replay(bad)
        self.assertTrue(all(x[1] == "train" for x in self.calls))

    def test_positive_numbers_still_cannot_promote(self):
        def optimistic(case, window, cost):
            m = self.evaluator(case, window, cost)
            if window == "evaluation" and case != "baseline":
                m["net_pnl_usdt"] = 10000.0
                m["max_intrabar_low_bound_pct"] = 0.0
            return m
        out = frozen_optuna_replay(optimistic)
        self.assertTrue(out["eval_profit_noninferior"])
        self.assertFalse(out["paper_promotion_authorized"])
        self.assertTrue(out["historically_seen"])


if __name__ == "__main__":
    unittest.main()
