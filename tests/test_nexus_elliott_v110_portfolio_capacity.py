"""V110 zero-network synthetic shared 500-USDT paper-reference accounting."""
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from research.elliott_v110_portfolio_capacity import capacity_v110 as v110

T=1792368000000
M=60000


def intent(name,symbol="BTCUSDT",time=T,entry="100",stop="90"):
    return v110.Intent(name,symbol,"BUY_SPOT",time,time,D(entry),D(stop))


def resolve(name,when,reason="BARRIER_CLOSED",observed=None):
    return v110.Resolution(name,when if observed is None else observed,
                           when,reason)


class V110PortfolioCapacity(unittest.TestCase):
    def test_empty_portfolio_never_claims_exchange_position(self):
        result=v110.replay([],[],T)
        self.assertEqual(result["original_intents_count"],0)
        self.assertEqual(result["reserved_usdt"],"0")
        self.assertEqual(result["unreserved_cash_usdt"],"500")
        self.assertEqual(result["trade_count"],0)
        self.assertFalse(result["paper_eligible"])
        self.assertIsNone(result["actual_net_pnl"])

    def test_one_spot_long_is_bounded_by_two_sided_stress_loss(self):
        x=v110.replay([intent("a")],[],T)
        self.assertEqual(x["original_intents_count"],1)
        self.assertEqual(x["admitted_hypothetical_intents"],1)
        row=x["append_only_causal_event_ledger"][0]
        self.assertLessEqual(D(row["hypothetical_notional_usdt"]),D("250"))
        self.assertLessEqual(D(row["assumed_gapless_stressed_loss_reserve_usdt"]),D("2.5"))
        self.assertFalse(x["live_enabled"])

    def test_same_symbol_overlap_is_denied_no_duplicate_reservation(self):
        x=v110.replay([intent("a"),intent("b",time=T+M)],[],T+M)
        self.assertEqual(x["admitted_hypothetical_intents"],1)
        self.assertEqual(x["denied_hypothetical_intents"],1)
        self.assertIn("SAME_SYMBOL",x["original_admission_outcomes"]["b"])
        self.assertEqual(len(x["open_symbol_reservations"]),1)

    def test_other_symbol_independent_but_shared_500_cash(self):
        x=v110.replay([intent("a","BTCUSDT"),intent("b","ETHUSDT")],[],T)
        self.assertEqual(x["admitted_hypothetical_intents"],2)
        self.assertEqual(x["denied_hypothetical_intents"],0)
        self.assertLessEqual(D(x["reserved_usdt"]),D("500"))
        self.assertLessEqual(D(x["stressed_gapless_risk_reserve_usdt"]),D("5"))
        self.assertEqual(set(x["open_symbol_reservations"].values()),
                         {"BTCUSDT","ETHUSDT"})

    def test_third_candidate_rejected_when_both_capacity_slots_used(self):
        all_intents=[intent("a","BTCUSDT"),intent("b","ETHUSDT"),
                     intent("c","BTCUSDT",T+M)]
        x=v110.replay(all_intents,[],T+M)
        self.assertEqual(x["admitted_hypothetical_intents"],2)
        self.assertIn("MAX_CONCURRENT",x["original_admission_outcomes"]["c"])
        self.assertEqual(x["original_intents_count"],3)

    def test_unknown_future_release_does_not_free_cash(self):
        x=v110.replay([intent("a"),intent("b",time=T+M)],[],T+M)
        self.assertEqual(x["denied_hypothetical_intents"],1)
        self.assertEqual(x["known_resolutions_count"],0)
        self.assertGreater(D(x["reserved_usdt"]),0)

    def test_known_release_at_same_minute_precedes_new_intent(self):
        source=[intent("a"),intent("b",time=T+3*M)]
        x=v110.replay(source,[resolve("a",T+3*M)],T+3*M)
        self.assertEqual(x["admitted_hypothetical_intents"],2)
        self.assertEqual(x["denied_hypothetical_intents"],0)
        self.assertEqual([p["event"] for p in x["append_only_causal_event_ledger"]],
                         ["SYNTHETIC_CAPACITY_RESERVED_NOT_ORDER",
                          "RELEASE_KNOWN","SYNTHETIC_CAPACITY_RESERVED_NOT_ORDER"])
        self.assertEqual(set(x["open_symbol_reservations"]),{"b"})

    def test_delayed_known_release_keeps_reservation_until_known(self):
        proposals=[intent("a"),intent("b",time=T+2*M),
                   intent("c",time=T+4*M)]
        late=resolve("a",T+4*M,observed=T+M)
        x=v110.replay(proposals,[late],T+4*M)
        self.assertIn("DENIED_",x["original_admission_outcomes"]["b"])
        self.assertEqual(x["original_admission_outcomes"]["c"],
                         "HYPOTHETICAL_RESERVED")
        self.assertEqual(x["known_resolutions_count"],1)

    def test_future_events_do_not_rewrite_original_replay_ledger(self):
        first=[intent("a")]
        early=v110.replay(first,[],T)
        extended=v110.replay(first+[intent("b",time=T+M)],
                             [resolve("a",T+2*M)],T+2*M)
        self.assertEqual(early["append_only_causal_event_ledger"],
                         extended["append_only_causal_event_ledger"][:1])
        self.assertEqual(early["original_admission_outcomes"]["a"],
                         extended["original_admission_outcomes"]["a"])

    def test_order_of_unsorted_source_objects_cannot_change_allocation(self):
        a=intent("b","BTCUSDT")
        b=intent("a","BTCUSDT")
        x=v110.replay([a,b],[],T)
        y=v110.replay([b,a],[],T)
        self.assertEqual(x,y)
        self.assertEqual(x["original_admission_outcomes"]["a"],
                         "HYPOTHETICAL_RESERVED")
        self.assertIn("DENIED_",x["original_admission_outcomes"]["b"])

    def test_resolution_of_denied_candidate_is_forbidden(self):
        proposals=[intent("a"),intent("b",time=T+M)]
        with self.assertRaisesRegex(ValueError,"inactive or denied"):
            v110.replay(proposals,[resolve("b",T+2*M)],T+2*M)

    def test_release_cannot_be_backdated_into_original_decision(self):
        proposals=[intent("a")]
        with self.assertRaisesRegex(ValueError,"future result"):
            v110.replay(proposals,[resolve("a",T-M)],T)

    def test_only_one_release_per_original_identifier(self):
        with self.assertRaisesRegex(ValueError,"duplicated or unknown"):
            v110.replay([intent("a")],
                        [resolve("a",T+M),resolve("a",T+2*M)],T+2*M)

    def test_no_release_for_nonexistent_position(self):
        with self.assertRaisesRegex(ValueError,"duplicated or unknown"):
            v110.replay([intent("a")],[resolve("imaginary",T+M)],T+M)

    def test_unobserved_future_intent_must_not_be_inserted(self):
        with self.assertRaisesRegex(ValueError,"future candidate"):
            v110.replay([intent("a",time=T+M)],[],T)

    def test_unobserved_future_resolution_must_not_be_inserted(self):
        with self.assertRaisesRegex(ValueError,"future release"):
            v110.replay([intent("a")],[resolve("a",T+M)],T)

    def test_stop_wrong_side_abstains_from_reserve(self):
        x=v110.replay([intent("a",entry="100",stop="105")],[],T)
        self.assertIn("DENIED_INVALID_OR_NONPOSITIVE",
                      x["original_admission_outcomes"]["a"])
        self.assertEqual(x["reserved_usdt"],"0")

    def test_spot_short_and_unknown_exchange_never_admitted(self):
        for invalid in (
            replace(intent("a"),side="SELL_SHORT"),
            replace(intent("a"),symbol="XRPUSDT"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError,"spot BUY only"):
                    v110.replay([invalid],[],T)

    def test_unknown_future_outcome_cannot_be_embedded_in_intent(self):
        import dataclasses
        with self.assertRaises(TypeError):
            v110.Intent("a","BTCUSDT","BUY_SPOT",T,T,D("100"),D("90"),
                        "future_pnl")

    def test_future_reference_appearing_after_decision_is_rejected(self):
        bad=replace(intent("a"),reference_known_ms=T+M)
        with self.assertRaisesRegex(ValueError,"causally known"):
            v110.replay([bad],[],T)

    def test_nan_untyped_negative_reference_rejected(self):
        for invalid in ("NaN","-1",0):
            with self.subTest(value=invalid):
                bad=replace(intent("a"),hypothetical_entry_close=(
                    invalid if isinstance(invalid,int) else D(invalid)))
                with self.assertRaisesRegex(ValueError,"finite positive"):
                    v110.replay([bad],[],T)

    def test_invalid_resolution_type_or_time_order_rejected(self):
        invalid=v110.Resolution("a",T+2*M,T+M,"BARRIER_CLOSED")
        with self.assertRaisesRegex(ValueError,"explicitly known"):
            v110.replay([intent("a")],[invalid],T+2*M)

    def test_malicious_repeated_candidate_cannot_mint_cash(self):
        with self.assertRaisesRegex(ValueError,"twice"):
            v110.replay([intent("a"),intent("a")],[],T)

    def test_continuous_capacity_invariants_under_20_overlaps(self):
        intents=[intent("c"+str(i),
                        "BTCUSDT" if i%2==0 else "ETHUSDT",
                        T+i*M,entry="100",stop="80") for i in range(20)]
        x=v110.replay(intents,[],T+19*M)
        self.assertEqual(x["original_intents_count"],20)
        self.assertEqual(x["admitted_hypothetical_intents"],2)
        self.assertEqual(x["denied_hypothetical_intents"],18)
        self.assertLessEqual(D(x["reserved_usdt"]),D("500"))
        self.assertLessEqual(D(x["stressed_gapless_risk_reserve_usdt"]),D("5"))
        self.assertEqual(len(x["append_only_causal_event_ledger"]),20)
        self.assertEqual(x["trade_count"],0)

    def test_rulebook_frozen_bytes_and_v109_locked_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"V110_PORTFOLIO_CAPACITY.json"
            one=v110.freeze_rulebook(f)
            self.assertEqual(one,v110.freeze_rulebook(f))
            self.assertEqual(f.read_bytes(),v110.frozen_bytes())
            self.assertEqual(one["original_market_rows_accessed"],0)
            self.assertEqual(json.loads(f.read_text())["real_trades_placed"],0)
            f.write_text("{}")
            with self.assertRaisesRegex(ValueError,"DIFFERS"):
                v110.freeze_rulebook(f)

    def test_both_near_stop_symbols_cannot_exceed_500_after_entry_friction(self):
        sample=[
            intent("btc","BTCUSDT",entry="100",stop="99.99"),
            intent("eth","ETHUSDT",entry="100",stop="99.99")
        ]
        x=v110.replay(sample,[],T)
        self.assertEqual(x["admitted_hypothetical_intents"],2)
        self.assertLessEqual(D(x["reserved_usdt"]),D("500"))
        self.assertGreaterEqual(D(x["unreserved_cash_usdt"]),D("0"))
        original_notional=sum(
            D(e["hypothetical_notional_usdt"]) for e in
            x["append_only_causal_event_ledger"])
        self.assertGreater(D(x["reserved_usdt"]),original_notional)
        self.assertLessEqual(D(x["stressed_gapless_risk_reserve_usdt"]),D("5"))

    def test_release_refunds_notional_and_buy_fee_cash_reserve(self):
        sample=[
            intent("btc","BTCUSDT",entry="100",stop="99.99"),
            intent("eth","ETHUSDT",entry="100",stop="99.99")
        ]
        before=v110.replay(sample,[],T)
        after=v110.replay(sample,[resolve("btc",T+M)],T+M)
        first_cash=D(before["append_only_causal_event_ledger"][0][
            "hypothetical_buy_cash_plus_entry_stress_usdt"])
        self.assertEqual(D(before["reserved_usdt"])-first_cash,
                         D(after["reserved_usdt"]))
        self.assertEqual(after["known_resolutions_count"],1)
        self.assertEqual(after["trade_count"],0)
