"""V71 independent archived 15m entry/exit clock and stop-first regression."""
import tempfile,unittest
from pathlib import Path
from audit_legacy_entries_v71 import (
 expected_exit_from_completed_bar,verify_bar_timestamps,require_digest,
 RESEARCH_ONLY,LIVE_ENABLED,PAPER_ELIGIBLE,FILLED_ORDERS_CONFIRMED,
)
class V71ExitBarTests(unittest.TestCase):
    def test_ambiguous_target_and_stop_prioritizes_stop(self):
        price,kind,dual=expected_exit_from_completed_bar(100,113,94,105,95,110,1)
        self.assertEqual((price,kind,dual),(95.0,"stop",True))
    def test_open_gap_below_stop_exits_at_open_not_better_stop(self):
        price,kind,dual=expected_exit_from_completed_bar(91,107,90,96,95,110,2)
        self.assertEqual((price,kind,dual),(91.0,"stop_open_gap",False))
    def test_target_only_price_is_exact_target(self):
        price,kind,dual=expected_exit_from_completed_bar(100,112,97,105,95,110,1)
        self.assertEqual((price,kind,dual),(110.0,"target",False))
    def test_time_and_terminal_close_are_not_invented_targets(self):
        self.assertEqual(expected_exit_from_completed_bar(100,103,97,101,95,110,64),
                         (101.0,"time_64_bars",False))
        self.assertEqual(expected_exit_from_completed_bar(100,103,97,101,95,110,1),
                         (101.0,"terminal_liquidation",False))
    def test_source_clock_exact_15m_only(self):
        ref={"open_at":"2024-01-01T00:15:00+00:00",
             "decision_at":"2024-01-01T00:30:00+00:00"}
        verify_bar_timestamps(5,ref,"2024-01-01T00:15:00Z")
        changed=dict(ref,decision_at="2024-01-01T00:15:00Z")
        with self.assertRaisesRegex(ValueError,"SOURCE_BAR_CLOCK"):
            verify_bar_timestamps(5,changed,"2024-01-01T00:15:00Z")
        with self.assertRaisesRegex(ValueError,"NAIVE"):
            verify_bar_timestamps(5,ref,"2024-01-01T00:15:00")
    def test_source_hash_changes_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            f=Path(directory)/"src.json";f.write_bytes(b"original")
            with self.assertRaisesRegex(ValueError,"FROZEN_PHYSICAL"):
                require_digest(f,"0"*64)
    def test_invalid_price_bar_denied(self):
        with self.assertRaisesRegex(ValueError,"INVALID_EXIT_BAR"):
            expected_exit_from_completed_bar(100,100,101,100,95,110,1)
    def test_research_only_never_filled_orders(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(LIVE_ENABLED or PAPER_ELIGIBLE or FILLED_ORDERS_CONFIRMED)
if __name__=="__main__":unittest.main()
