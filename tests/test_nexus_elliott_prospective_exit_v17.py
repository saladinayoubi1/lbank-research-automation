"""Synthetic-only V17 forward exit tests. No historical Bybit bar ingestion."""
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from nexus_elliott_prospective_exit_v17 import (
    AUTO_DEMO,ENTRY_SIGNAL,LIVE_ENABLED,PAPER_ELIGIBLE,RESEARCH_ONLY,
    COMPLETE_RECURSIVE_ELLIOTT_COUNT, FORWARD_START_UTC,
    MAX_HOLD_BARS, evaluate_prospective_study,
)


DECISION = datetime(2026,10,16,0,15,tzinfo=timezone.utc)


def eligible(**updates):
    return {
        "event_id":"future-synthetic-BTC-0001",
        "symbol":"BTCUSDT","decision_close_utc":DECISION,
        "previous_close":109,"decision_close":112,
        "fifth_high":110,"correction_low":100,
        "source_bound_seven_pivot":True,"closed_first_breakout":True,
        "post_correction_path_valid":True,
        **updates,
    }


def bar(i=0,**changes):
    row={"open_at":DECISION+timedelta(minutes=15*i),
         "open":112, "high":113,"low":111,"close":112}
    row.update(changes)
    return row


def audit(rows=None,*,e=None,profile="conservative",asof=None):
    rows=[bar()] if rows is None else rows
    if asof is None:
        asof=rows[-1]["open_at"]+timedelta(minutes=15)
    return evaluate_prospective_study(
        eligible() if e is None else e,rows,profile=profile,observed_at_utc=asof)


class ElliottProspectiveV17Tests(unittest.TestCase):
    def test_safety_no_authority(self):
        self.assertTrue(RESEARCH_ONLY)
        for flag in (AUTO_DEMO,ENTRY_SIGNAL,LIVE_ENABLED,PAPER_ELIGIBLE,
                     COMPLETE_RECURSIVE_ELLIOTT_COUNT):
            self.assertFalse(flag)
        self.assertEqual(FORWARD_START_UTC,datetime(2026,10,16,tzinfo=timezone.utc))

    def test_stop_priority_on_touched_both_same_bar(self):
        out=audit([bar(high=140,low=99)])
        self.assertEqual(out["exit_reason"],"stop")
        self.assertTrue(out["both_levels_touched_stop_first"])
        self.assertLess(Decimal(out["net_pnl"]),0)
        self.assertTrue(out["hypothetical_simulator_only"])
        self.assertFalse(out["real_broker_fill_verified"])
        self.assertEqual(out["orders_placed"],0)

    def test_immediate_target_exit(self):
        out=audit([bar(high=140,low=111)])
        self.assertEqual(out["exit_reason"],"target")
        self.assertGreater(Decimal(out["net_pnl"]),0)
        self.assertFalse(out["both_levels_touched_stop_first"])

    def test_gap_through_stop_uses_worse_next_open(self):
        out=audit([bar(),bar(1,open=95,high=110,low=94,close=100)])
        self.assertEqual(out["exit_reason"],"stop")
        self.assertEqual(Decimal(out["exit_reference"]),Decimal(95))
        self.assertLess(Decimal(out["exit_price"]),Decimal(95))

    def test_favorable_gap_does_not_give_free_extra_profit(self):
        out=audit([bar(),bar(1,open=150,high=151,low=149,close=150)])
        self.assertEqual(out["exit_reason"],"target")
        self.assertEqual(Decimal(out["exit_reference"]),Decimal(out["target"]))

    def test_next_open_under_stop_refuses_entry(self):
        out=audit([bar(open=99,high=112,low=98,close=108)])
        self.assertEqual(out["status"],"NO_ENTRY_OPEN_AT_OR_BELOW_CORRECTION")
        self.assertFalse(out["filled"])
        self.assertIsNone(out["net_pnl"])

    def test_no_exit_with_only_one_quiet_bar_is_pending_not_fabricated(self):
        out=audit([bar()])
        self.assertEqual(out["status"],"AWAITING_MORE_CLOSED_BARS")
        self.assertIsNone(out["net_pnl"])

    def test_horizon_exit_on_64th_bar_at_close(self):
        out=audit([bar(i) for i in range(MAX_HOLD_BARS)])
        self.assertEqual(out["status"],"EXITED")
        self.assertEqual(out["exit_reason"],"time_limit")
        self.assertEqual(out["exit_bar_index_after_entry"],63)
        self.assertEqual(Decimal(out["exit_reference"]),Decimal(112))

    def test_insufficient_63_bars_remain_pending(self):
        out=audit([bar(i) for i in range(MAX_HOLD_BARS-1)])
        self.assertEqual(out["status"],"AWAITING_MORE_CLOSED_BARS")

    def test_no_historical_fold_admitted(self):
        with self.assertRaisesRegex(ValueError,"historically inspected"):
            audit(e=eligible(decision_close_utc=DECISION-timedelta(days=1)),
                  asof=DECISION+timedelta(minutes=15))

    def test_unverified_source_and_break_rejected(self):
        for key in ("source_bound_seven_pivot","closed_first_breakout",
                    "post_correction_path_valid"):
            e=eligible(**{key:False})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,"eligibility"):
                audit(e=e)

    def test_breakout_cross_mathematically_checked(self):
        with self.assertRaisesRegex(ValueError,"no valid first CLOSED breakout"):
            audit(e=eligible(previous_close=111))
        with self.assertRaisesRegex(ValueError,"no valid first CLOSED breakout"):
            audit(e=eligible(correction_low=113))

    def test_forged_future_gap_or_missing_bar_rejected(self):
        with self.assertRaisesRegex(ValueError,"contiguous"):
            audit(rows=[bar(),bar(2)])

    def test_forming_candle_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"forming/unavailable"):
            audit(rows=[bar(),bar(1)],asof=DECISION+timedelta(minutes=15))

    def test_forever_open_cannot_fake_terminal_exit(self):
        with self.assertRaisesRegex(ValueError,"between 1 and 64"):
            audit(rows=[bar(i) for i in range(MAX_HOLD_BARS+1)])

    def test_missing_source_ohlc_fails_closed(self):
        src=bar();src.pop("high")
        with self.assertRaisesRegex(ValueError,"missing"):
            audit(rows=[src])

    def test_malformed_source_ohlc_fails_closed(self):
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            audit(rows=[bar(high=110)])
        with self.assertRaisesRegex(ValueError,"finite positive"):
            audit(rows=[bar(low=float("nan"))])

    def test_no_blank_research_identity_or_wrong_symbol(self):
        with self.assertRaisesRegex(ValueError,"ID/symbol"):
            audit(e=eligible(event_id=""))
        with self.assertRaisesRegex(ValueError,"ID/symbol"):
            audit(e=eligible(symbol="LBank"))

    def test_invalid_profile_rejected(self):
        with self.assertRaisesRegex(ValueError,"unregistered"):
            audit(profile="zero_fees")

    def test_slippage_stress_decreases_net_target_return(self):
        row=[bar(high=145)]
        a=audit(row,profile="conservative")
        b=audit(row,profile="stress")
        self.assertEqual(a["exit_reason"],b["exit_reason"])
        self.assertLess(Decimal(b["net_pnl"]),Decimal(a["net_pnl"]))

    def test_different_bar_source_changes_sha(self):
        one=audit([bar(high=113)])
        two=audit([bar(high=114)])
        self.assertNotEqual(one["future_closed_bar_sha256"],two["future_closed_bar_sha256"])

    def test_position_size_and_research_reference_only(self):
        out=audit([bar(high=145)])
        entry=Decimal(out["entry"])
        q=Decimal(out["quantity"])
        fee=Decimal(out["fee_bps_per_leg"])/Decimal(10000)
        stop_dist=entry-Decimal(out["structural_stop"])
        self.assertLessEqual(q*stop_dist,Decimal("10"))
        self.assertLessEqual(q*entry*(1+fee),Decimal("1000"))
        self.assertEqual(out["reference_cell_usdt"],"10000")
        self.assertFalse(out["paper_eligible"])

    def test_boundary_naive_time_rejected(self):
        with self.assertRaisesRegex(ValueError,"aware"):
            audit(asof=DECISION.replace(tzinfo=None)+timedelta(minutes=15))

    def test_mae_mfe_extremes_not_exact_execution_claim(self):
        out=audit([bar(high=140,low=99)])
        envelope=out["observed_bar_extremes_mae_mfe_not_exact_executed_excursion"]
        self.assertTrue(envelope["intrabar_order_unknown"])
        self.assertGreater(Decimal(envelope["highest_high_vs_entry"]),0)
        self.assertLess(Decimal(envelope["lowest_low_vs_entry"]),0)


if __name__=="__main__":
    unittest.main()
