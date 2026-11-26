from dataclasses import replace
from decimal import Decimal as D, localcontext
import unittest

import test_nexus_fx_protection_research as fixtures
from nexus_fx_risk_plan_research import RiskBudget, TargetRule, EqualSplit, compile_trade_plan, replay_plan_protection
from nexus_fx_quote_research import TickContractError


class RiskPlanTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProtectionTests()
        self.budget=RiskBudget(D("10000"),D(".005"),"USD")
        self.rule=TargetRule(D("2"))

    def case(self, *, side="buy", stop="98", rule=None, budget=None, split=None, after=None, profile=None):
        w,e,_,_=self.fixture.case(after or [(30,"108","108.10")],side=side)
        return w,compile_trade_plan(w,e.intent,profile or e.profile,e.delay,budget or self.budget,
                                   D(stop),rule or self.rule,split=split)

    def test_risk_includes_two_commissions_and_stop_slippage(self):
        _,p=self.case()
        self.assertEqual(p.status,"HYPOTHETICAL_PLAN")
        self.assertEqual(p.initial_r,D("3.02"))
        self.assertEqual(p.entry.lots,D(".15"))
        self.assertEqual(p.estimated_stop_risk,D("47.70"))
        self.assertEqual(p.targets[0].price,D("107.06"))

    def test_replay_protection(self):
        w,p=self.case()
        r=replay_plan_protection(w,p)
        self.assertEqual(r.status,"CLOSED_TARGETS")
        self.assertEqual(r.exits[0].price,D("107.06"))
        self.assertEqual(r.net_closed_pnl,D("88.50"))

    def test_short_mirror(self):
        _,p=self.case(side="sell",stop="103")
        self.assertEqual(p.initial_r,D("3.02"))
        self.assertEqual(p.targets[0].price,D("93.94"))
        self.assertEqual(p.entry.lots,D(".15"))

    def test_round_long_target_down(self):
        _,p=self.case(rule=TargetRule(D("1.333")))
        self.assertEqual(p.targets[0].price,D("105.04"))

    def test_round_short_target_up(self):
        _,p=self.case(side="sell",stop="103",rule=TargetRule(D("1.333")))
        self.assertEqual(p.targets[0].price,D("95.96"))

    def test_structural_cap(self):
        _,p=self.case(rule=TargetRule(D("2"),D("104")))
        self.assertEqual(p.targets[0].price,D("104"))

    def test_gap_past_structural_target(self):
        _,p=self.case(rule=TargetRule(structural_level=D("101")))
        self.assertEqual(p.status,"REJECT_TARGET_GEOMETRY")
        self.assertIsNone(p.entry)

    def test_gap_past_stop(self):
        _,p=self.case(stop="102")
        self.assertEqual(p.status,"REJECT_STOP_GEOMETRY")
        self.assertIsNone(p.entry)

    def test_equal_split(self):
        b=RiskBudget(D("12800"),D(".005"),"USD")
        _,p=self.case(budget=b,split=EqualSplit(D("1"),100,0))
        self.assertEqual(p.entry.lots,D(".20"))
        self.assertEqual([t.lots for t in p.targets],[D(".10"),D(".10")])
        self.assertEqual([t.price for t in p.targets],[D("104.04"),D("107.06")])
        self.assertEqual(p.policy.stop_move.new_stop,p.entry.candidate.price)

    def test_odd_lots_rejected(self):
        _,p=self.case(split=EqualSplit(D("1"),100,0))
        self.assertEqual(p.status,"REJECT_UNDIVIDABLE_LOTS")

    def test_target_too_close_for_split(self):
        _,p=self.case(rule=TargetRule(D("1")),split=EqualSplit(D("1"),100,0))
        self.assertEqual(p.status,"REJECT_SPLIT_GEOMETRY")

    def test_minimum_lot_budget(self):
        _,p=self.case(budget=RiskBudget(D("100"),D(".005"),"USD"))
        self.assertEqual(p.status,"REJECT_INSUFFICIENT_RISK_BUDGET")

    def test_currency_mismatch(self):
        with self.assertRaises(TickContractError):
            self.case(budget=replace(self.budget,currency="EUR"))

    def test_max_lot_cap(self):
        _,e,_,_=self.fixture.case([(30,"108","108.10")])
        _,p=self.case(profile=replace(e.profile,max_lots=D(".10")))
        self.assertEqual(p.entry.lots,D(".10"))

    def test_forged_plan(self):
        w,p=self.case()
        with self.assertRaises(TickContractError):
            replay_plan_protection(w,replace(p,estimated_stop_risk=D(0)))

    def test_context_independence(self):
        _,expected=self.case()
        with localcontext() as ctx:
            ctx.prec=2
            self.assertEqual(self.case()[1],expected)

    def test_bad_inputs(self):
        with self.assertRaises(TickContractError):
            RiskBudget(D("1"),D("1.1"),"USD")
        with self.assertRaises(TickContractError):
            TargetRule()
        with self.assertRaises(TickContractError):
            EqualSplit(D("1"),0,0)


if __name__=="__main__":
    unittest.main()
