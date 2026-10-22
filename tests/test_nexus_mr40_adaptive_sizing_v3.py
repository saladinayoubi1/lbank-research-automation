import copy
from decimal import Decimal as D
import importlib.util
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("adaptive_test",ROOT/"research/nexus_mr40_adaptive_sizing_v3.py")
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)


class AdaptiveSizingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v2,cls.base,cls.code=study.load_engines(ROOT)
        cls.policy=json.loads((ROOT/"research/mr40_adaptive_sizing_v3.json").read_bytes())

    def setUp(self):
        self.rows=[[self.base.ms("2023-01-01")+i*study.STEP,"100","101","99","100","1"] for i in range(248)]
        self.profile=copy.deepcopy(self.policy["profiles"][0])
        self.signals=[int(i>=239) for i in range(len(self.rows))]

    def bar(self,i,op=100,hi=101,lo=99,cl=100):self.rows[i][1:5]=list(map(str,(op,hi,lo,cl)))

    def case(self,name):return next(c for c in self.policy["cases"] if c["id"]==name)

    def run_case(self,name="b_vol40",capital=10000,**kwargs):
        data=self.v2.prepare(self.rows,self.base,self.code)
        return study.simulate(self.rows,data,self.signals,self.case(name),240,len(self.rows),self.profile,capital,**kwargs)

    def test_combined_caps_use_minimum_not_multiplication(self):
        c=self.case("b_vol40_dd5")
        self.assertEqual(study.fraction(c,1,.06),D("0.4"))
        self.assertEqual(study.fraction(c,.5,.06),D("0.5"))
        self.assertEqual(study.fraction(c,.2,0),D("1"))

    def test_vol_target_is_monotonic_cash_capped_and_cost_aware(self):
        for i in range(240):
            c=100 if i%2 else 102
            self.bar(i,op=c,hi=c+1,lo=c-1,cl=c)
        values=[]
        for case in ("b_vol30","b_vol40","b_vol50"):
            r=self.run_case(case);e=r["fills"][0];values.append(D(e["quantity"]))
            self.assertGreater(D(e["cash_after"]),0)
            self.assertLess(D(e["allocation"]),1)
            self.assertLessEqual(D(e["notional"])+D(e["fee"]),10000*D(e["allocation"]))
        self.assertLess(values[0],values[1]);self.assertLess(values[1],values[2])

    def test_zero_volatility_caps_at_all_cash_without_division_by_zero(self):
        e=self.run_case()["fills"][0]
        self.assertEqual(D(e["allocation"]),1)
        self.assertEqual(e["observed_annual_vol_pct"],0)

    def test_entry_sizing_does_not_see_future_prices(self):
        before=self.run_case()["fills"][0]
        self.bar(241,op=100,hi=201,lo=99,cl=200)
        after=self.run_case()["fills"][0]
        self.assertEqual(before,after)

    def test_holding_is_not_rebalanced_when_volatility_changes(self):
        self.bar(241,op=100,hi=201,lo=99,cl=200)
        r=self.run_case()
        self.assertEqual([f["side"] for f in r["fills"]],["buy","sell"])
        self.assertEqual(r["fills"][0]["quantity"],r["fills"][1]["quantity"])

    def test_drawdown_throttle_persists_after_losing_exit(self):
        self.signals=[0]*len(self.rows);self.signals[239]=1
        for i in range(242,len(self.rows)):self.signals[i]=1
        self.bar(240,lo=93,cl=94)
        for i in range(241,len(self.rows)):self.bar(i,op=94,hi=95,lo=93,cl=94)
        buys=[f for f in self.run_case("b_dd5_a50")["fills"] if f["side"]=="buy"]
        self.assertEqual([f["bar_index"] for f in buys],[240,243])
        self.assertGreater(buys[1]["observed_drawdown_pct"],5)
        self.assertEqual(D(buys[1]["allocation"]),D("0.5"))

    def test_two_bar_lag_uses_decision_drawdown_not_current_cash_drawdown(self):
        self.profile["lag_bars"]=2
        self.signals=[0]*len(self.rows);self.signals[239]=1
        for i in range(241,len(self.rows)):self.signals[i]=1
        for i in range(242,len(self.rows)):self.bar(i,op=94,hi=95,lo=93,cl=94)
        buys=[f for f in self.run_case("b_dd5_a50")["fills"] if f["side"]=="buy"]
        self.assertEqual([f["bar_index"] for f in buys],[241,243])
        self.assertLess(float(buys[1]["cash_before"]),9500)
        self.assertLess(buys[1]["observed_drawdown_pct"],5)
        self.assertEqual(D(buys[1]["allocation"]),1)

    def test_lot_floor_and_minimum_preserve_cash(self):
        for name in ("baseline_a100","baseline_a50","b_vol40"):
            r=self.run_case(name,capital=500);e=r["fills"][0]
            self.assertEqual(D(e["quantity"])%study.LOT,0)
            self.assertGreaterEqual(D(e["cash_after"]),0)
        r=self.run_case("baseline_a50",capital=1)
        self.assertFalse(r["fills"]);self.assertEqual(r["metrics"]["net_pnl_usdt"],0)

    def test_independent_oracle_rejects_fee_fraction_and_observation_tampering(self):
        r=self.run_case();case=self.case("b_vol40")
        for field,value in (("fee","0"),("allocation","0.1"),("observed_drawdown_pct",50)):
            fills=copy.deepcopy(r["fills"]);fills[0][field]=value
            with self.assertRaises(ValueError):study.verify_ledger(self.rows,case,240,len(self.rows),self.profile,10000,fills,r["equity"])

    def test_control_paths_match_frozen_engine_with_both_latencies(self):
        close=[80+i*40/238 for i in range(239)]+[110,109,111,112,113,130,130,130]
        self.rows=[[self.base.ms("2023-01-01")+i*study.STEP,str(c),str(c*1.01),str(c*.99),str(c),"1"] for i,c in enumerate(close)]
        data=self.v2.prepare(self.rows,self.base,self.code)
        for case,variant in (("baseline_a100","baseline"),("baseline_a50","cash50_control"),("confirm_natural_a100","confirm3")):
            self.signals=self.base.targets(self.rows,data,self.case(case)["entry"],240,len(self.rows))
            for lag in (1,2):
                self.profile["lag_bars"]=lag
                old=self.base.simulate(self.rows,data,variant,240,len(self.rows),self.profile,500)
                new=self.run_case(case,capital=500)
                self.assertEqual(old["equity"],new["equity"])

    def test_prefix_execution_and_marks_are_invariant(self):
        self.bar(241,lo=93,cl=94)
        full=self.run_case("b_vol40_dd5",liquidate=False)
        cut=244;data=self.v2.prepare(self.rows[:cut],self.base,self.code)
        short=study.simulate(self.rows[:cut],data,self.signals[:cut],self.case("b_vol40_dd5"),240,cut,self.profile,10000,liquidate=False)
        self.assertEqual(short["fills"],[f for f in full["fills"] if f["bar_index"]<cut])
        self.assertEqual(short["equity"],full["equity"][:cut-240])

    def test_account_drawdown_starts_at_initial_capital_despite_price_history(self):
        for i in range(100):self.bar(i,op=200,hi=201,lo=199,cl=200)
        e=self.run_case("b_dd5_a50")["fills"][0]
        self.assertEqual(e["observed_drawdown_pct"],0)
        self.assertEqual(D(e["allocation"]),1)


if __name__=="__main__":unittest.main()
