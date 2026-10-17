"""Adversarial purely SYNTHETIC V25 actionable clock tests; no exchange IO."""
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal

from nexus_elliott_causal_clock_v25 import (
    RESEARCH_ONLY,LIVE_ENABLED,AUTO_DEMO,PAPER_ELIGIBLE,BROKER_FILL_VERIFIED,
    PROSPECTIVE_STRATEGY_REGISTERED,verify_temporal_feasibility,
)

DECISION=datetime(2026,10,16,0,15,tzinfo=timezone.utc)
SHORT=timedelta(milliseconds=200)
LATE=timedelta(seconds=1)


def obs():
    return {
        "event_id":"synthetic_v25_BTC_001","symbol":"BTCUSDT",
        "decision_close_utc":DECISION,
        "previous_close":"109","decision_close":"112",
        "fifth_high":"110","correction_low":"100",
        "source_bound_seven_pivot":True,"closed_first_breakout":True,
        "post_correction_path_valid":True,
    }


def bar(*, high="145", low="111", op="112", close="112"):
    return [{"open_at":DECISION,"open":op,"high":high,
             "low":low,"close":close}]


def inspect(source=DECISION,signal=DECISION,quote=DECISION,
            future=None,profile="conservative",evaluated=None,observation=None):
    return verify_temporal_feasibility(
        obs() if observation is None else observation,
        bar() if future is None else future,
        profile=profile,
        source_received_at_utc=source,
        signal_committed_at_utc=signal,
        entry_quote_received_at_utc=quote,
        evaluated_asof_utc=DECISION+timedelta(minutes=15) if evaluated is None else evaluated,
    )


class CausalClockV25Tests(unittest.TestCase):
    def test_still_only_research(self):
        self.assertTrue(RESEARCH_ONLY)
        for flag in (LIVE_ENABLED,AUTO_DEMO,PAPER_ELIGIBLE,
                     BROKER_FILL_VERIFIED,PROSPECTIVE_STRATEGY_REGISTERED):
            self.assertFalse(flag)

    def test_ideal_zero_latency_still_cannot_claim_broker_fill(self):
        r=inspect()
        self.assertEqual(r["clock_disposition"],
                         "IDEAL_ZERO_LATENCY_CLOCK_ONLY_NOT_FILL_PROOF")
        self.assertFalse(r["broker_fill_verified"])
        self.assertFalse(r["may_treat_v17_fill_as_executable"])
        self.assertFalse(r["may_count_as_profitable_trading_result"])
        self.assertFalse(r["decision_and_quote_clock_attestation_independent"])
        self.assertGreater(Decimal(r["v17_original_hypothetical_net_pnl_not_executable"]),0)

    def test_signal_generated_after_open_cannot_claim_old_open_fill(self):
        r=inspect(signal=DECISION+SHORT,quote=DECISION+LATE)
        self.assertEqual(r["clock_disposition"],"SIMULATED_NEXT_OPEN_FILL_PRECEDES_SIGNAL")
        self.assertIn("SIGNAL_PUBLISHED_AFTER_NEXT_OPEN_NO_RETROACTIVE_FILL",r["warning_codes"])
        self.assertFalse(r["may_treat_v17_fill_as_executable"])
        self.assertEqual(r["next_open_latency_signal_seconds"],"0.2")

    def test_feed_received_late_adds_source_and_quote_warning(self):
        r=inspect(source=DECISION+SHORT,signal=DECISION+SHORT,
                  quote=DECISION+LATE)
        self.assertIn("BAR_CLOSE_DELIVERY_LATENCY_EXCLUDES_NEXT_OPEN",r["warning_codes"])
        self.assertIn("ENTRY_OPEN_ALREADY_PASSED_WHEN_QUOTE_OBSERVED",r["warning_codes"])

    def test_quote_late_zero_latency_decision_is_not_fill(self):
        r=inspect(source=DECISION,signal=DECISION,quote=DECISION+SHORT)
        self.assertEqual(r["clock_disposition"],
                         "SIMULATED_NEXT_OPEN_FILL_PRECEDES_QUOTE_OBSERVATION")

    def test_source_cannot_precede_candle_close(self):
        with self.assertRaisesRegex(ValueError,"before source candle was closed"):
            inspect(source=DECISION-SHORT)

    def test_signal_cannot_precede_received_source(self):
        with self.assertRaisesRegex(ValueError,"signal committed before"):
            inspect(source=DECISION+SHORT,signal=DECISION)

    def test_quote_cannot_precede_signal(self):
        with self.assertRaisesRegex(ValueError,"predates signal"):
            inspect(signal=DECISION+LATE,quote=DECISION+SHORT)

    def test_future_review_cannot_precede_quote(self):
        with self.assertRaisesRegex(ValueError,"future review predates"):
            inspect(signal=DECISION+LATE,
                    quote=DECISION+timedelta(minutes=16))

    def test_aware_offsets_normalize_with_subsecond_precision(self):
        ist=timezone(timedelta(hours=3,minutes=30))
        q=(DECISION+SHORT).astimezone(ist)
        result=inspect(quote=q)
        self.assertEqual(result["entry_quote_received_at_utc"],
                         "2026-10-16T00:15:00.200000+00:00")

    def test_naive_and_string_clocks_rejected(self):
        for bad in (DECISION.replace(tzinfo=None),"2026-10-16T00:15:00Z"):
            with self.subTest(bad=bad),self.assertRaisesRegex(
                ValueError,"timezone-aware"
            ):
                inspect(signal=bad)

    def test_fixed_v17_stop_first_negative_preserved_even_if_late(self):
        r=inspect(future=bar(high="145",low="99"),
                  source=DECISION+SHORT,signal=DECISION+SHORT,quote=DECISION+LATE)
        self.assertEqual(r["v17_original_hypothetical_exit_reason"],"stop")
        self.assertLess(Decimal(r["v17_original_hypothetical_net_pnl_not_executable"]),0)
        self.assertIn("BOTH_STOP_AND_TARGET_INSIDE_CANDLE_STOP_FIRST",r["warning_codes"])

    def test_breakout_reentry_not_rewritten_into_winner(self):
        r=inspect(future=bar(op="109",high="111",low="108",close="110"))
        self.assertFalse(r["v24_price_only_gate_passed"])
        self.assertIn("NEXT_OPEN_REENTERED_PRE_BREAKOUT_RANGE",r["warning_codes"])
        self.assertIsNone(r["v17_original_hypothetical_net_pnl_not_executable"])

    def test_time_gap_entry_ohlc_at_same_boundary_cannot_retroactively_fill(self):
        r=inspect(signal=DECISION+timedelta(milliseconds=1),
                  quote=DECISION+timedelta(milliseconds=2))
        self.assertEqual(r["v17_original_hypothetical_exit_reason"],"target")
        self.assertFalse(r["may_treat_v17_fill_as_executable"])

    def test_different_friction_preserves_original_hypothetical_difference(self):
        a=inspect(profile="conservative")
        b=inspect(profile="stress")
        self.assertGreater(Decimal(a["v17_original_hypothetical_net_pnl_not_executable"]),
                           Decimal(b["v17_original_hypothetical_net_pnl_not_executable"]))
        self.assertFalse(a["paper_eligible"])
        self.assertFalse(b["paper_eligible"])


if __name__=="__main__":
    unittest.main()
