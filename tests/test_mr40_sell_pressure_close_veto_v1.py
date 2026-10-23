"""Offline causal-invariant tests for the one fixed MR40 sell-pressure veto."""
import copy
import unittest

from research.mr40_sell_pressure_close_veto_v1 import (
    _validate_own_protocol, filtered_reference, signal_veto, test_gate,
)
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bars():
    data = [
        [i * 14_400_000, "100", "110", "90", "105", "10"]
        for i in range(24)
    ]
    data[21] = [21 * 14_400_000, "100", "110", "90", "92", "15"]
    return data


def minimal_ref(data):
    return {
        "decisions": [
            {"signal_index": 21, "signal_ms": data[21][0],
             "allowed": True, "episode_last_index": 22}
        ],
        "positions": [
            {"entry": {"signal_index": 21}, "net_pnl_usdt": -2.0}
        ],
        "fills": [],
        "equity_digest": "not_reused_for_candidate",
    }


class ResearchOnlyVetoTests(unittest.TestCase):
    def test_high_volume_near_low_red_vetoes_first_closed_signal(self):
        self.assertTrue(signal_veto(bars(), 21))

    def test_no_veto_when_volume_below_frozen_ratio(self):
        data = bars()
        data[21][5] = "14.99"
        self.assertFalse(signal_veto(data, 21))

    def test_no_veto_if_price_closes_above_lower_quintile(self):
        data = bars()
        data[21][4] = "95"
        self.assertFalse(signal_veto(data, 21))

    def test_no_veto_if_green_even_high_volume(self):
        data = bars()
        data[21][1] = "91"
        self.assertFalse(signal_veto(data, 21))

    def test_future_bar_mutation_cannot_change_veto(self):
        data = bars()
        original = signal_veto(data, 21)
        data[22] = [22 * 14_400_000, "900", "2000", "1", "10", "5000000"]
        self.assertEqual(signal_veto(data, 21), original)

    def test_missing_history_and_malformed_candle_fail(self):
        with self.assertRaisesRegex(ValueError, "missing_volume_history"):
            signal_veto(bars(), 19)
        data = bars()
        data[21][5] = "NaN"
        with self.assertRaisesRegex(ValueError, "nonfinite_bar"):
            signal_veto(data, 21)

    def test_veto_consumes_entire_positive_episode(self):
        data = bars()
        original = minimal_ref(data)
        new, removed = filtered_reference(data, original)
        self.assertEqual(len(removed), 1)
        self.assertEqual(new["decisions"], [])
        self.assertEqual(new["positions"], [])
        self.assertEqual(len(original["decisions"]), 1)

    def test_veto_does_not_remove_accepted_episode(self):
        data = bars()
        data[21][5] = "1"
        new, removed = filtered_reference(data, minimal_ref(data))
        self.assertEqual(removed, [])
        self.assertEqual(len(new["decisions"]), 1)

    def test_lock_protocol_and_reject_tampered_threshold(self):
        doc = json.loads((ROOT / "research/mr40_sell_pressure_close_veto_protocol_20261023.json").read_text())
        _validate_own_protocol(doc)
        bad = copy.deepcopy(doc)
        bad["veto"]["all_conditions"][3] = "volume[j] >= 1.10 * mean(volume[j-20:j])"
        with self.assertRaisesRegex(ValueError, "protocol_rule_drift"):
            _validate_own_protocol(bad)

    def test_gate_refuses_profit_decrease_and_winner_loss(self):
        group = {"baseline": {"net_pnl_usdt": 40.0, "max_intrabar_low_bound_pct": 20.0},
                 "sell_pressure_close_veto": {"net_pnl_usdt": 30.0, "max_intrabar_low_bound_pct": 10.0}}
        attr = {"retained_winner_fraction": 0.4, "retained_winner_pnl_fraction": 0.4,
                "removed_losers": 2}
        self.assertFalse(all(test_gate(group, attr).values()))
        self.assertTrue(test_gate(group, attr)["low_dd_improved_10pct"])


if __name__ == "__main__":
    unittest.main()
