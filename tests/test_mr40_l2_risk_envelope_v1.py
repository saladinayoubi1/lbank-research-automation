"""Offline guardrail tests for the non-executable MR40 L2 mark study."""
import copy
import unittest
from decimal import Decimal

from research.mr40_l2_risk_envelope_v1 import (
    SAMPLE_LABELS, ENTRY_CASH, compute, find_position, sensitivity,
    validate_failed_gates, validate_snapshot,
)


def example_snapshot():
    return {
        "label": "first_cross", "book_valid": True, "invalidation_reason": None,
        "target_utc": "2025-10-10T20:56:14.936+00:00",
        "source_timestamp_utc": "2025-10-10T20:56:14.864+00:00",
        "source_engine_cts_utc": "2025-10-10T20:56:14.862+00:00",
        "age_ms": 72,
        "depth_mark": {
            "ask": Decimal("114346.5"), "bid": Decimal("114345.2"),
            "book_walk_levels": 6,
            "zero_latency_static_displayed_book_walk_completely_covered": True,
            "remaining_uncovered_btc": 0, "recorded_position_qty_btc": Decimal("0.09461"),
            "static_book_walk_vwap_mark": Decimal("114342.083945"),
        }
    }


class RiskEnvelopeTests(unittest.TestCase):
    def test_cash_denominator_and_stop_reference(self):
        stop = Decimal("119075.40795000") * Decimal("0.96")
        qty = Decimal("0.09461")
        change, percent = sensitivity(Decimal("114342.083945"), stop, qty, ENTRY_CASH)
        self.assertEqual(stop, Decimal("114312.3916320000"))
        self.assertEqual(change, Decimal("29.692313") * qty)
        self.assertEqual(percent, change / ENTRY_CASH * 100)
        self.assertNotEqual(percent, change / Decimal("10000") * 100)

    def test_snapshot_cannot_consume_future_state(self):
        sample = example_snapshot()
        sample["source_timestamp_utc"] = "2025-10-10T20:56:14.937+00:00"
        with self.assertRaisesRegex(ValueError, "Future"):
            validate_snapshot(sample, Decimal("0.09461"))

    def test_stale_or_crossed_book_rejected(self):
        sample = example_snapshot()
        sample["source_timestamp_utc"] = "2025-10-10T20:56:12.000+00:00"
        sample["age_ms"] = 2936
        with self.assertRaisesRegex(ValueError, "older than"):
            validate_snapshot(sample, Decimal("0.09461"))
        sample = example_snapshot()
        sample["depth_mark"]["ask"] = Decimal("114345.1")
        with self.assertRaisesRegex(ValueError, "Crossed"):
            validate_snapshot(sample, Decimal("0.09461"))

    def test_mismatched_order_quantity_rejected(self):
        sample = example_snapshot()
        with self.assertRaisesRegex(ValueError, "quantity"):
            validate_snapshot(sample, Decimal("0.10"))

    def test_ledger_identity_and_duplicate_guard(self):
        match = {
            "venue": "Bybit", "window": "evaluation", "capital": 10000,
            "profile": "normal", "case": "baseline", "entry_ms": 1760112000000,
            "expected_entry_quantity_btc": "0.09461",
            "expected_filled_entry_price": "119075.40795000",
        }
        row = {"key": {k: match[k] for k in ("venue", "window", "capital", "profile", "case")},
               "positions": [{
                   "entry": {"side": "buy", "fill_ms": 1760112000000, "quantity": "0.09461",
                             "price": "119075.40795000", "cash_before": "11277.26953006"}
               }]}
        self.assertEqual(find_position([row], match)["quantity"], "0.09461")
        with self.assertRaisesRegex(ValueError, "scenario"):
            find_position([row, row], match)
        wrong = copy.deepcopy(row)
        wrong["positions"][0]["entry"]["quantity"] = "0.09462"
        with self.assertRaisesRegex(ValueError, "quantity"):
            find_position([wrong], match)
        wrong = copy.deepcopy(row)
        wrong["positions"][0]["entry"]["cash_before"] = "10000"
        with self.assertRaisesRegex(ValueError, "cash-before"):
            find_position([wrong], match)

    def test_original_two_failed_gates_cannot_be_upgraded(self):
        audit = {
            "schema": "mr40.bybit-spot-historical-l2-crash.results.v1",
            "prior_4h_1m_full_ohlc_parity": "FAILED and deliberately not changed",
            "full_day_strict_time_scope_pass": False,
            "cross_state_usable": True, "paper_changed": False,
            "real_fill_verified": False,
        }
        validate_failed_gates(audit)
        mutated = copy.deepcopy(audit)
        mutated["prior_4h_1m_full_ohlc_parity"] = "PASSED"
        with self.assertRaisesRegex(ValueError, "FAILED"):
            validate_failed_gates(mutated)
        mutated = copy.deepcopy(audit)
        mutated["full_day_strict_time_scope_pass"] = True
        with self.assertRaisesRegex(ValueError, "FAILED"):
            validate_failed_gates(mutated)

    def test_closed_event_sample_list_and_no_promote(self):
        s = example_snapshot()
        gate = {
            "schema": "mr40.bybit-spot-historical-l2-crash.results.v1",
            "prior_4h_1m_full_ohlc_parity": "FAILED", "full_day_strict_time_scope_pass": False,
            "cross_state_usable": True, "paper_changed": False, "real_fill_verified": False,
            "digest": "pinned", "source": {
                "sha256": "6a7e3f08c46da49ea2241aaec77371ca414a3f400e0cec4ec3b1ecda662b0d88"},
        }
        protocol = {
            "sources": {"l2_digest": "pinned", "ledger_sha256": "pinned"},
            "entry_match": {"stop_fraction": Decimal("0.04")},
        }
        snapshots = []
        for label in SAMPLE_LABELS:
            t = copy.deepcopy(s)
            t["label"] = label
            snapshots.append(t)
        gate["snapshots"] = snapshots
        entry = {
            "fill_ms": 1760112000000, "quantity": "0.09461",
            "price": "119075.40795000", "cash_before": "11277.26953006",
        }
        result = compute(protocol, gate, entry)
        self.assertEqual(len(result["samples"]), 7)
        self.assertEqual(result["promotion"], "NO_PROMOTE")
        self.assertFalse(result["real_fill_verified"])
        self.assertEqual(result["source_gates"]["l2_full_day_date_only_scope"], "FAILED")
        gate["snapshots"] = snapshots[:-1]
        with self.assertRaisesRegex(ValueError, "Missing"):
            compute(protocol, gate, entry)


if __name__ == "__main__":
    unittest.main()
