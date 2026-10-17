"""V78: protect source-anchored stop-bar ambiguity from false profitability."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from audit_v78 import (
    V77_SHA256,SOURCE_TRACE_SHA256,audit_v77_receipt,
    classify_stop_record,RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED
)

def stopped(*,exposure=3,earlier="0.4",full="1.5",**more):
    out=dict(symbol="ETHUSDT",partition="validation",profile="conservative",
        trade_index=2,exit_reason="stop",invalid_earlier_exit=False,
        prior_exit_touch_count=0,exposure_bars=exposure,
        preexit_favorable_R=earlier,full_hold_favorable_R=full,
        target_reward_to_stop_risk_R=2.5)
    out.update(more)
    return out

def paired_receipt():
    rows=[]
    for n in range(6):
        for profile in ("conservative","stress"):
            row=stopped(trade_index=n,profile=profile,
                earlier=None if n==0 else "0.4",
                full="1.6" if n==0 else "0.6",exposure=1 if n==0 else 3)
            rows.append(row)
    for n in range(4):
        for profile in ("conservative","stress"):
            rows.append(dict(symbol="ETHUSDT",partition="train",profile=profile,
                trade_index=n,exit_reason="target"))
    return dict(schema="nexus.elliott-v77-first-touch-source-causal-exit-audit.v1",
        frozen_trace_sha256=SOURCE_TRACE_SHA256,
        archived_15m_physical_validation_performed=True,
        all_preexit_source_bars_checked_for_early_touch=True,
        incorrect_early_exit_holds_detected=0,
        paired_cost_profile_exit_paths_checked=20,
        different_historical_simulated_trades=10,
        demo_promotion=False,live_enabled=False,new_pnl=None,
        per_trade=rows)

class V78StopBarAmbiguityTests(unittest.TestCase):
    def test_one_bar_stop_cannot_prove_prior_favorable_move(self):
        p=classify_stop_record(stopped(exposure=1,earlier=None,full="1.37"))
        self.assertFalse(p["verified_strict_prior_bar_favorable_at_least_1R"])
        self.assertTrue(p["terminal_stop_bar_intrabar_1R_timing_unresolved"])
        self.assertTrue(p["realized_stop_not_a_validated_1R_profit"])
    def test_prior_favorable_move_is_distinguished_from_terminal_bar(self):
        p=classify_stop_record(stopped(earlier="1.1",full="1.5"))
        self.assertTrue(p["verified_strict_prior_bar_favorable_at_least_1R"])
        self.assertFalse(p["terminal_stop_bar_intrabar_1R_timing_unresolved"])
    def test_last_bar_high_is_not_assumed_to_precede_stop(self):
        p=classify_stop_record(stopped(earlier="0.05",full="1.96"))
        self.assertTrue(p["terminal_stop_bar_intrabar_1R_timing_unresolved"])
        self.assertFalse(p["verified_strict_prior_bar_favorable_at_least_1R"])
    def test_invalid_prior_more_than_full_rejected(self):
        with self.assertRaisesRegex(ValueError,"PRIOR_HIGH_CANNOT"):
            classify_stop_record(stopped(earlier="2.0",full="1.5"))
    def test_one_bar_has_no_preexit_candle(self):
        with self.assertRaisesRegex(ValueError,"ONE_BAR_MUST"):
            classify_stop_record(stopped(exposure=1,earlier="0.1"))
    def test_unverified_source_path_denied(self):
        with self.assertRaisesRegex(ValueError,"UNVERIFIED_FIRST_TOUCH"):
            classify_stop_record(stopped(invalid_earlier_exit=True))
    def test_improper_profit_exit_record_denied(self):
        with self.assertRaisesRegex(ValueError,"STOP_ONLY"):
            classify_stop_record(stopped(exit_reason="target"))
    def test_bytes_sha_required_before_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"fake.json"
            p.write_text(json.dumps(paired_receipt()))
            with self.assertRaisesRegex(ValueError,"SOURCE_BAR_RECEIPT_HASH"):
                audit_v77_receipt(p)
    def test_source_bound_twelve_stop_profiles_and_ambiguity(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"synthetic.json"
            p.write_text(json.dumps(paired_receipt()))
            with patch("audit_v78.hashfile",return_value=V77_SHA256):
                summary=audit_v77_receipt(p)
            self.assertEqual(summary["stop_profiles_verified"],12)
            self.assertEqual(summary["strictly_prior_completed_bar_profit_1R_instances"],0)
            self.assertEqual(summary["same_terminal_stop_bar_high_1R_without_verified_order_instances"],2)
            self.assertEqual(summary["distinct_ambiguous_historical_stop_trades"],1)
            self.assertFalse(summary["paper_eligible"] or summary["live_enabled"])
            self.assertIsNone(summary["new_pnl"])
    def test_immutable_metadata_cannot_become_paper_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"forged.json"
            data=paired_receipt();data["live_enabled"]=True
            p.write_text(json.dumps(data))
            with patch("audit_v78.hashfile",return_value=V77_SHA256):
                with self.assertRaisesRegex(ValueError,"FIRST_TOUCH_EVIDENCE_REQUIRED"):
                    audit_v77_receipt(p)
    def test_nonexecuting_flags(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)

if __name__=="__main__":
    unittest.main()
