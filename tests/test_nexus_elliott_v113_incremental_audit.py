"""V113 streaming proof versus V112 true prefix differential; synthetic only."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v112_prefix_audit import single,both
from test_nexus_elliott_v111_source_capacity import sample
from test_nexus_elliott_v108_forward_outcomes import bar
from research.elliott_v113_incremental_audit import incremental_v113 as v113
from research.elliott_v112_prefix_audit import audit_v112 as v112
from research.elliott_v111_source_capacity import bridge_v111 as v111
from research.elliott_v110_portfolio_capacity import capacity_v110 as v110

M=60000


class V113IncrementalNoSamplingProof(unittest.TestCase):
    def compare_with_true_full_prefix(self,series):
        baseline=v112.audit_every_causal_checkpoint(series)
        stream=v113.audit_streaming(series)
        for key in (
            "source_1m_minutes_per_symbol","all_mandatory_causal_checkpoints",
            "no_checkpoint_omitted","all_original_candidate_windows",
            "all_final_hypothetical_reference_proposals",
            "final_portfolio_event_count","differential_asof_ledger_checks",
            "final_v111_event_log_digest",
        ):
            with self.subTest(key=key):
                self.assertEqual(stream[key],baseline[key])
        self.assertEqual(stream["trade_count"],0)
        self.assertFalse(stream["entry_signal"])
        self.assertFalse(stream["live_enabled"])
        self.assertIsNone(stream["net_pnl"])
        return stream

    def test_no_release_reference_ledger_identical_to_v112(self):
        x=self.compare_with_true_full_prefix(single(n=5))
        self.assertEqual(x["all_original_candidate_windows"],1)
        self.assertEqual(x["final_portfolio_event_count"],1)

    def test_target_touch_release_ledger_identical_to_v112(self):
        x=self.compare_with_true_full_prefix(single(n=5,hit=2))
        self.assertEqual(x["final_portfolio_event_count"],2)

    def test_cross_symbol_shared_500usdt_ledger_identical_to_v112(self):
        x=self.compare_with_true_full_prefix(both(n=6,hit_btc=2))
        self.assertEqual(x["all_original_candidate_windows"],2)
        self.assertEqual(x["final_portfolio_event_count"],3)
        self.assertEqual(x["differential_asof_ledger_checks"][-1][
            "open_reservations_at_cutoff"],1)

    def test_bearish_spot_abstention_matches_true_v112_replay(self):
        x=self.compare_with_true_full_prefix(single(n=5,bear=True))
        self.assertEqual(x["all_original_candidate_windows"],1)
        self.assertEqual(x["all_final_hypothetical_reference_proposals"],0)

    def test_first_barrier_early_abstention_matches_v112(self):
        streams=single(n=5)
        coarse,fine,bars=streams["BTCUSDT"]
        bars[0]=bar(bars[0].ms,110,130,105,110)
        x=self.compare_with_true_full_prefix(streams)
        self.assertEqual(x["all_final_hypothetical_reference_proposals"],0)

    def test_no_causal_wave2_candidate_also_matches_v112(self):
        streams=single(n=5)
        coarse,fine,bars=streams["BTCUSDT"]
        streams["BTCUSDT"]=(coarse[:5],fine,bars)
        x=self.compare_with_true_full_prefix(streams)
        self.assertEqual(x["all_original_candidate_windows"],0)
        self.assertEqual(x["all_mandatory_causal_checkpoints"],2)

    def test_original_admission_prefix_stable_when_future_shock_arrives(self):
        early=v113.audit_streaming(single(n=2))
        late=v113.audit_streaming(single(n=5,hit=2))
        a=early["differential_asof_ledger_checks"]
        b=[p for p in late["differential_asof_ledger_checks"]
           if p["source_closed_minutes_per_symbol"]<=2]
        self.assertEqual(a,b)
        self.assertEqual(early["final_portfolio_event_count"],1)
        self.assertEqual(late["final_portfolio_event_count"],2)

    def test_5000_mandatory_minutes_not_sampled_or_truncated(self):
        start=1_000_000*M
        end=start+5_005*M
        checks=[start+i*M for i in range(1,5_001)]
        result=v113.all_checkpoint_timestamps(start,end,checks,[])
        self.assertEqual(len(result),5001)
        self.assertEqual(result[0],start+M)
        self.assertEqual(result[-1],end)
        self.assertEqual(result,sorted(set(result)))

    def test_streaming_ignores_old_4096_cap_but_v112_fail_closed(self):
        streams=single(n=5,hit=2)
        with patch.object(v112,"MAX_MANDATORY_CHECKPOINTS",1):
            with self.assertRaisesRegex(ValueError,"FAIL_CLOSED"):
                v112.audit_every_causal_checkpoint(streams)
            new=v113.audit_streaming(streams)
            self.assertGreater(new["all_mandatory_causal_checkpoints"],1)

    def test_bad_misaligned_original_confirmation_not_accepted(self):
        start=100*M
        end=110*M
        with self.assertRaisesRegex(ValueError,"future/misaligned"):
            v113.all_checkpoint_timestamps(start,end,[start+M+1],[])

    def test_future_checkpoint_cannot_be_inserted(self):
        with self.assertRaisesRegex(ValueError,"future/misaligned"):
            v113.all_checkpoint_timestamps(100*M,110*M,[111*M],[])

    def test_duplicate_mandatory_times_are_deduplicated_not_dropped(self):
        start=100*M
        end=110*M
        result=v113.all_checkpoint_timestamps(
            start,end,[102*M,102*M,104*M],[104*M,105*M])
        self.assertEqual(result,[101*M,102*M,104*M,105*M,110*M])

    def test_tampered_original_full_budget_fails_closed(self):
        series=single(n=5)
        fake=v111.portfolio_census_from_source_streams(series)
        fake["cash_capacity_v110"]["reserved_usdt"]="0"
        with self.assertRaisesRegex(ValueError,"TAMPERED"):
            v113.audit_streaming(series,fake)

    def test_original_barrier_screen_later_modified_fails(self):
        series=single(n=5)
        source=v111.portfolio_census_from_source_streams(series)
        screen=copy.deepcopy(source["all_original_candidate_reference_screens"][0])
        screen["closed_reference_evidence"]["reference_source_price"]="900"
        coarse,fine,bars=series["BTCUSDT"]
        start,end=v112._original_series(series)
        with self.assertRaisesRegex(ValueError,"MATURED_REFERENCE"):
            v113._physical_mature_screen(screen,coarse,bars,start,end)

    def test_original_screen_status_rewrite_rejected(self):
        series=single(n=5)
        source=v111.portfolio_census_from_source_streams(series)
        screen=copy.deepcopy(source["all_original_candidate_reference_screens"][0])
        screen["reference_screen_status"]="FUTURE_WINNER"
        coarse,fine,bars=series["BTCUSDT"]
        start,end=v112._original_series(series)
        with self.assertRaisesRegex(ValueError,"MATURED_REFERENCE"):
            v113._physical_mature_screen(screen,coarse,bars,start,end)

    def test_forged_source_event_or_time_refused(self):
        series=single(n=5)
        coarse,fine,bars=series["BTCUSDT"]
        coarse[-1]=replace(coarse[-1],confirmed_ms=coarse[-1].confirmed_ms+M)
        with self.assertRaises(ValueError):
            v113.audit_streaming(series)

    def test_unresolved_reservation_never_fabricates_release(self):
        proof=v113.audit_streaming(single(n=5))
        self.assertEqual(proof["final_portfolio_event_count"],1)
        self.assertEqual(proof["differential_asof_ledger_checks"][-1][
            "open_reservations_at_cutoff"],1)

    def test_frozen_rulebook_never_rewrites_source_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"V113_PLAN.json"
            a=v113.freeze(path)
            self.assertEqual(a,v113.freeze(path))
            self.assertEqual(a["actual_market_candles"],0)
            self.assertEqual(json.loads(path.read_text())["orders"],0)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"RULEBOOK CHANGED"):
                v113.freeze(path)

    def test_date_gate_refuses_archive_reads_before_november_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v113,"datetime",wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,17,tzinfo=timezone.utc)
                with patch.object(v111,"evaluate_future_sealed_archive") as upstream:
                    with self.assertRaisesRegex(ValueError,"NO_ARCHIVE_READ"):
                        v113.evaluate_future_sealed_archive(Path(tmp))
                    upstream.assert_not_called()

    def test_no_network_order_or_unearned_profit(self):
        rulebook=v113.rules()
        self.assertTrue(rulebook["none_sampled_or_silently_dropped"])
        self.assertTrue(rulebook["streaming_proof_not_equivalent_to_expensive_full_prefix_recomputation"])
        self.assertEqual(rulebook["future_market_rows_read_during_v113"],0)
        self.assertEqual(rulebook["orders"],0)
        self.assertIsNone(v113.ORDER_ADAPTER)
        self.assertTrue(v113.V52_UNCHANGED)
        self.assertFalse(v113.PAPER_ELIGIBLE)
        self.assertFalse(v113.LIVE_ENABLED)
