import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
import nexus_mr40_continuous_account_v1 as study


class ContinuousAccountTests(unittest.TestCase):
    def core(self):
        path = ROOT / "frozen/nexus_mean_reversion_40_m2_retest_v1.py"
        if not path.exists():
            path = ROOT / "research/nexus_mean_reversion_40_m2_retest_v1.py"
        spec = importlib.util.spec_from_file_location("synthetic_continuous_core", path)
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
        return core

    def example(self):
        values = [100, 100, 110, 120, 130, 140]
        rows = [[i * study.STEP, str(v), str(v), str(v), str(v), "1"] for i, v in enumerate(values)]
        core = self.core();signal = [1, 1, 1, 0, 0, 0]
        old = core.simulate(rows, signal, 0, 3, 10, 5)
        full = core.simulate(rows, signal, 0, 6, 10, 5)
        control = {"bars": 3, "equity_sha256_without_old_terminal_liquidation": study.digest(full["equity_curve"][:3]), "old_terminal_exits": 1}
        prior = {**old["metrics"], "fills": old["fills"]}
        return rows, signal, core, old, full, prior, control

    def test_uninterrupted_position_crosses_old_boundary(self):
        rows, signal, core, old, full, prior, control = self.example()
        self.assertEqual(old["metrics"]["terminal_exits"], 1)
        self.assertEqual(full["metrics"]["terminal_exits"], 0)
        self.assertEqual([(f["bar_index"], f["side"]) for f in full["fills"]], [(1, "buy"), (4, "sell")])
        check = study.check_prefix(full, prior, control)
        self.assertTrue(check["position_carried_at_cutoff"])
        self.assertEqual(full["equity_curve"][2]["equity"], old["metrics"]["pre_terminal_mark_equity"])
        self.assertNotEqual(full["equity_curve"][2]["equity"], old["metrics"]["final_usdt"])

    def test_stitching_reset_accounts_changes_returns(self):
        rows, signal, core, old, full, _, _ = self.example()
        later = core.simulate(rows, signal, 3, 6, 10, 5)
        stitched = old["metrics"]["final_usdt"] * later["metrics"]["final_usdt"] / 10000
        self.assertNotAlmostEqual(stitched, full["metrics"]["final_usdt"])

    def test_prefix_control_rejects_changed_earlier_equity(self):
        _, _, _, _, full, prior, control = self.example()
        full["equity_curve"][1]["equity"] += 1
        with self.assertRaises(AssertionError):
            study.check_prefix(full, prior, control)

    def test_prefix_control_rejects_changed_natural_fill(self):
        _, _, _, _, full, prior, control = self.example()
        prior["fills"][0]["quantity"] += 1
        with self.assertRaises(AssertionError):
            study.check_prefix(full, prior, control)

    def test_monthly_marks_and_closed_positions_are_separate(self):
        _, _, _, _, full, _, _ = self.example()
        monthly = study.monthly_with_positions(full)
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly[0]["positions_closed"], 1)
        self.assertAlmostEqual(monthly[0]["pnl_usdt"], full["metrics"]["net_pnl_usdt"])
        self.assertAlmostEqual(monthly[0]["closed_position_pnl_sum_usdt"], full["positions"][0]["net_pnl_usdt"])

    def test_terminal_midnight_is_attributed_to_observed_month(self):
        stamp = self.core().ms("2026-08-01")
        self.assertEqual(study.exit_month({"exit_ms": stamp, "exit_reason": "terminal_close"}), "2026-07")
        self.assertEqual(study.exit_month({"exit_ms": stamp, "exit_reason": "previous_closed_bar_signal"}), "2026-08")

    def test_input_digest_substitution_is_rejected(self):
        value = {"rows": [1]};value["digest"] = study.digest(value)
        study.check_digest(value, "digest", value["digest"])
        expected = value["digest"];value["rows"] = [2]
        with self.assertRaises(ValueError):
            study.check_digest(value, "digest", expected)


if __name__ == "__main__":
    unittest.main()
