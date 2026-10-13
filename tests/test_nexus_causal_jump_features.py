from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from nexus_causal_jump_features import build_lagged_jump_features
import nexus_mechanism_factory as factory


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "research" / "mechanism_factory_v6.json"


def prices(n=360):
    returns = np.where(np.arange(n) % 2, 0.001, -0.001)
    return pd.Series(100.0 * np.exp(np.cumsum(returns)))


class JumpFeatureTests(unittest.TestCase):
    def test_constant_magnitude_returns_match_bipower_scale(self):
        values = build_lagged_jump_features(prices())
        expected = math.sqrt(math.pi / 2.0) * 0.001
        self.assertTrue(np.allclose(values.lagged_bipower_sigma_96.iloc[120:], expected))
        self.assertTrue(np.allclose(values.lagged_jump_proxy_share_96.iloc[120:], 0.0))

    def test_no_current_or_future_close_enters_context(self):
        close = prices()
        before = build_lagged_jump_features(close)
        mutated = close.copy()
        mutated.iloc[160:] *= np.linspace(1.5, 2.0, len(mutated) - 160)
        after = build_lagged_jump_features(mutated)
        pd.testing.assert_frame_equal(before.iloc[:161], after.iloc[:161])

    def test_event_is_visible_one_bar_later_and_excluded_from_its_baseline(self):
        close = prices()
        mild, large = close.copy(), close.copy()
        mild.iloc[160:] *= math.exp(-0.02)
        large.iloc[160:] *= math.exp(-0.04)
        one, two = build_lagged_jump_features(mild), build_lagged_jump_features(large)
        self.assertAlmostEqual(one.lagged_bipower_sigma_96.iloc[161], two.lagged_bipower_sigma_96.iloc[161])
        self.assertGreater(abs(two.lagged_standardized_shock_96.iloc[161]), abs(one.lagged_standardized_shock_96.iloc[161]))
        self.assertLess(two.lagged_standardized_shock_96.iloc[161], -3)
        self.assertGreater(two.lagged_jump_proxy_share_96.iloc[161], 0.1)
        self.assertGreater(two.lagged_standardized_shock_96.iloc[160], -3)

    def test_warmup_and_flat_prices_cannot_emit_shock_context(self):
        early = build_lagged_jump_features(prices(80))
        self.assertTrue(early.lagged_standardized_shock_96.isna().all())
        flat = build_lagged_jump_features(pd.Series(np.full(300, 100.0)))
        self.assertTrue(flat.lagged_standardized_shock_96.isna().all())
        self.assertTrue(flat.lagged_jump_proxy_share_96.isna().all())

    def test_invalid_prices_fail_closed(self):
        for value in (0.0, -1.0, np.nan, np.inf):
            with self.subTest(value=value):
                close = prices()
                close.iloc[100] = value
                with self.assertRaises(ValueError):
                    build_lagged_jump_features(close)

    def test_hypotheses_bind_new_features_and_research_authority(self):
        raw = json.loads(CONTRACT.read_text())
        specs = factory.load_factory_contract(CONTRACT)
        self.assertEqual(len(specs), 2)
        self.assertTrue(raw["no_minimum_trade_count_gate"])
        self.assertFalse(raw["auto_demo_promotion"])
        self.assertFalse(raw["live_trading_authority"])
        for spec in specs.values():
            self.assertIn("lagged_standardized_shock_96", {c["field"] for c in spec["context"]})
            self.assertIn("lagged_jump_proxy_share_96", {c["field"] for c in spec["context"]})
            self.assertFalse(spec["peer_required"])

    def test_signal_denies_nan_history_and_unconfirmed_response(self):
        specs = factory.load_factory_contract(CONTRACT)
        name = "factory_isolated_downshock_recovery"
        frame = pd.DataFrame({
            "h4_range": [1, 1, 1], "h1_vol_ok": [1, 1, 1],
            "lagged_standardized_shock_96": [-4.0, np.nan, -4.0],
            "lagged_jump_proxy_share_96": [0.4, 0.4, 0.4],
            "close": [101.0, 101.0, 99.0], "previous_close": [100.0] * 3,
            "open": [100.0] * 3, "close_location": [0.7] * 3,
        })
        result = factory.factory_signal(frame, name, specs=specs, expected_contract_digest=specs[name]["contract_digest"])
        self.assertEqual(result.tolist(), [True, False, False])
        with self.assertRaises(factory.MechanismFactoryError):
            factory.factory_signal(frame, name, specs=specs, expected_contract_digest="0" * 64)

    def test_constant_price_rescaling_cannot_change_shock_context(self):
        one = build_lagged_jump_features(prices())
        two = build_lagged_jump_features(prices() * 7)
        for field in ("lagged_bipower_sigma_96", "lagged_standardized_shock_96", "lagged_jump_proxy_share_96"):
            self.assertTrue(np.allclose(one[field], two[field], equal_nan=True))


class JumpResearchIntegrationTests(unittest.TestCase):
    def test_old_contracts_and_order_survive_the_append(self):
        import nexus_composite_strategy_research as research
        old = factory.load_factory_contract(ROOT / "research" / "mechanism_factory_v5.json")
        self.assertEqual(research.REVIEWED_EXTENSION_SPECS, old)
        jump_configs = tuple(
            config for config in research.FRONTIER_CONFIGS
            if config["mechanism"] in research.JUMP_EXTENSION_MECHANISMS
        )
        self.assertEqual(jump_configs, factory.factory_configs(research.JUMP_EXTENSION_SPECS))
        self.assertEqual(len(research.FIXED_FACTORY_SPECS), 12)
        self.assertEqual(len(research.GENERATED_FACTORY_SPECS_V2), 24)
        self.assertEqual(len(research.GENERATED_FACTORY_SPECS_V3), 36)
        self.assertEqual(len(research.GENERATED_FACTORY_SPECS_V4), 15)

    def test_terminal_v5_ledger_routes_only_two_new_hypotheses(self):
        import nexus_composite_strategy_research as research
        ledger = research.empty_ledger()
        ledger["mechanisms_evaluated"] = list(research.MECHANISMS)
        ledger["frontier_screened_mechanisms"] = [name for name in research.FRONTIER_MECHANISMS if name not in research.JUMP_EXTENSION_MECHANISMS]
        choices = research._frontier_configs_to_screen(ledger)
        self.assertEqual({c["mechanism"] for c in choices}, set(research.JUMP_EXTENSION_MECHANISMS))
        self.assertEqual(len(choices), 2)
        self.assertTrue(all(c["risk_variant"] == 0 for c in choices))

    def test_pending_v5_stage_precedes_new_jump_stage(self):
        import nexus_composite_strategy_research as research
        ledger = research.empty_ledger()
        ledger["mechanisms_evaluated"] = list(research.MECHANISMS)
        ledger["frontier_screened_mechanisms"] = [name for name in research.FRONTIER_MECHANISMS if name not in (*research.REVIEWED_EXTENSION_MECHANISMS, *research.JUMP_EXTENSION_MECHANISMS)]
        choices = research._frontier_configs_to_screen(ledger)
        self.assertEqual({c["mechanism"] for c in choices}, set(research.REVIEWED_EXTENSION_MECHANISMS))

    def test_synthetic_new_stage_uses_existing_train_validation_stress_grid(self):
        # Wiring evidence only; this synthetic fixture is not profitability data.
        import nexus_composite_strategy_research as research
        n = 1536
        frames = {}
        for symbol in research.SYMBOLS:
            frames[symbol] = {}
            for tf, divisor, freq in (("minute15", 1, "15min"), ("hour1", 4, "1h"), ("hour4", 16, "4h")):
                size = n // divisor
                close = 100.0 + np.arange(size) * 0.03
                frames[symbol][tf] = pd.DataFrame({
                    "timestamp": pd.date_range("2025-01-01", periods=size, freq=freq, tz="UTC"),
                    "open": close - 0.05, "high": close + 0.2, "low": close - 0.2,
                    "close": close, "volume": np.full(size, 1000.0),
                })
        core = research.empty_ledger()
        core.pop("ledger_digest")
        core["mechanisms_evaluated"] = list(research.MECHANISMS)
        core["frontier_screened_mechanisms"] = [name for name in research.FRONTIER_MECHANISMS if name not in research.JUMP_EXTENSION_MECHANISMS]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            previous = root / "previous.json"
            previous.write_text(json.dumps({**core, "ledger_digest": research.digest(core)}))
            with patch.object(research, "load_verified_archive_frame", side_effect=lambda _, symbol, tf: frames[symbol][tf]):
                report = research.run(root, root / "result", "a" * 40, previous)
            self.assertEqual(report["frontier_screening"]["candidate_count"], 2)
            self.assertIn(report["selected"]["mechanism"], research.JUMP_EXTENSION_MECHANISMS)
            self.assertEqual(len(report["rows"]), 12)
            self.assertFalse(report["frontier_screening"]["validation_used_for_selection"])
            self.assertFalse(report["auto_demo_promotion"])
            self.assertFalse(report["live_enabled"])
            self.assertFalse(report["historical_test_pristine"])
            self.assertTrue(all(row["trade_count_limit"] is None for row in report["rows"]))


if __name__ == "__main__":
    unittest.main()
