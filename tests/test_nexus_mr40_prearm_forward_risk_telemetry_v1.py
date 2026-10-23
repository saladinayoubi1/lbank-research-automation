"""Synthetic no-broker tests for frozen day23 pre-arm risk telemetry."""
import copy,json, tempfile,unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from research.nexus_mr40_bybit_archive_bridge_v1 import epoch,STEP4
from research.nexus_mr40_prearm_forward_risk_telemetry_v1 import (
    compute_day,check_lock,run,LOCK_SCHEMA,NOT_BEFORE
)

DAY="2026-10-23"
def sample():
    start=epoch(DAY)
    rows=[[start+i*STEP4,"100","101","99","100","1"] for i in range(6)]
    marks=[{"first_entry_close_marker":False,"natural_exit_close_marker":False} for _ in rows]
    return rows,marks

class TestFixedDayPrearmLowTelemetry(unittest.TestCase):
    def test_no_new_entry_no_fabricated_PnL_or_risk(self):
        r,m=sample()
        x=compute_day(r,m)
        self.assertEqual(x["natural_exit_completed_positions_with_both_next_open_proxies"],0)
        self.assertIsNone(x["realized_net_PnL_only_for_completed_positions_usdt"])
        self.assertIsNone(x["fixed_day_max_held_bar_adverse_price_MAE_pct"])
        self.assertIsNone(x["fixed_day_OHLC_prior_high_to_current_low_minimum_drawdown_pct"])
        self.assertFalse(x["an_open_position_at_day_end"])
        self.assertEqual(x["closed_positions_reference_quote_equity_if_flat_usdt"],"500")

    def test_entry_is_next_open_only_and_low_before_armed_close(self):
        r,m=sample()
        m[0]["first_entry_close_marker"]=True
        r[0][3]="1"  # adverse low BEFORE any entry; irrelevant
        r[1]=[r[1][0],"100","104","94","103","1"]   # 5pct adverse, arm at CLOSE
        r[2]=[r[2][0],"103","104","89","101","1"]   # 10pct adverse AFTER arm
        m[2]["natural_exit_close_marker"]=True
        r[3]=[r[3][0],"104","105","1","103","1"]    # low AFTER next-open exit
        out=compute_day(r,m)
        self.assertEqual(out["natural_exit_completed_positions_with_both_next_open_proxies"],1)
        expected=D("500")*D("0.999")**2*D("1.04")-D("500")
        self.assertEqual(D(out["realized_net_PnL_only_for_completed_positions_usdt"]),expected)
        self.assertEqual(out["first_prearm_adverse_LOW_5_and_10_pct"]["5"]["age_hours_from_entry_bar_start"],0)
        self.assertIsNone(out["first_prearm_adverse_LOW_5_and_10_pct"]["10"])
        self.assertTrue(out["per_closed_fourhour_bar"][1]["arm_two_pct_at_this_bar_CLOSE_for_future_bars"])
        self.assertFalse(out["per_closed_fourhour_bar"][1]["arm_two_pct_completed_CLOSE_already_on_at_bar_OPEN"])
        self.assertEqual(out["per_closed_fourhour_bar"][3]["reference_action_at_open"],"NATURAL_EXIT_NEXT_OPEN_REFERENCE_ONLY")

    def test_high_without_completed_profitable_close_never_arms(self):
        r,m=sample();m[0]["first_entry_close_marker"]=True
        r[1]=[r[1][0],"100","120","94","100.9","1"]
        r[2]=[r[2][0],"100.9","105","89","99","1"]
        out=compute_day(r,m)
        self.assertFalse(out["per_closed_fourhour_bar"][1]["arm_two_pct_at_this_bar_CLOSE_for_future_bars"])
        self.assertEqual(out["first_prearm_adverse_LOW_5_and_10_pct"]["10"]["age_hours_from_entry_bar_start"],4)
        self.assertTrue(out["an_open_position_at_day_end"])
        self.assertIsNone(out["realized_net_PnL_only_for_completed_positions_usdt"])
        self.assertGreater(D(out["fixed_day_adversarial_same_bar_high_before_low_drawdown_upper_pct"]),
                           D(out["fixed_day_OHLC_prior_high_to_current_low_minimum_drawdown_pct"]))

    def test_latest_close_entry_signal_has_no_same_bar_filled_position(self):
        r,m=sample();m[-1]["first_entry_close_marker"]=True
        r[-1][3]="1"
        out=compute_day(r,m)
        self.assertEqual(out["entry_or_exit_next_open_outside_day_unresolved"],"entry")
        self.assertIsNone(out["fixed_day_max_held_bar_adverse_price_MAE_pct"])
        self.assertEqual(out["per_closed_fourhour_bar"][-1]["unrealized_adverse_low_pct"],None)
        self.assertIsNone(out["realized_net_PnL_only_for_completed_positions_usdt"])

    def test_last_bar_exit_marker_unclosed_never_assumed_filled(self):
        r,m=sample();m[0]["first_entry_close_marker"]=True
        m[-1]["natural_exit_close_marker"]=True
        out=compute_day(r,m)
        self.assertTrue(out["an_open_position_at_day_end"])
        self.assertEqual(out["entry_or_exit_next_open_outside_day_unresolved"],"exit")
        self.assertIsNone(out["realized_net_PnL_only_for_completed_positions_usdt"])

    def test_duplicate_entry_on_existing_long_rejected(self):
        r,m=sample();m[0]["first_entry_close_marker"]=True;m[3]["first_entry_close_marker"]=True
        with self.assertRaisesRegex(ValueError,"duplicate_entry"):
            compute_day(r,m)

    def test_no_exit_marker_when_flat(self):
        r,m=sample();m[2]["natural_exit_close_marker"]=True
        with self.assertRaisesRegex(ValueError,"exit_close_without_position"):
            compute_day(r,m)

    def test_intrabar_invalid_price_cannot_be_used(self):
        r,m=sample();r[4][3]="102"
        with self.assertRaisesRegex(ValueError,"invalid_ohlcv"):
            compute_day(r,m)

    def test_pre_day_end_gate_prevents_any_file_access(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/"result.json"
            with self.assertRaisesRegex(ValueError,"full_future_utc_day_not_finished"):
                run(Path(t)/"missing.json",Path(t)/"shadow.json",
                    Path(t)/"oct22.json",Path(t)/"archive.gz",target,now_ms=NOT_BEFORE-1)
            self.assertFalse(target.exists())

    def test_untrusted_preexisting_result_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as t:
            target=Path(t)/"result.json";target.write_text("KEEP")
            with self.assertRaisesRegex(ValueError,"never_overwrite"):
                run(Path(t)/"missing",Path(t)/"missing",
                    Path(t)/"missing",Path(t)/"missing",target,now_ms=NOT_BEFORE+1)
            self.assertEqual(target.read_text(),"KEEP")

    def test_prelocked_budget_and_fee_cannot_be_changed_by_outcomes(self):
        p={"schema":LOCK_SCHEMA,"sources":{
            "locked_future_day":"2026-10-23","earliest_eligible_utc":"2026-10-24T00:00:00Z",
            "original_8514_market_sha256":"a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a",
            "preverified_oct22_archive_sha256":"9591b0ccf534810939771e59ec95d6dbab4f978a72c57f86b2b332ef4cb84587",
            "preverified_oct22_independent_tick_vs_WS_logical_digest":"59c037de00de8af3b403ea1ca069fe2362d658a71bc428ecae6895b0fe7bc380",
            "previous_oct20_oct21_bridge_logical_digest":"f118d0affe21995f4bfa01c1b5261eb7e963d1c1d46bfb094debf28a35c3114e",
            "oct22_historical_close_state_logical_digest":"a3f46cf792cb47d1a3ebd01a7d5debe6abda0f0f7122a9fa9c437dff63daf351",
            "oct22_last_closed_target_long":False,
            "oct22_first_entry_and_natural_exit_markers":[0,0],
            "oct23_full_4h_candles":6,"spot_not_perpetual":True},
            "fixed_measurement":{"initial_quote_reference_USDT":"500",
            "public_spot_VIP0_reference_fee_per_side":"0.001",
            "prior_profit_arm_at_completed_4h_close_pct":"2",
            "pre_arm_price_adverse_thresholds_descriptive_not_stops_pct":[5,10]},
            "safety":{"orders":0,"private_api":False,"Live":False,
            "Paper_500USDT_unchanged":True,"promote":False,"merge":False,
            "automations":False}}
        check_lock(p)
        altered=copy.deepcopy(p);altered["fixed_measurement"]["prior_profit_arm_at_completed_4h_close_pct"]="3"
        with self.assertRaisesRegex(ValueError,"protocol_drift"):
            check_lock(altered)

if __name__=="__main__":
    unittest.main()
