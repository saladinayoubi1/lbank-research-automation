"""V112 adversarial temporal-prefix tests, only synthetic BTC/ETH, no HTTP."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v111_source_capacity import sample
from test_nexus_elliott_v108_forward_outcomes import bar
from research.elliott_v112_prefix_audit import audit_v112 as v112
from research.elliott_v111_source_capacity import bridge_v111 as v111
from research.elliott_v110_portfolio_capacity import capacity_v110 as v110

M=60000


def single(n=5,hit=None,bear=False):
    coarse,fine,t,bars=sample(bear=bear,ext=n)
    if hit is not None:
        bars[hit]=bar(t+hit*M,110,125,105,120)
    return {"BTCUSDT":(coarse,fine,bars)}


def both(n=6,hit_btc=None):
    s=single(n,hit_btc)
    coarse,fine,t,bars=sample(ext=n)
    s["ETHUSDT"]=(coarse,fine,bars)
    return s


class V112TemporalPrefixAuditor(unittest.TestCase):
    def test_complete_five_bar_snapshot_replays_identical_original_admission(self):
        streams=single(n=5)
        a=v112.audit_every_causal_checkpoint(streams)
        self.assertEqual(a["all_original_candidate_windows"],1)
        self.assertEqual(a["all_final_hypothetical_reference_proposals"],1)
        self.assertEqual(a["all_mandatory_causal_checkpoints"],3)
        self.assertTrue(a["no_checkpoint_omitted"])
        self.assertEqual(a["final_portfolio_event_count"],1)
        self.assertEqual(a["trade_count"],0)
        self.assertIsNone(a["net_pnl"])
        self.assertFalse(a["paper_eligible"])

    def test_known_stop_or_target_release_can_only_append_new_event(self):
        streams=single(n=5,hit=2)
        result=v112.audit_every_causal_checkpoint(streams)
        self.assertEqual(result["final_portfolio_event_count"],2)
        self.assertEqual(result["all_final_hypothetical_reference_proposals"],1)
        self.assertIn(2,[x["observable_cash_events"] for x in result[
            "differential_asof_ledger_checks"]])
        checkpoints=result["differential_asof_ledger_checks"]
        event_counts=[x["observable_cash_events"] for x in checkpoints]
        self.assertEqual(event_counts,sorted(event_counts))

    def test_both_pairs_share_original_one_portfolio_timeline(self):
        streams=both(n=6,hit_btc=2)
        result=v112.audit_every_causal_checkpoint(streams)
        self.assertEqual(result["all_original_candidate_windows"],2)
        self.assertEqual(result["all_final_hypothetical_reference_proposals"],2)
        self.assertEqual(result["final_portfolio_event_count"],3)
        self.assertEqual(result["trade_count"],0)
        all_checkpoints=result["differential_asof_ledger_checks"]
        self.assertEqual(all_checkpoints[-1][
            "open_reservations_at_cutoff"],1)

    def test_future_price_shock_cannot_change_prior_prefix_decision(self):
        base=single(n=2)
        advanced=single(n=5,hit=2)
        early=v112.audit_every_causal_checkpoint(base)
        later=v112.audit_every_causal_checkpoint(advanced)
        first_in_later=[x for x in later["differential_asof_ledger_checks"]
                        if x["source_closed_minutes_per_symbol"]<=2]
        self.assertEqual(early["differential_asof_ledger_checks"],
                         first_in_later)
        self.assertEqual(early["final_portfolio_event_count"],1)
        self.assertEqual(later["final_portfolio_event_count"],2)

    def test_five_completed_coarse_events_are_not_validated_as_wave2(self):
        streams=single(n=5)
        coarse,fine,bars=streams["BTCUSDT"]
        early=(coarse[:5],fine[:],bars)
        early_streams={"BTCUSDT":early}
        a=v112.audit_every_causal_checkpoint(early_streams)
        self.assertEqual(a["all_original_candidate_windows"],0)
        self.assertEqual(a["all_final_hypothetical_reference_proposals"],0)
        self.assertEqual(a["final_portfolio_event_count"],0)

    def test_bearish_candidate_retained_not_spot_short_entered(self):
        streams=single(n=5,bear=True)
        r=v112.audit_every_causal_checkpoint(streams)
        self.assertEqual(r["all_original_candidate_windows"],1)
        self.assertEqual(r["all_final_hypothetical_reference_proposals"],0)

    def test_price_barrier_in_first_minute_keeps_source_abstention(self):
        streams=single(n=5)
        coarse,fine,bars=streams["BTCUSDT"]
        bars[0]=bar(bars[0].ms,110,130,105,110)
        r=v112.audit_every_causal_checkpoint(streams)
        self.assertEqual(r["all_original_candidate_windows"],1)
        self.assertEqual(r["all_final_hypothetical_reference_proposals"],0)

    def test_tampered_provided_final_cash_balance_cannot_be_accepted(self):
        streams=single(n=5)
        declared=v111.portfolio_census_from_source_streams(streams)
        declared["cash_capacity_v110"]["reserved_usdt"]="0"
        with self.assertRaisesRegex(ValueError,"FINAL_CANDIDATE"):
            v112.audit_every_causal_checkpoint(streams,declared)

    def test_tampered_earlier_admission_rejected_before_time_audit(self):
        streams=single(n=5)
        declared=v111.portfolio_census_from_source_streams(streams)
        declared["cash_capacity_v110"]["append_only_causal_event_ledger"][0][
            "candidate_id"]="some-future-winner"
        with self.assertRaisesRegex(ValueError,"FINAL_CANDIDATE"):
            v112.audit_every_causal_checkpoint(streams,declared)

    def test_complete_cutoff_cannot_extend_past_original_1m_bars(self):
        streams=single(n=5)
        beginning,end=v112._original_series(streams)
        with self.assertRaisesRegex(ValueError,"out-of-period"):
            v112.prefix_series_at(streams,end+M)
        with self.assertRaisesRegex(ValueError,"out-of-period"):
            v112.prefix_series_at(streams,beginning)

    def test_all_predeclared_checkpoints_including_source_end(self):
        streams=single(n=5,hit=2)
        full=v111.portfolio_census_from_source_streams(streams)
        timeline=v112.complete_checkpoint_set(streams,full)
        start,end=v112._original_series(streams)
        self.assertEqual(timeline[0],start+M)
        self.assertEqual(timeline[-1],end)
        self.assertIn(start+2*M,timeline)
        self.assertIn(start+3*M,timeline)
        self.assertEqual(len(timeline),len(set(timeline)))

    def test_no_sampling_allowed_if_mandatory_checkpoints_exceed_cap(self):
        streams=single(n=5,hit=2)
        full=v111.portfolio_census_from_source_streams(streams)
        with patch.object(v112,"MAX_MANDATORY_CHECKPOINTS",1):
            with self.assertRaisesRegex(ValueError,"FAIL_CLOSED"):
                v112.complete_checkpoint_set(streams,full)

    def test_gap_in_physical_bars_fails_without_partial_claim(self):
        streams=single(n=5)
        coarse,fine,bars=streams["BTCUSDT"]
        bars[1]=replace(bars[1],ms=bars[0].ms)
        with self.assertRaisesRegex(ValueError,"gap/duplicate"):
            v112.audit_every_causal_checkpoint(streams)

    def test_tainted_pivot_from_future_fails_before_checkpoints(self):
        streams=single(n=5)
        coarse,fine,bars=streams["BTCUSDT"]
        future=replace(coarse[-1],confirmed_ms=coarse[-1].confirmed_ms+
                       30*M,confirmed_index=coarse[-1].confirmed_index+30)
        coarse[-1]=future
        with self.assertRaises(ValueError):
            v112.audit_every_causal_checkpoint(streams)

    def test_source_periods_of_two_assets_must_match(self):
        streams=both(n=5)
        coarse,fine,bars=streams["ETHUSDT"]
        streams["ETHUSDT"]=(coarse,fine,bars[:-1])
        with self.assertRaisesRegex(ValueError,"cross-symbol"):
            v112.audit_every_causal_checkpoint(streams)

    def test_future_sealed_archive_is_hard_blocked_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v112,"datetime",wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,17,tzinfo=timezone.utc)
                with patch.object(v111,"evaluate_future_sealed_archive") as future:
                    with self.assertRaisesRegex(ValueError,"NO_ARCHIVE_READ"):
                        v112.evaluate_future_sealed_archive(Path(tmp))
                    future.assert_not_called()

    def test_no_other_market_or_spot_short_orders(self):
        self.assertTrue(v112.RESEARCH_ONLY)
        self.assertFalse(v112.PAPER_ELIGIBLE)
        self.assertFalse(v112.ENTRY_SIGNAL)
        self.assertFalse(v112.LIVE_ENABLED)
        self.assertIsNone(v112.ORDER_ADAPTER)
        self.assertTrue(v112.V52_UNCHANGED)
        self.assertEqual(v112.rulebook()["orders"],0)

    def test_frozen_rulebook_sha_stable_and_mutation_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"V112_FROZEN.json"
            a=v112.freeze(path)
            self.assertEqual(a,v112.freeze(path))
            self.assertEqual(a["market_rows_evaluated"],0)
            self.assertEqual(a["actual_orders"],0)
            self.assertEqual(json.loads(path.read_text())["orders"],0)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"MUTATED"):
                v112.freeze(path)

    def test_sealed_source_status_overlay_allows_only_exact_known_fields(self):
        streams=single(n=5)
        original=v111.portfolio_census_from_source_streams(streams)
        sealed=copy.deepcopy(original)
        sealed.update({
            "source_status":"AFTER_FROZEN_PERIOD_TWO_PARSERS_SAME_ARCHIVE",
            "exchange_payload_cryptographically_authenticated":False,
            "two_parser_agreement_is_not_independent_venue_observation":True,
            "original_complete_1m_rows_per_symbol":20160,
        })
        self.assertIsNone(v112.verify_sealed_v111_source_overlay(sealed,original))

    def test_forged_sealed_source_signature_overclaim_refused(self):
        streams=single(n=5)
        original=v111.portfolio_census_from_source_streams(streams)
        sealed=copy.deepcopy(original)
        sealed.update({
            "source_status":"AFTER_FROZEN_PERIOD_TWO_PARSERS_SAME_ARCHIVE",
            "exchange_payload_cryptographically_authenticated":True,
            "two_parser_agreement_is_not_independent_venue_observation":True,
            "original_complete_1m_rows_per_symbol":20160,
        })
        with self.assertRaisesRegex(ValueError,"ledger disagrees"):
            v112.verify_sealed_v111_source_overlay(sealed,original)

    def test_sealed_source_cash_event_rewrite_rejected_not_whitelisted(self):
        streams=single(n=5)
        original=v111.portfolio_census_from_source_streams(streams)
        sealed=copy.deepcopy(original)
        sealed.update({
            "source_status":"AFTER_FROZEN_PERIOD_TWO_PARSERS_SAME_ARCHIVE",
            "exchange_payload_cryptographically_authenticated":False,
            "two_parser_agreement_is_not_independent_venue_observation":True,
            "original_complete_1m_rows_per_symbol":20160,
        })
        sealed["cash_capacity_v110"]["append_only_causal_event_ledger"][0][
            "candidate_id"]="fake-retroactive"
        with self.assertRaisesRegex(ValueError,"ledger disagrees"):
            v112.verify_sealed_v111_source_overlay(sealed,original)

    def test_unexpected_sealed_source_extra_metadata_refused(self):
        streams=single(n=5)
        original=v111.portfolio_census_from_source_streams(streams)
        sealed=copy.deepcopy(original)
        sealed.update({
            "source_status":"AFTER_FROZEN_PERIOD_TWO_PARSERS_SAME_ARCHIVE",
            "exchange_payload_cryptographically_authenticated":False,
            "two_parser_agreement_is_not_independent_venue_observation":True,
            "original_complete_1m_rows_per_symbol":20160,
            "secret_external_certification":True,
        })
        with self.assertRaisesRegex(ValueError,"ledger disagrees"):
            v112.verify_sealed_v111_source_overlay(sealed,original)
