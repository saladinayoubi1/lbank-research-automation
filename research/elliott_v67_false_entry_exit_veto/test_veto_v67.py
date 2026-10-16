"""V67 fail-closed reporting tests: never confuse an ETH pivot with a fill."""
import unittest
from dataclasses import replace
from veto_v67 import (
    audit_retrospective_claim, SCHEMA, SOURCE_SHA, V63_SHA,
    RESEARCH_ONLY, ENTRY_SIGNAL, EXIT_SIGNAL, LIVE_ENABLED, P_AND_L,
)

def signed_metadata():
    # Synthetic metadata-shaped example; NOT physical source authentication.
    return dict(
        schema=SCHEMA,verified_source_sha256=SOURCE_SHA,
        verified_v63_receipt_sha256=V63_SHA,
        confirmed_1m_count=8,confirmed_3m_interior_count=6,
        confirmed_15m_parent_count=2,
        physically_attested_historical_vertices=True,
        geometry_valid_expansions=0,
        geometry_state="NO_ADMISSIBLE_5_PLUS_ABC_GEOMETRY",
        first_structural_pivot_decision_not_before_utc="2026-10-10T10:30:00Z",
        executable_quote_proof=False,
        source_archive_accessible_at_structural_time=False,
        entry_signal=False,paper_eligible=False,live_enabled=False,pnl=None,
    )

class V67FalseEntryExitVetoTests(unittest.TestCase):
    def setUp(self):
        self.sample=signed_metadata()
    def test_0931_parent_center_cannot_be_an_entry(self):
        r=audit_retrospective_claim(
            self.sample,proposed_entry_utc="2026-10-10T09:31:00Z")
        self.assertEqual(r.state,"REJECT_BACKDATED_BEFORE_PARENT_RIGHT_CONFIRMATION")
        self.assertFalse(r.structure_was_confirmed_at_entry)
        self.assertFalse(r.fill_confirmed or r.entry_signal or r.exit_signal)
        self.assertIsNone(r.pnl)
    def test_1029_cannot_look_forward_one_minute(self):
        r=audit_retrospective_claim(
            self.sample,proposed_entry_utc="2026-10-10T10:29:59Z")
        self.assertEqual(r.state,"REJECT_BACKDATED_BEFORE_PARENT_RIGHT_CONFIRMATION")
    def test_1030_structural_confirmation_is_not_archive_availability(self):
        r=audit_retrospective_claim(
            self.sample,proposed_entry_utc="2026-10-10T10:30:00Z")
        self.assertTrue(r.structure_was_confirmed_at_entry)
        self.assertFalse(r.five_day_history_could_be_complete_at_entry)
        self.assertEqual(r.state,"REJECT_UNFINISHED_HISTORICAL_ARCHIVE_AS_INTRADAY_SOURCE")
        self.assertFalse(r.entry_signal)
    def test_after_archive_close_still_no_quote_or_hierarchical_entry(self):
        r=audit_retrospective_claim(
            self.sample,proposed_entry_utc="2026-10-13T00:00:00Z")
        self.assertTrue(r.five_day_history_could_be_complete_at_entry)
        self.assertEqual(r.state,"REJECT_UNVALIDATED_WAVE_WITH_NO_EXECUTABLE_QUOTE_OR_FILL")
        self.assertFalse(r.paper_eligible or r.live_enabled or r.fill_confirmed)
    def test_cannot_invent_exit_before_or_at_entry(self):
        for exit_time in ("2026-10-10T09:30:59Z","2026-10-10T09:31:00Z"):
            r=audit_retrospective_claim(
                self.sample,proposed_entry_utc="2026-10-10T09:31:00Z",
                proposed_exit_utc=exit_time)
            self.assertEqual(r.state,"INVALID_ENTRY_EXIT_CHRONOLOGY")
            self.assertFalse(r.exit_signal)
    def test_chronological_exit_is_not_realized_pnl(self):
        r=audit_retrospective_claim(
            self.sample,proposed_entry_utc="2026-10-13T00:00:00Z",
            proposed_exit_utc="2026-10-14T00:00:00Z")
        self.assertEqual(r.state,"REJECT_UNVALIDATED_WAVE_WITH_NO_EXECUTABLE_QUOTE_OR_FILL")
        self.assertIsNone(r.pnl)
        self.assertFalse(r.fill_confirmed or r.exit_signal)
    def test_no_trade_claim_stays_no_trade(self):
        r=audit_retrospective_claim(self.sample)
        self.assertEqual(r.state,"NO_TRADE_CLAIM")
        self.assertIsNone(r.proposed_entry_utc)
        self.assertFalse(r.entry_signal)
    def test_unpaired_exit_claim_rejected(self):
        with self.assertRaisesRegex(ValueError,"EXIT_WITHOUT_ENTRY"):
            audit_retrospective_claim(self.sample,proposed_exit_utc="2026-10-14T00:00:00Z")
    def test_naive_entry_timestamp_rejected(self):
        with self.assertRaisesRegex(ValueError,"UTC_AWARE"):
            audit_retrospective_claim(self.sample,proposed_entry_utc="2026-10-10T10:30:00")
    def test_forged_receipt_hash_rejected(self):
        self.sample["verified_source_sha256"]="0"*64
        with self.assertRaisesRegex(ValueError,"METADATA"):
            audit_retrospective_claim(self.sample)
    def test_forged_execution_flag_and_pnl_rejected(self):
        for key,value in (("entry_signal",True),("live_enabled",True),
                          ("executable_quote_proof",True),("pnl",12.5)):
            source=signed_metadata()
            source[key]=value
            with self.assertRaises(ValueError):
                audit_retrospective_claim(source)
    def test_forged_confirmation_clock_rejected(self):
        self.sample["first_structural_pivot_decision_not_before_utc"]="2026-10-10T09:31:00Z"
        with self.assertRaisesRegex(ValueError,"CLOCK"):
            audit_retrospective_claim(self.sample)
    def test_offset_timezone_utc_equivalence(self):
        r=audit_retrospective_claim(self.sample,proposed_entry_utc="2026-10-10T12:30:00+02:00")
        self.assertEqual(r.state,"REJECT_UNFINISHED_HISTORICAL_ARCHIVE_AS_INTRADAY_SOURCE")
    def test_flags_never_authorize_orders(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or EXIT_SIGNAL or LIVE_ENABLED)
        self.assertIsNone(P_AND_L)

if __name__ == "__main__":
    unittest.main()
