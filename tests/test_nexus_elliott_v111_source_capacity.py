"""V111 pure synthetic original-source-to-V110 capacity bridge, NO HTTP."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from test_nexus_elliott_v106_early_partial import synthetic,MIN
from test_nexus_elliott_v108_forward_outcomes import bar,follow
from research.elliott_v111_source_capacity import bridge_v111 as v111
from research.elliott_v110_portfolio_capacity import capacity_v110 as v110
from research.elliott_v107_prefix_census import census_v107 as v107


def sample(bear=False,ext=5):
    coarse,fine,t=synthetic(bear)
    # Within original 1-2 levels for a BUY: Wave0=100, Wave1=120.
    physical=[bar(t+i*MIN,110,115,105,110) for i in range(ext)]
    if bear:
        physical=[bar(t+i*MIN,220,225,215,220) for i in range(ext)]
    return coarse,fine,t,physical


class V111SourceBoundCapacityTests(unittest.TestCase):
    def test_bull_two_completed_minutes_makes_reference_not_order(self):
        coarse,fine,t,candles=sample()
        result=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,candles)
        self.assertEqual(len(result["original_candidate_screens"]),1)
        self.assertEqual(len(result["hypothetical_intents"]),1)
        idea=result["hypothetical_intents"][0]
        self.assertEqual(idea.decision_asof_ms,t+2*MIN)
        self.assertEqual(idea.reference_known_ms,t+2*MIN)
        self.assertEqual(idea.hypothetical_entry_close,candles[1].close)
        self.assertEqual(idea.side,"BUY_SPOT")
        self.assertFalse(result["real_market_source_authenticated"])

    def test_bearish_original_contour_remains_denominator_but_no_short(self):
        coarse,fine,t,bars=sample(True)
        obj=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,bars)
        self.assertEqual(len(obj["original_candidate_screens"]),1)
        self.assertEqual(len(obj["hypothetical_intents"]),0)
        self.assertEqual(obj["original_candidate_screens"][0][
            "reference_screen_status"],"BEAR_CANNOT_OPEN_SPOT_SHORT")

    def test_rejected_original_v107_cannot_be_resurrected_by_gains(self):
        coarse,fine,t,bars=sample()
        coarse[2]=replace(coarse[2],center_close=coarse[0].center_close)
        bars[2]=bar(t+2*MIN,110,140,105,130)
        a=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,bars)
        self.assertEqual(len(a["hypothetical_intents"]),0)
        self.assertEqual(a["original_candidate_screens"][0][
            "reference_screen_status"],"ORIGINAL_V107_NECESSARY_SCREEN_REJECTED")

    def test_only_one_closed_bar_is_censored_before_reference(self):
        coarse,fine,t,bars=sample(ext=1)
        out=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,bars)
        self.assertEqual(out["original_candidate_screens"][0][
            "reference_screen_status"],"RIGHT_CENSORED_BEFORE_CLOSED_REFERENCE")

    def test_latency_minute_stop_touch_blocks_reference(self):
        coarse,fine,t,bars=sample()
        bars[0]=bar(t,110,115,95,110)
        result=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,bars)
        self.assertEqual(result["hypothetical_intents"],[])
        self.assertEqual(result["original_candidate_screens"][0][
            "reference_screen_status"],"BARRIER_TOUCHED_BEFORE_CLOSED_REFERENCE")

    def test_second_reference_bar_touched_wave1_blocks_reference(self):
        coarse,fine,t,bars=sample()
        bars[1]=bar(t+MIN,110,125,105,110)
        result=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,bars)
        self.assertEqual(result["hypothetical_intents"],[])
        self.assertEqual(result["original_candidate_screens"][0][
            "reference_screen_status"],"BARRIER_TOUCHED_BEFORE_CLOSED_REFERENCE")

    def test_source_reference_price_unavailable_until_second_minute_close(self):
        coarse,fine,t,bars=sample(ext=2)
        record=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,bars)
        known=record["original_candidate_screens"][0]["closed_reference_evidence"]
        self.assertEqual(known["second_close_reference_known_ms"],t+2*MIN)
        self.assertEqual(known["first_closed_latency_minute_known_ms"],t+MIN)
        self.assertEqual(len(record["hypothetical_intents"]),1)

    def test_no_source_event_from_later_bar_changes_prior_reference_screen(self):
        coarse,fine,t,bars=sample(ext=2)
        before=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,bars)
        future=bars+[bar(t+2*MIN,110,140,80,109),
                     bar(t+3*MIN,110,140,80,109)]
        after=v111.source_intents_for_symbol("BTCUSDT",coarse,fine,future)
        self.assertEqual(before["original_candidate_screens"],
                         after["original_candidate_screens"])
        self.assertEqual(before["hypothetical_intents"],
                         after["hypothetical_intents"])

    def test_postreference_wave1_barrier_releases_only_when_closed(self):
        coarse,fine,t,bars=sample()
        bars[2]=bar(t+2*MIN,110,125,105,120)
        output=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,bars)})
        self.assertEqual(output["all_v107_candidate_windows"],1)
        self.assertEqual(output["all_source_reference_proposals"],1)
        cash=output["cash_capacity_v110"]
        self.assertEqual(cash["admitted_hypothetical_intents"],1)
        self.assertEqual(cash["known_resolutions_count"],1)
        self.assertEqual(v110.Decimal(cash["reserved_usdt"]),v110.Decimal(0))
        self.assertEqual(output["synthetic_later_barrier_closure_observations"][0][
            "source_observation_known_at_ms"],t+3*MIN)

    def test_both_wave0_and_wave1_in_same_postreference_bar_assumes_wave0(self):
        coarse,fine,t,bars=sample()
        bars[2]=bar(t+2*MIN,110,130,90,110)
        result=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,bars)})
        self.assertEqual(result["synthetic_later_barrier_closure_observations"][0][
            "observation_only_no_auction_fill"],
            "BOTH_SAME_MINUTE_ASSUME_WAVE0_FIRST")

    def test_unresolved_synthetic_reference_retains_cash_not_fake_profit(self):
        coarse,fine,t,bars=sample()
        result=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,bars)})
        budget=result["cash_capacity_v110"]
        self.assertEqual(budget["known_resolutions_count"],0)
        self.assertGreater(v110.Decimal(budget["reserved_usdt"]),0)
        self.assertIsNone(result["net_pnl"])

    def test_two_symbols_shared_cash_never_more_than_500(self):
        coarse,fine,t,bars=sample()
        result=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,bars),
            "ETHUSDT":(coarse,fine,bars),
        })
        self.assertEqual(result["all_v107_candidate_windows"],2)
        self.assertEqual(result["all_source_reference_proposals"],2)
        capacity=result["cash_capacity_v110"]
        self.assertEqual(capacity["admitted_hypothetical_intents"],2)
        self.assertLessEqual(v110.Decimal(capacity["reserved_usdt"]),v110.CASH)
        self.assertEqual(capacity["trade_count"],0)
        self.assertIsNone(capacity["actual_net_pnl"])

    def test_future_high_does_not_retroactively_change_past_admission(self):
        coarse,fine,t,bars=sample(ext=2)
        first=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,bars)})
        advanced=bars+[bar(t+2*MIN,110,125,105,120)]
        second=v111.portfolio_census_from_source_streams({
            "BTCUSDT":(coarse,fine,advanced)})
        a=first["cash_capacity_v110"]
        b=second["cash_capacity_v110"]
        self.assertEqual(a["append_only_causal_event_ledger"][0],
                         b["append_only_causal_event_ledger"][0])
        self.assertEqual(a["original_admission_outcomes"],
                         b["original_admission_outcomes"])
        self.assertEqual(a["known_resolutions_count"],0)
        self.assertEqual(b["known_resolutions_count"],1)

    def test_any_invalid_source_gap_is_rejected_before_portfolio(self):
        coarse,fine,t,bars=sample()
        bars[1]=replace(bars[1],ms=t+2*MIN)
        with self.assertRaisesRegex(ValueError,"gap/duplicate"):
            v111.portfolio_census_from_source_streams({
                "BTCUSDT":(coarse,fine,bars)})

    def test_future_archive_cannot_be_read_before_nov30(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(v111,"datetime",wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,17,tzinfo=timezone.utc)
                with patch.object(v107,"evaluate_future_sealed_archive") as upstream:
                    with self.assertRaisesRegex(ValueError,"NO_ARCHIVE_READ"):
                        v111.evaluate_future_sealed_archive(Path(td))
                    upstream.assert_not_called()

    def test_locked_manifest_and_no_auto_order_routes(self):
        with tempfile.TemporaryDirectory() as td:
            destination=Path(td)/"V111_PROTOCOL.json"
            x=v111.freeze(destination)
            self.assertEqual(x,v111.freeze(destination))
            self.assertEqual(x["real_source_rows_evaluated"],0)
            self.assertEqual(json.loads(destination.read_text())["orders"],0)
            destination.write_text("{}")
            with self.assertRaisesRegex(ValueError,"altered"):
                v111.freeze(destination)
        self.assertTrue(v111.RESEARCH_ONLY)
        self.assertTrue(v111.V52_UNCHANGED)
        self.assertIsNone(v111.ORDER_ADAPTER)
        self.assertFalse(v111.LIVE_ENABLED)
        self.assertFalse(v111.PAPER_ELIGIBLE)
