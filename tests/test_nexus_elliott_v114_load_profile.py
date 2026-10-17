"""V114 synthetic event journal stress, faults, timing evidence contract."""
import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from research.elliott_v114_load_profile import profile_v114 as v114
from research.elliott_v110_portfolio_capacity import capacity_v110 as v110
from research.elliott_v113_incremental_audit import incremental_v113 as v113


def prepared(n=30):
    intents,closed,asof=v114.fixed_fixture(n)
    original=v110.replay(intents,closed,asof)
    return intents,closed,asof,original


class V114IndependentJournalStressQA(unittest.TestCase):
    def test_30_intents_two_realized_synthetic_reservations_only(self):
        intents,closed,end,original=prepared()
        proof=v114.verify_all_events(intents,closed,end,original)
        self.assertEqual(proof["all_source_intents"],30)
        self.assertEqual(proof["all_explicit_synthetic_resolutions"],2)
        self.assertEqual(proof["all_event_checkpoints_checked"],32)
        self.assertEqual(proof["record_counts"]["hypothetical_reserved"],2)
        self.assertEqual(proof["record_counts"]["explicit_synthetic_closures"],2)
        self.assertEqual(Decimal(proof["current_hypothetical_reserved_cash"]),0)
        self.assertEqual(proof["actual_orders"],0)
        self.assertIsNone(proof["net_pnl"])

    def test_same_minute_releases_precede_next_original_admissions(self):
        intents,closed,end,original=prepared(60)
        proof=v114.verify_all_events(intents,closed,end,original)
        self.assertEqual(proof["all_event_checkpoints_checked"],64)
        events=original["append_only_causal_event_ledger"]
        boundary=v114.BASE+30*v114.MIN
        exactly=[e for e in events if e["known_at_ms"]==boundary]
        self.assertEqual([e["event"] for e in exactly],
            ["RELEASE_KNOWN","RELEASE_KNOWN",
             "SYNTHETIC_CAPACITY_RESERVED_NOT_ORDER"])
        self.assertEqual(proof["record_counts"]["hypothetical_reserved"],4)

    def test_full_prefix_SHA_after_all_events_matches_standard_hash(self):
        intents,closed,end,original=prepared(60)
        proof=v114.verify_all_events(intents,closed,end,original)
        raw=json.dumps(original["append_only_causal_event_ledger"],
                       sort_keys=True,ensure_ascii=False).encode()
        self.assertEqual(proof["full_cash_event_log_sha256"],
                         hashlib.sha256(raw).hexdigest())
        self.assertEqual(proof["checkpoint_prefix_sha256_last"],
                         hashlib.sha256(raw).hexdigest())
        self.assertEqual(proof["all_prefix_sha256_created"] if
            "all_prefix_sha256_created" in proof else
            proof["all_event_prefix_sha256_created"],64)

    def test_all_4200_plus_release_checkpoints_without_4096_sample_cap(self):
        intents,closed,end,original=prepared(4200)
        proof=v114.verify_all_events(intents,closed,end,original)
        self.assertEqual(proof["all_event_checkpoints_checked"],4480)
        self.assertEqual(proof["all_event_prefix_sha256_created"],4480)
        self.assertEqual(proof["record_counts"]["hypothetical_reserved"],280)
        self.assertEqual(proof["record_counts"]["explicit_synthetic_closures"],280)
        self.assertEqual(Decimal(proof["current_hypothetical_gapless_risk"]),0)
        self.assertFalse(v113.PAPER_ELIGIBLE)

    def test_missing_original_intent_event_detected(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        del damaged["append_only_causal_event_ledger"][5]
        with self.assertRaisesRegex(ValueError,"DENOMINATOR"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_extra_forged_event_refused(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["append_only_causal_event_ledger"].append(
            copy.deepcopy(damaged["append_only_causal_event_ledger"][-1]))
        with self.assertRaisesRegex(ValueError,"DENOMINATOR"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_backdated_event_known_at_cannot_rewrite_prior_admission(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["append_only_causal_event_ledger"][1]["known_at_ms"]-=v114.MIN
        with self.assertRaisesRegex(ValueError,"SOURCE_TIME"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_swapping_equal_time_release_order_invalidates_identity(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        a=damaged["append_only_causal_event_ledger"]
        a[-2],a[-1]=a[-1],a[-2]
        with self.assertRaisesRegex(ValueError,"SOURCE_TIME"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_future_winner_claim_cannot_be_inserted_in_journal(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["append_only_causal_event_ledger"][0]["future_profit_USDT"]=123
        with self.assertRaisesRegex(ValueError,"TAMPERED"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_forged_usdt_cash_balance_detected(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["append_only_causal_event_ledger"][0][
            "reserved_capital_after"]="0"
        with self.assertRaisesRegex(ValueError,"TAMPERED"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_forged_reserved_risk_detected(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["append_only_causal_event_ledger"][0][
            "assumed_gapless_stressed_loss_reserve_usdt"]="999"
        with self.assertRaisesRegex(ValueError,"TAMPERED"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_exit_observed_closed_timestamp_forgery_detected(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["append_only_causal_event_ledger"][-1][
            "observed_closed_ms"]-=v114.MIN
        with self.assertRaisesRegex(ValueError,"TAMPERED"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_denial_does_not_get_reclassified_as_admission(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["append_only_causal_event_ledger"][2][
            "event"]="SYNTHETIC_CAPACITY_RESERVED_NOT_ORDER"
        with self.assertRaisesRegex(ValueError,"TAMPERED"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_unknown_cancellation_reason_does_not_mint_cash(self):
        intents,closed,end,original=prepared()
        altered=list(closed)
        altered[0]=replace(altered[0],reason="FUTURE_PROFIT")
        with self.assertRaises(ValueError):
            v114.verify_all_events(intents,altered,end,original)

    def test_duplicate_closure_event_refused(self):
        intents,closed,end,original=prepared()
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            v114.verify_all_events(intents,[closed[0],closed[0]],end,original)

    def test_original_final_budget_tamper_detected(self):
        intents,closed,end,original=prepared()
        damaged=copy.deepcopy(original)
        damaged["unreserved_cash_usdt"]="1000"
        with self.assertRaisesRegex(ValueError,"FINAL_CAPACITY"):
            v114.verify_all_events(intents,closed,end,damaged)

    def test_future_resolution_or_original_intent_cannot_enter_today(self):
        intents,closed,end,original=prepared()
        with self.assertRaises(ValueError):
            v114.verify_all_events(intents,closed,end-v114.MIN,original)

    def test_replay_and_verify_unchanged_for_reversed_input_object_order(self):
        intents,closed,end,original=prepared(60)
        result=v114.verify_all_events(list(reversed(intents)),
                                      list(reversed(closed)),end,original)
        self.assertEqual(result["all_event_checkpoints_checked"],64)

    def test_nonmatching_input_size_is_explicitly_refused(self):
        for wrong in (0,31,-30,True):
            with self.subTest(wrong=wrong):
                with self.assertRaisesRegex(ValueError,"positive complete"):
                    v114.fixed_fixture(wrong)

    def test_static_rulebook_preserves_v113_parent_and_no_market(self):
        p=v114.locked_rules()
        self.assertEqual(p["v113_predecessor_commit"],v114.PARENT_COMMIT)
        self.assertTrue(p["benchmark_is_journal_only_not_full_v99_v107_source_scaling"])
        self.assertTrue(p["all_checkpoint_prefix_hashes_computed_not_sampled"])
        self.assertEqual(p["actual_market_data_evaluated"],0)
        self.assertEqual(p["orders"],0)
        self.assertIsNone(v114.ORDER_ADAPTER)
        self.assertFalse(v114.LIVE_ENABLED)
        self.assertTrue(v114.V52_UNCHANGED)

    def test_frozen_protocol_rejects_silent_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"V114_RULES.json"
            proof=v114.freeze(path)
            self.assertEqual(proof,v114.freeze(path))
            self.assertEqual(proof["actual_orders"],0)
            self.assertEqual(proof["real_market_rows"],0)
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError,"LOCKED"):
                v114.freeze(path)
