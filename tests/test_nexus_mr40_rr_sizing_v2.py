"""Synthetic market paths exercise accounting, causal brackets and sizing limits."""
import copy
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("rr_sizing_test",ROOT/"research/nexus_mr40_rr_sizing_v2.py")
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)


class RewardRiskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=study.load_base(ROOT);cls.code=cls.base.load_code(ROOT)
        cls.policy=json.loads((ROOT/"research/mr40_rr_sizing_v2.json").read_bytes())

    def setUp(self):
        # ATR20 is exactly 2 before entry; initial stop distance is exactly 4.
        self.rows=[[self.base.ms("2023-01-01")+i*study.STEP,"100","101","99","100","1"] for i in range(248)]
        self.signals=[int(i>=239) for i in range(len(self.rows))]
        self.profile=copy.deepcopy(self.policy["profiles"][0])

    def bar(self,i,op=100,hi=101,lo=99,cl=100):
        self.rows[i][1:5]=list(map(str,(op,hi,lo,cl)))

    def run_case(self,name="b_rr2_r1",capital=10000,**kwargs):
        case=next(c for c in self.policy["cases"] if c["id"]==name)
        data=study.prepare(self.rows,self.base,self.code)
        return study.simulate(self.rows,data,self.signals,case,240,len(self.rows),self.profile,capital,**kwargs)

    def test_allocation_fractions_include_entry_commission_and_lot_floor(self):
        for name,budget in (("b_rr2_a25",2500),("b_rr2_a50",5000),("b_rr2_a100",10000)):
            entry=self.run_case(name)["fills"][0]
            paid=D(entry["notional"])+D(entry["fee"])
            self.assertLessEqual(paid,budget)
            self.assertLess(D(budget)-paid,D("0.00101"))
            self.assertEqual(D(entry["quantity"])%study.LOT,0)

    def test_fixed_risk_is_net_stop_loss_with_costs_and_never_leverages(self):
        entry=self.run_case()["fills"][0]
        q=D(entry["quantity"])
        cost=D(entry["notional"])+D(entry["fee"])
        # Independent oracle using specified stop, sell slippage and both fees.
        net_stop=q*(D(entry["initial_stop"])*D("0.9995"))*D("0.999")
        self.assertAlmostEqual(float(cost-net_stop),100,places=4)
        self.assertLessEqual(D(entry["planned_loss"]),100+study.Q)
        # A risk budget larger than available capital is capped by cash.
        entry=self.run_case("b_rr2_r2",capital=10)["fills"][0]
        self.assertGreaterEqual(D(entry["cash_after"]),0)

    def test_high_risk_request_with_tiny_atr_caps_at_cash(self):
        for row in self.rows:row[2:4]=["100.001","99.999"]
        result=self.run_case("b_rr2_r2")
        self.assertGreater(result["metrics"]["median_entry_allocation_pct"],99)
        self.assertLess(result["metrics"]["median_nominal_risk_pct"],2)

    def test_entry_bar_bracket_is_active_and_intrabar_time_is_an_interval(self):
        self.bar(240,hi=110)
        result=self.run_case()
        self.assertEqual([(f["bar_index"],f["side"]) for f in result["fills"]],[(240,"buy"),(240,"sell")])
        exit=result["fills"][-1]
        self.assertEqual(exit["reason"],"take_profit")
        self.assertEqual(exit["time_kind"],"intrabar")
        self.assertEqual(exit["interval_end_ms"]-exit["interval_start_ms"],study.STEP)
        self.assertEqual(result["positions"][0]["holding_hours_lower"],0)
        self.assertEqual(result["positions"][0]["holding_hours_upper"],4)

    def test_both_levels_hit_defaults_to_stop_and_diagnostic_changes_order(self):
        self.bar(240,hi=110,lo=90)
        conservative=self.run_case();optimistic=self.run_case(stop_first=False)
        self.assertEqual(conservative["fills"][-1]["reason"],"protective_stop")
        self.assertEqual(optimistic["fills"][-1]["reason"],"take_profit")
        self.assertEqual(conservative["metrics"]["ambiguous_bars"],1)
        self.assertLess(conservative["metrics"]["net_pnl_usdt"],0)
        self.assertGreater(optimistic["metrics"]["net_pnl_usdt"],0)

    def test_stop_gap_uses_adverse_open_and_can_exceed_nominal_risk(self):
        self.bar(241,op=90,hi=92,lo=88,cl=90)
        result=self.run_case();exit=result["fills"][-1]
        self.assertEqual(D(exit["reference"]),90)
        self.assertEqual(exit["time_kind"],"open")
        self.assertLess(result["metrics"]["net_pnl_usdt"],-200)

    def test_favorable_target_gap_receives_only_target_level(self):
        self.bar(241,op=115,hi=116,lo=114,cl=115)
        exit=self.run_case()["fills"][-1]
        self.assertEqual(D(exit["reference"]),D("108.05"))
        self.assertEqual(exit["time_kind"],"open")

    def test_breakeven_requires_closed_one_r_and_costs_are_included(self):
        self.bar(240,op=100,hi=106,lo=99,cl=105)
        self.bar(241,op=105,hi=106,lo=100,cl=101)
        result=self.run_case("b_be2_r1")
        exit=result["fills"][-1]
        self.assertEqual(exit["bar_index"],241)
        self.assertGreater(D(exit["active_stop"]),D(result["fills"][0]["price"]))
        self.assertGreaterEqual(result["metrics"]["net_pnl_usdt"],-1e-7)
        self.assertLess(result["metrics"]["net_pnl_usdt"],1e-5)

    def test_current_high_does_not_activate_breakeven(self):
        self.bar(240,hi=106,lo=99,cl=100)
        self.bar(241,hi=101,lo=98,cl=100)
        result=self.run_case("b_be2_r1")
        self.assertEqual(result["fills"][-1]["reason"],"terminal_close")

    def test_stop_update_respects_extra_latency(self):
        self.profile["lag_bars"]=2
        self.bar(241,op=100,hi=106,lo=99,cl=105)
        self.bar(242,op=105,hi=106,lo=100,cl=105)
        self.bar(243,op=105,hi=106,lo=100,cl=101)
        exit=self.run_case("b_be2_r1")["fills"][-1]
        self.assertEqual(exit["bar_index"],243)
        self.assertEqual(exit["update_signal_index"],241)

    def test_trailing_stop_uses_prior_close_atr_and_never_moves_down(self):
        self.bar(240,op=100,hi=104,lo=99,cl=103)
        self.bar(241,op=103,hi=104,lo=100,cl=102)
        self.bar(242,op=102,hi=103,lo=98,cl=100)
        exit=self.run_case("b_trail2_r1")["fills"][-1]
        # Post-entry ATR=(19*2+5)/20=2.15, so next stop=103-4.3=98.7.
        self.assertEqual(exit["bar_index"],242)
        self.assertEqual(D(exit["active_stop"]),D("98.7"))

    def test_partial_exit_has_two_sales_and_exact_cashflow(self):
        self.bar(240,hi=105,cl=104)
        self.bar(241,op=105,hi=114,lo=104,cl=113)
        result=self.run_case("b_partial3_r1")
        self.assertEqual([f["reason"] for f in result["fills"]],["episode_entry","partial_1r","take_profit"])
        buy,*sales=result["fills"]
        self.assertEqual(sum(D(f["quantity"]) for f in sales),D(buy["quantity"]))
        self.assertEqual(result["metrics"]["partial_fills"],1)
        self.assertAlmostEqual(result["positions"][0]["net_pnl_usdt"],result["metrics"]["net_pnl_usdt"],places=7)
        self.assertGreater(D(sales[-1]["active_stop"]),D(buy["price"]))

    def test_partial_stop_stays_at_initial_level_until_next_closed_bar(self):
        self.bar(240,hi=105,lo=99,cl=100)
        result=self.run_case("b_partial3_r1")
        self.assertEqual(result["fills"][1]["reason"],"partial_1r")
        self.assertEqual(result["fills"][-1]["bar_index"],241)
        self.assertEqual(result["fills"][-1]["reason"],"protective_stop")

    def test_small_partial_is_skipped_and_whole_quantity_waits_for_three_r(self):
        self.bar(240,hi=105)
        self.bar(241,op=105,hi=114,lo=104,cl=113)
        result=self.run_case("b_partial3_r1",capital=5)
        self.assertEqual(result["metrics"]["partial_skips"],1)
        self.assertEqual(result["metrics"]["partial_fills"],0)
        self.assertEqual(len(result["fills"]),2)
        self.assertEqual(D(result["fills"][-1]["reference"]),D("112.05"))

    def test_close_confirmed_ignores_high_and_executes_after_closed_trigger(self):
        self.profile=copy.deepcopy(self.policy["profiles"][3])
        self.bar(240,hi=110,lo=90,cl=100)
        self.bar(241,op=100,hi=110,lo=99,cl=110)
        self.bar(242,op=106,hi=111,lo=105,cl=110)
        exit=self.run_case()["fills"][-1]
        self.assertEqual(exit["bar_index"],242)
        self.assertEqual(exit["signal_index"],241)
        self.assertEqual(D(exit["reference"]),106)

    def test_no_reentry_within_episode_after_target_exit(self):
        self.bar(240,hi=110)
        result=self.run_case()
        self.assertEqual(sum(f["side"]=="buy" for f in result["fills"]),1)

    def test_delayed_signal_seen_while_holding_is_not_entered_after_exit(self):
        self.profile["lag_bars"]=2
        self.signals[240]=0;self.signals[241]=1
        self.bar(242,hi=110)
        result=self.run_case()
        self.assertEqual([(f["bar_index"],f["side"]) for f in result["fills"]],[(241,"buy"),(242,"sell")])

    def test_ledger_rejects_fee_and_quantity_tampering(self):
        result=self.run_case();case=next(c for c in self.policy["cases"] if c["id"]=="b_rr2_r1")
        for field,value in (("fee","0"),("quantity","999")):
            fills=copy.deepcopy(result["fills"]);fills[0][field]=value
            with self.assertRaises(ValueError):study.verify_ledger(self.rows,case,240,len(self.rows),self.profile,10000,fills,result["equity"])

    def test_natural_control_matches_frozen_execution_for_both_latencies(self):
        close=[80+i*40/238 for i in range(239)]+[110,109,111,112,113,130,130,130]
        self.rows=[[self.base.ms("2023-01-01")+i*study.STEP,str(c),str(c*1.01),str(c*.99),str(c),"1"] for i,c in enumerate(close)]
        data=study.prepare(self.rows,self.base,self.code)
        self.signals=self.base.targets(self.rows,data,"baseline",240,len(self.rows))
        for lag in (1,2):
            self.profile["lag_bars"]=lag
            old=self.base.simulate(self.rows,data,"baseline",240,len(self.rows),self.profile,500)
            new=self.run_case("baseline_a100",capital=500)
            self.assertEqual(new["equity"],old["equity"])

    def test_training_selector_excludes_allocation_controls_and_is_deterministic(self):
        records=[]
        for case in self.policy["cases"]:
            for p in ("normal","stress"):
                pnl,cagr,dd=(100,10,10) if case["id"]=="baseline_a100" else (50,5,15)
                if case["id"] in ("baseline_a25","baseline_a50"):pnl,cagr,dd=9999,100,1
                if case["id"]=="b_rr2_r1":pnl,cagr,dd=110,11,8
                records.append({"case":case["id"],"profile":p,"net_pnl_usdt":pnl,"cagr_pct":cagr,"max_close_drawdown_pct":dd})
        selected=study.select(records,self.policy["cases"])
        self.assertEqual(selected["profit"],"b_rr2_r1")
        self.assertEqual(selected["efficiency"],"b_rr2_r1")
        self.assertEqual(selected,study.select(list(reversed(records)),self.policy["cases"]))


if __name__=="__main__":unittest.main()
