"""No-exchange prospective ATR14x2 pre-arm MR40 risk experiments.

These synthetic tests never replay seen strategies or claim any stop fill.
"""
from __future__ import annotations
import copy,json,tempfile,unittest
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import STEP
from research.nexus_mr40_prearm_atr14x2_prospective_v1 import (
    atr14_from_confirmed_signal_history,research_entry_geometry,
    hypothetical_risk_budget_geometry,hypothetical_stop_touch,verify_protocol,smoke,
)

def bars(n=16,high="102",low="98",close="100"):
    t=1792627200000
    return [[t+i*STEP,"100",high,low,close,"1"] for i in range(n)]

def lock():
    return {
      "schema":"nexus.mr40.prospective_prearm_atr14x2_research_protocol.v1",
      "market":{"venue":"Bybit","symbol":"BTCUSDT","category":"spot",
                "interval_minutes":240,"first_unseen_utc_day":"2026-10-23",
                "end_exclusive_utc":"2026-12-23",
                "frozen_8514_rows_sha256":"a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a",
                "verified_oct22_official_spot_gzip_sha256":"9591b0ccf534810939771e59ec95d6dbab4f978a72c57f86b2b332ef4cb84587",
                "verified_oct22_WS_parity_result_sha256":"ea5f020264cb3e307bc142f22a9736c8c5afdd5df16fa9615927f887384c099c"},
      "candidate":{"id":"PREARM_ATR14_X2_CLOSED_SIGNAL","atr_window":14,
                   "atr_multiplier":"2",
                   "atr_aggregation":"arithmetic mean of last 14 fully CLOSED 4h true ranges including completed signal bar and never entry bar",
                   "active_immediately_after_hypothetical_entry":True,
                   "ratchet_after_profit":False},
      "comparator":{"id":"UNCHANGED_MR40_BASELINE_NATURAL_EXIT"},
      "reference":{"capital_USDT":"500","diagnostic_risk_budgets_pct_of_cash":["1","2"]},
      "cost_scenarios":[
          {"id":"VIP0_FEE_ONLY","fee_each_side":"0.001","slippage_each_side":"0"},
          {"id":"VIP0_PLUS_0_1PCT_EACH_SIDE_SLIP_STRESS","fee_each_side":"0.001","slippage_each_side":"0.001"}],
      "prospective_evaluation":{"new_signal_entries_only_from":"2026-10-23T00:00:00Z",
                 "num_completed_nonoverlapping_trades_minimum_for_directional_screen":12},
      "safety":{"private_api":False,"paper_modified":False,"live":False,
                "merge":False,"promote":False,"no_orders":True,"no_scheduler":True}
    }

class TestMR40NewPreArmATR(unittest.TestCase):
    def test_synthetic_closed_bars_stop_level_and_ideal_risk_geometry(self):
        b=bars()
        a=atr14_from_confirmed_signal_history(b)
        self.assertEqual(a,D(4))
        p=research_entry_geometry(b,b[-1][0]+STEP,"100")
        self.assertEqual(D(p["initial_prearm_stop_reference_price"]),D(92))
        self.assertEqual(D(p["stop_distance_pct_of_assumed_entry"]),D(8))
        diagnostic=hypothetical_risk_budget_geometry(p,1,"0.001","0")
        self.assertTrue(D(diagnostic["ideal_stop_risk_notional_usdt"])<=D(5))
        self.assertTrue(D(diagnostic["max_research_qty_btc_if_ideal_stop_fill"])>0)
        self.assertTrue(diagnostic["not_a_real_loss_limit_or_approved_order_size"])

    def test_only_closed_bar_history_changes_ATR_not_future_entry_low(self):
        b=bars(16)
        original=research_entry_geometry(b,b[-1][0]+STEP,"100")
        # A future entry candle with extreme intrabar LOW is NEVER in b:
        future=[b[-1][0]+STEP,"100","110","1","105","200"]
        b2=copy.deepcopy(b)
        assert future[0]==b[-1][0]+STEP
        self.assertEqual(research_entry_geometry(b2,future[0],future[1]),original)
        self.assertEqual(hypothetical_stop_touch(original,future)["possible_stop_event"],
                         "LOW_TOUCHED_INTRABAR_UNCERTAIN")

    def test_entry_open_bar_cannot_be_included_in_atr_window(self):
        b=bars()
        with self.assertRaisesRegex(ValueError,"entry_clock_disagrees"):
            research_entry_geometry(b,b[-1][0],"100")
        with self.assertRaisesRegex(ValueError,"entry_clock_disagrees"):
            research_entry_geometry(b,b[-1][0]+2*STEP,"100")

    def test_fifteen_contiguous_closed_candles_required(self):
        with self.assertRaisesRegex(ValueError,"at_least_15"):
            atr14_from_confirmed_signal_history(bars(14))
        b=bars(16);b[-3][0]+=60*1000
        with self.assertRaisesRegex(ValueError,"missing_closed_source"):
            atr14_from_confirmed_signal_history(b)

    def test_ohlc_candle_corruption_cannot_make_stop(self):
        b=bars();b[-1][2]="99"
        with self.assertRaisesRegex(ValueError,"bad_candle_envelope"):
            atr14_from_confirmed_signal_history(b)

    def test_zero_ATR_no_technical_stop_or_trade_authorized(self):
        with self.assertRaisesRegex(ValueError,"zero_or_invalid_ATR"):
            atr14_from_confirmed_signal_history(bars(high="100",low="100"))

    def test_stop_gap_through_uses_open_not_unreachable_stop(self):
        b=bars()
        position=research_entry_geometry(b,b[-1][0]+STEP,"100")
        held=[b[-1][0]+STEP,"90","91","80","85","1"]
        m=hypothetical_stop_touch(position,held)
        self.assertEqual(m["possible_stop_event"],"GAP_THROUGH_AT_OPEN")
        self.assertEqual(D(m["price_reference_for_hypothetical_exit"]),D(90))
        self.assertTrue(m["no_real_fill"])

    def test_intrabar_low_not_automatic_stop_fill(self):
        b=bars()
        position=research_entry_geometry(b,b[-1][0]+STEP,"100")
        m=hypothetical_stop_touch(position,[b[-1][0]+STEP,"100","110","91","105","1"])
        self.assertEqual(m["possible_stop_event"],"LOW_TOUCHED_INTRABAR_UNCERTAIN")
        self.assertTrue(m["no_real_fill"])
        self.assertEqual(D(m["price_reference_for_hypothetical_exit"]),D(92))

    def test_no_touch_uneventful_candle(self):
        b=bars()
        position=research_entry_geometry(b,b[-1][0]+STEP,"100")
        m=hypothetical_stop_touch(position,[b[-1][0]+STEP,"100","105","99","101","1"])
        self.assertEqual(m["possible_stop_event"],"NO_STOP_LOW_CROSS")
        self.assertIsNone(m["price_reference_for_hypothetical_exit"])

    def test_diagnostic_budget_not_user_approved_and_no_leverage(self):
        b=bars()
        g=research_entry_geometry(b,b[-1][0]+STEP,"100")
        q1=hypothetical_risk_budget_geometry(g,1,"0.001","0")
        q2=hypothetical_risk_budget_geometry(g,2,"0.001","0")
        self.assertLess(D(q1["max_research_qty_btc_if_ideal_stop_fill"]),
                        D(q2["max_research_qty_btc_if_ideal_stop_fill"]))
        self.assertLessEqual(D(q2["max_research_qty_btc_if_ideal_stop_fill"])*D(100)*(1+D("0.001")),D(500))
        for args in ((3,"0.001","0"),(1,"0.002","0"),(1,"0.001","0.002")):
            with self.assertRaisesRegex(ValueError,"not_in_prelocked"):
                hypothetical_risk_budget_geometry(g,*args)

    def test_lock_rejects_param_tuning_after_results(self):
        data=lock()
        verify_protocol(data)
        for section,key,value in [
            ("candidate","atr_multiplier","1.5"),
            ("candidate","atr_window",7),
            ("market","first_unseen_utc_day","2026-10-22"),
            ("prospective_evaluation","num_completed_nonoverlapping_trades_minimum_for_directional_screen",2),
            ("safety","live",True)
        ]:
            bad=copy.deepcopy(data)
            bad[section][key]=value
            with self.assertRaisesRegex(ValueError,"protocol_drift"):
                verify_protocol(bad)

    def test_contract_proof_is_immutable_and_has_no_order_hooks(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);p=base/"lock.json";out=base/"proof.json"
            p.write_text(json.dumps(lock())+"\n")
            smoke(p,out)
            proof=json.loads(out.read_text())
            self.assertEqual(proof["new_prospective_trades_analysed"],0)
            self.assertFalse(proof["prearm_candidate_selected_for_Paper"])
            self.assertFalse(proof["economic_backtest_completed"])
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                smoke(p,out)

if __name__=="__main__":
    unittest.main()
