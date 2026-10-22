"""Synthetic invariants for NEXUS MR40 research-only event coordinator.

No exchange, private API, profitability, fills, or historical backtests.
"""
import unittest
from decimal import Decimal as D
from research.nexus_mr40_entry_event_contract_v1 import EntryEventCoordinator, Position


def position(stop="95"):
    return Position(entry_price=D("100"), quantity=D("0.2"),
                    stop_price=None if stop is None else D(stop))


def closed(c, i, *, entry=False, exit=False, pos=None, allowed=True, close="100",
           high="105", low="95", confirmed=True, source_ok=True):
    return c.close(i, D(close), entry, exit, pos, high_price=D(high),
                   low_price=D(low), quality_allowed=allowed,
                   confirmed=confirmed, source_ok=source_ok)


class EntryEventContractTests(unittest.TestCase):
    def test_signal_from_closed_candle_enters_only_at_next_open(self):
        c = EntryEventCoordinator()
        self.assertEqual(c.open(0, D("100")).kind, "FLAT")
        self.assertEqual(closed(c, 0, entry=True).kind, "CLOSE_CONFIRMED")
        result = c.open(1, D("99"))
        self.assertEqual(result.kind, "ENTRY_NEXT_OPEN")
        self.assertFalse(result.executable)
        self.assertEqual(result.index, 1)

    def test_veto_consumes_entire_positive_episode(self):
        c = EntryEventCoordinator()
        c.open(0, 100)
        closed(c, 0, entry=True, allowed=False)
        self.assertEqual(c.open(1, 100).kind, "FLAT")
        closed(c, 1, entry=True)
        self.assertEqual(c.open(2, 100).kind, "FLAT")
        closed(c, 2, entry=False)
        c.open(3, 100)
        closed(c, 3, entry=True)
        self.assertEqual(c.open(4, 100).kind, "ENTRY_NEXT_OPEN")

    def test_duplicate_signal_while_unacknowledged_cannot_open_twice(self):
        c = EntryEventCoordinator()
        c.open(0, 100)
        closed(c, 0, entry=True)
        self.assertEqual(c.open(1, 100).kind, "ENTRY_NEXT_OPEN")
        closed(c, 1, entry=True)
        self.assertEqual(c.open(2, 100).kind, "AWAIT_ENTRY_ACK")

    def test_natural_exit_outranks_gap_at_next_open(self):
        c = EntryEventCoordinator()
        p = position()
        c.open(0, 100, p)
        closed(c, 0, pos=p, exit=True)
        event = c.open(1, 90, p)
        self.assertEqual(event.kind, "NATURAL_EXIT_NEXT_OPEN")
        self.assertEqual(event.reference_price, D("90"))
        self.assertFalse(event.executable)

    def test_gap_precedes_intrabar_stop_and_marks_unverified(self):
        c = EntryEventCoordinator()
        p = position()
        c.open(0, 100, p)
        closed(c, 0, pos=p)
        event = c.open(1, 90, p)
        self.assertEqual(event.kind, "GAP_BELOW_STOP_OPEN")
        self.assertIn("unverified", event.note)
        self.assertEqual(c.low_touch(1, 88, p).kind, "NO_INTRABAR_EXIT")

    def test_intrabar_stop_touch_not_assumed_fill(self):
        c = EntryEventCoordinator()
        p = position()
        self.assertEqual(c.open(0, 100, p).kind, "HOLD")
        event = c.low_touch(0, 94, p)
        self.assertEqual(event.kind, "STOP_LOW_TOUCHED_UNVERIFIED_FILL")
        self.assertFalse(event.executable)
        self.assertEqual(event.reference_price, D("95"))
        closed(c, 0, pos=p)
        self.assertEqual(c.open(1, 99, p).kind, "AWAIT_EXIT_ACK")

    def test_profit_arming_only_effective_from_subsequent_open(self):
        c = EntryEventCoordinator(arm2_gross_entry_stop=True)
        p = position("90")
        self.assertEqual(c.open(0, 100, p).kind, "HOLD")
        self.assertEqual(c.low_touch(0, 99, p).kind, "NO_INTRABAR_EXIT")
        closed(c, 0, pos=p, close="103", high="104", low="99")
        self.assertEqual(c.open(1, 102, p).kind, "HOLD")
        self.assertEqual(c.current_effective_stop, D("100"))
        self.assertEqual(c.low_touch(1, 99, p).kind,
                         "STOP_LOW_TOUCHED_UNVERIFIED_FILL")

    def test_baseline_has_no_unapproved_profit_arm(self):
        c = EntryEventCoordinator(arm2_gross_entry_stop=False)
        p = position("90")
        c.open(0, 100, p)
        closed(c, 0, pos=p, close="103", high="104", low="99")
        self.assertEqual(c.open(1, 102, p).kind, "HOLD")
        self.assertEqual(c.current_effective_stop, D("90"))
        self.assertEqual(c.low_touch(1, 99, p).kind, "NO_INTRABAR_EXIT")

    def test_bad_source_requires_neutral_closed_reset(self):
        c = EntryEventCoordinator()
        self.assertEqual(c.open(0, 100, source_ok=False).kind, "DATA_BLOCK")
        self.assertEqual(closed(c, 0, entry=True, source_ok=False).kind, "DATA_BLOCK")
        self.assertEqual(c.open(1, 100).kind, "DATA_BLOCK")
        self.assertEqual(closed(c, 1, entry=True).kind, "DATA_BLOCK")
        self.assertEqual(c.open(2, 100).kind, "DATA_BLOCK")
        self.assertEqual(closed(c, 2, entry=False).kind, "NEUTRAL_RESET")
        c.open(3, 100)
        closed(c, 3, entry=True)
        self.assertEqual(c.open(4, 100).kind, "ENTRY_NEXT_OPEN")

    def test_unconfirmed_close_cannot_emit_entry(self):
        c = EntryEventCoordinator()
        c.open(0, 100)
        self.assertEqual(closed(c, 0, entry=True, confirmed=False).kind, "DATA_BLOCK")
        self.assertEqual(c.open(1, 100).kind, "DATA_BLOCK")

    def test_invalid_ohlc_or_bar_gap_blocks(self):
        c = EntryEventCoordinator()
        c.open(0, 100)
        self.assertEqual(closed(c, 0, high="90").kind, "DATA_BLOCK")
        self.assertEqual(c.open(2, 100).kind, "DATA_BLOCK")

    def test_cannot_access_future_low_during_entry_at_open(self):
        c = EntryEventCoordinator()
        c.open(0, 100)
        closed(c, 0, entry=True)
        event = c.open(1, 100)
        self.assertEqual(event.kind, "ENTRY_NEXT_OPEN")
        self.assertNotIn("low", EntryEventCoordinator.open.__code__.co_varnames[:5])

    def test_repeat_close_fails_and_no_live_methods(self):
        c = EntryEventCoordinator()
        c.open(0, 100)
        closed(c, 0)
        with self.assertRaisesRegex(ValueError, "duplicate_close"):
            closed(c, 0)
        self.assertFalse(hasattr(c, "place_order"))
        self.assertFalse(hasattr(c, "send_api_order"))


if __name__ == "__main__":
    unittest.main()
