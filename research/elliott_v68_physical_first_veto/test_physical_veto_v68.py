"""V68 regression: source evidence must precede a research timing decision."""
import unittest
from unittest.mock import patch
import pandas as pd
import physical_veto_v68 as audit

def witness():
    return dict(
        physically_attested_historical_vertices=True,
        confirmed_1m_count=8,confirmed_3m_interior_count=6,
        confirmed_15m_parent_count=2,
        geometry_state="NO_ADMISSIBLE_5_PLUS_ABC_GEOMETRY",
        geometry_valid_expansions=0,
        first_structural_pivot_decision_not_before_utc="2026-10-10T10:30:00Z",
        executable_quote_proof=False,
        source_archive_accessible_at_structural_time=False,
        entry_signal=False,paper_eligible=False,live_enabled=False,pnl=None)

class V68PhysicalFirstVetoTests(unittest.TestCase):
    def run_proof(self,entry=None,exit_time=None,overrides=None):
        p=witness()
        if overrides:p.update(overrides)
        with patch.object(audit,"audit_files",return_value=(
              pd.DataFrame(index=range(7200)),{},p)) as attested,\
             patch.object(audit,"hash_file",side_effect=[
              audit.ETH_1M_SHA,audit.V63_RECEIPT_SHA]):
            value=audit.reattest_then_veto("source.parquet","receipt.json",
                proposed_entry_utc=entry,proposed_exit_utc=exit_time)
            attested.assert_called_once()
            return value
    def test_bytes_are_required_before_claim_review(self):
        with patch.object(audit,"audit_files",
                side_effect=ValueError("PHYSICAL_SOURCE_SHA_MISMATCH")),\
             patch.object(audit,"audit_retrospective_claim") as reporter:
            with self.assertRaisesRegex(ValueError,"PHYSICAL_SOURCE_SHA"):
                audit.reattest_then_veto("source.parquet","receipt.json")
            reporter.assert_not_called()
    def test_no_backdated_entry(self):
        output=self.run_proof("2026-10-10T09:31:00Z",
                               "2026-10-10T10:00:00Z")
        self.assertEqual(output["timing_veto"]["state"],
                "REJECT_BACKDATED_BEFORE_PARENT_RIGHT_CONFIRMATION")
    def test_confirmed_pivot_not_archive(self):
        output=self.run_proof("2026-10-10T10:30:00Z")
        self.assertEqual(output["timing_veto"]["state"],
                "REJECT_UNFINISHED_HISTORICAL_ARCHIVE_AS_INTRADAY_SOURCE")
    def test_archive_not_execution(self):
        output=self.run_proof("2026-10-13T00:00:00Z",
                              "2026-10-14T00:00:00Z")
        self.assertEqual(output["timing_veto"]["state"],
                "REJECT_UNVALIDATED_WAVE_WITH_NO_EXECUTABLE_QUOTE_OR_FILL")
        self.assertIsNone(output["pnl"])
        self.assertFalse(output["entry_signal"] or output["exit_signal"])
    def test_missing_parent_denied(self):
        with patch.object(audit,"audit_files",return_value=(
            pd.DataFrame(index=range(7200)),{},
            dict(witness(),confirmed_15m_parent_count=1))):
            with self.assertRaisesRegex(ValueError,"WITNESS_INCOMPLETE"):
                audit.reattest_then_veto("source.parquet","receipt.json")
    def test_claimed_profit_denied(self):
        with self.assertRaises(ValueError):
            self.run_proof(overrides={"pnl":123})
    def test_no_claim_does_not_authorize(self):
        output=self.run_proof()
        self.assertEqual(output["timing_veto"]["state"],"NO_TRADE_CLAIM")
        self.assertFalse(output["paper_eligible"] or output["live_enabled"])
if __name__=="__main__":unittest.main()
