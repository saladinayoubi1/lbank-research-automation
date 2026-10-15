"""Read-only Spring signal integration checks; no market execution."""
import unittest

import numpy as np

import nexus_spring_research_signal as spring
from test_nexus_causal_macro_retest_features import aggregate
from test_nexus_spring_parent_feature_review import minute_spring


class ResearchSignalBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, cls.signals = spring.inspect_research_signals(
            aggregate(minute_spring())
        )

    def test_research_only_authority(self):
        self.assertTrue(spring.RESEARCH_ONLY)
        self.assertFalse(spring.LIVE_ENABLED)
        self.assertFalse(spring.AUTO_DEMO)
        self.assertFalse(spring.FACTORY_REGISTERED)
        self.assertFalse(spring.ORDER_EXECUTION_ENABLED)

    def test_single_predeclared_configuration(self):
        self.assertEqual(spring.SPEC["hypothesis_count"], 1)
        self.assertEqual(spring.SPEC["parameter_configurations"], 1)
        original = spring.candidate_config()
        original["risk_variant"] = 1
        with self.assertRaises(ValueError):
            spring.research_signals(self.frame, original)

    def test_non_admitted_event_does_not_schedule_signal(self):
        self.assertEqual(
            np.flatnonzero(self.frame["spring_first_support_reclaim_event"]).tolist(),
            [288],
        )
        self.assertFalse(self.signals.any())
        self.assertNotIn("order", self.frame.columns)
        self.assertNotIn("next_open_fill", self.frame.columns)

    def test_missing_cost_gate_denied(self):
        with self.assertRaises(ValueError):
            spring.research_signals(
                self.frame.drop(columns="spring_stress_cost_feasible")
            )

    def test_invalid_atr_denied(self):
        broken = self.frame.copy()
        broken.loc[288, "atr"] = float("nan")
        self.assertFalse(spring.research_signals(broken).any())


if __name__ == "__main__":
    unittest.main()
