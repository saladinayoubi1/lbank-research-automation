import copy
from decimal import Decimal
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("mr40_improvement_test",ROOT/"research/nexus_mr40_isolated_improvement_v1.py")
study=importlib.util.module_from_spec(spec);spec.loader.exec_module(study)


class IsolatedImprovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code=study.load_code(ROOT)

    def setUp(self):
        close=[80+i*40/238 for i in range(239)]+[110,109,111,112,113,130,130,130]
        self.rows=[[study.ms("2023-01-01")+i*study.STEP,str(c),str(c*1.01),str(c*.99),str(c),"1"] for i,c in enumerate(close)]
        self.data=study.features(self.rows,self.code)
        self.profile={"id":"normal","fee_bps":10,"slippage_bps":5,"lag_bars":1}

    def run_variant(self,variant,**kwargs):
        return study.simulate(self.rows,self.data,variant,240,len(self.rows),self.profile,500,**kwargs)

    def test_frozen_episode_admission_is_identical(self):
        expected,_=self.code["gate"].admit_episodes(self.rows,self.data["raw"],239,len(self.rows))
        actual=study.targets(self.rows,self.data,"baseline",240,len(self.rows))
        self.assertEqual(actual,expected)
        result=self.run_variant("baseline")
        self.assertEqual(result["fills"][0]["bar_index"],240)
        self.assertEqual(result["fills"][0]["signal_index"],239)

    def test_confirmation_can_enter_on_third_decision_only_once(self):
        result=self.run_variant("confirm3")
        buys=[f for f in result["fills"] if f["side"]=="buy"]
        self.assertEqual([f["bar_index"] for f in buys],[242])

    def test_confirmation_rejects_late_rebound_for_whole_episode(self):
        for i,c in ((240,109),(241,108),(242,111)):
            self.rows[i][1:5]=[str(c),str(c*1.01),str(c*.99),str(c)]
        self.data=study.features(self.rows,self.code)
        self.assertFalse(self.run_variant("confirm3")["fills"])

    def test_close_stop_uses_next_open_accepts_gap_loss_and_blocks_reentry(self):
        for i,op,c in ((240,110,110),(241,105,103),(242,90,104)):
            self.rows[i][1:5]=[str(op),str(max(op,c)*1.01),str(min(op,c)*.99),str(c)]
        self.data=study.features(self.rows,self.code)
        result=self.run_variant("stop5")
        fills=result["fills"]
        self.assertEqual([(f["bar_index"],f["side"]) for f in fills],[(240,"buy"),(242,"sell")])
        self.assertEqual(fills[-1]["reason"],"close_stop5")
        self.assertEqual(Decimal(fills[-1]["reference"]),90)
        self.assertLess(result["positions"][0]["account_return_pct"],-5)

    def test_early_exit_does_not_reenter_same_original_episode(self):
        self.data["z"][241]=-.4
        result=self.run_variant("exit_m05")
        self.assertEqual([(f["bar_index"],f["side"]) for f in result["fills"]],[(240,"buy"),(242,"sell")])

    def test_delay_is_applied_to_fills_not_to_signal_features(self):
        self.profile["lag_bars"]=2
        result=self.run_variant("baseline")
        self.assertEqual(result["fills"][0]["bar_index"],241)
        self.assertEqual(result["fills"][0]["signal_index"],239)

    def test_lots_budget_and_partial_allocation_preserve_cash(self):
        for variant in ("baseline","cash50_control","vol20"):
            result=self.run_variant(variant)
            entry=result["fills"][0]
            self.assertEqual(Decimal(entry["quantity"])%study.LOT,0)
            self.assertGreaterEqual(Decimal(entry["cash_after"]),0)
            self.assertEqual(result["metrics"]["closed_positions"],1)
            if variant=="cash50_control":self.assertGreaterEqual(Decimal(entry["cash_after"]),250)

    def test_independent_cashflow_replay_rejects_changed_fee(self):
        result=self.run_variant("baseline")
        altered=copy.deepcopy(result["fills"]);altered[0]["fee"]="0"
        with self.assertRaisesRegex(ValueError,"cashflow_changed"):
            study.verify_ledger(self.rows,240,len(self.rows),self.profile,500,altered,result["equity"])

    def test_cash50_control_cannot_win_training_selection(self):
        records=[]
        for variant in study.VARIANTS:
            for profile in ("normal","stress"):
                gain,risk=(5,10) if variant=="baseline" else (1,20)
                if variant=="confirm3":gain,risk=6,5
                if variant=="cash50_control":gain,risk=1000,1
                records.append({"variant":variant,"profile":profile,"cagr_pct":gain,"max_close_drawdown_pct":risk})
        self.assertEqual(study.choose(records)["selected"],"confirm3")


if __name__=="__main__":unittest.main()
