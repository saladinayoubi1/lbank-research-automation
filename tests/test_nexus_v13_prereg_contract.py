"""Enforce a single frozen V13 prospective hypothesis and empty market ledger."""
from pathlib import Path
import json
import unittest

import pandas as pd
import nexus_v13_compression_detector as d

SPEC=json.loads((Path(__file__).resolve().parents[1] /
                 "research/causal_volatility_compression_breakout_v13_preregistration.json")
                .read_text(encoding="utf-8"))


class PreregisteredV13ForwardContract(unittest.TestCase):
    def test_independent_one_hypothesis(self):
        self.assertEqual(SPEC["hypothesis_count"],1)
        self.assertEqual(SPEC["parameter_configurations"],1)
        self.assertEqual(SPEC["independence"]["branch_base"],"main")
        self.assertEqual(SPEC["mechanism_id"],
                         "research_causal_volatility_compression_expansion_v13")

    def test_future_only_window(self):
        self.assertEqual(d.FUTURE_START,pd.Timestamp(
            SPEC["independence"]["new_evaluation_start_utc"]))
        self.assertEqual(d.FUTURE_END_EXCLUSIVE,pd.Timestamp(
            SPEC["independence"]["new_evaluation_end_utc_exclusive"]))
        self.assertGreater(d.FUTURE_START,pd.Timestamp("2026-07-31T23:59:59Z"))
        self.assertGreater(d.FUTURE_END_EXCLUSIVE,d.FUTURE_START)

    def test_compression_and_no_lookahead_window(self):
        v=SPEC["compression"]
        self.assertEqual(d.RECENT_HOURS,v["recent_window_1h_closed_bars"])
        self.assertEqual(d.REFERENCE_HOURS,v["reference_window_1h_closed_bars"])
        self.assertEqual(d.REQUIRED_HOURS,v["volatility_window_total_completed_hours"])
        self.assertEqual(d.COMPRESSION_MAX,v["ratio_threshold_inclusive"])
        self.assertEqual(d.REFRACTORY_15M_BARS,
                         SPEC["breakout"]["refractory_decision_bars_after_any_first_break"])

    def test_execution_authority_unavailable(self):
        self.assertTrue(d.RESEARCH_ONLY)
        for value in (d.LIVE_ENABLED,d.ORDER_EXECUTION_ENABLED,
                      d.AUTO_DEMO,d.FACTORY_REGISTERED):
            self.assertFalse(value)
        self.assertEqual(d.MARKET_EVALUATIONS,0)
        self.assertEqual(SPEC["current_state"]["real_forward_bars_scored"],0)
        self.assertEqual(SPEC["current_state"]["live_orders"],0)


if __name__=="__main__":
    unittest.main()
