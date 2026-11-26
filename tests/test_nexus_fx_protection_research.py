from dataclasses import replace
from decimal import Decimal as D, localcontext
import unittest

from nexus_fx_quote_research import Instrument, Tick, QuoteWindow, EntryIntent, quote_digest, TickContractError
from nexus_fx_cost_research import CostProfile
from nexus_fx_entry_lifecycle_research import DelayPolicy, model_entry_lifecycle
from nexus_fx_protection_research import Target, model_protection


class ProtectionTests(unittest.TestCase):
    def case(self, after, side="buy", stop="98", targets=None, slip=2):
        # Contact at 10; delayed entry at 20. After tuples include explicit timestamp.
        quotes = [(0,"99","100"),(10,"100","101"),(20,"100","101")] + after
        ts = tuple(Tick(t,n,D(b),D(a)) for n,(t,b,a) in enumerate(quotes))
        ins = Instrument("XAUUSD",D(".01"),D("100"),"USD")
        w = QuoteWindow(ins,"synthetic","v1",0,ts[-1].time_ms,100,quote_digest(ts),ts)
        p = CostProfile(ins,"synthetic","v1","explicit-test",D(".01"),D(".01"),D("10"),D("7"),slip)
        e = model_entry_lifecycle(w,EntryIntent(side,"market",0,1000),p,D(".03"),DelayPolicy(0))
        plan = targets if targets is not None else (Target(D("102"),D(".01")),Target(D("103"),D(".02")))
        return w,e,D(stop),plan

    def model(self,*args,**kwargs):
        return model_protection(*self.case(*args,**kwargs))

    def test_partial_then_stop(self):
        r = self.model([(30,"102.10","102.20"),(40,"97.50","97.60")])
        self.assertEqual(r.status,"CLOSED_STOP")
        self.assertEqual([x.lots for x in r.exits],[D(".01"),D(".02")])
        self.assertEqual([x.price for x in r.exits],[D("102.08"),D("97.48")])
        self.assertEqual(r.gross_closed_pnl,D("-6.02"))
        self.assertEqual(r.net_closed_pnl,D("-6.44"))
        self.assertEqual(r.remaining_lots,D("0"))

    def test_multiple_targets_one_quote(self):
        r = self.model([(30,"104","104.10")])
        self.assertEqual(r.status,"CLOSED_TARGETS")
        self.assertEqual(len(r.exits),2)
        self.assertEqual(r.net_closed_pnl,D("8.46"))

    def test_targets_across_quotes(self):
        r = self.model([(30,"102.50","102.60"),(40,"103.50","103.60")])
        self.assertEqual([x.tick.time_ms for x in r.exits],[30,40])

    def test_unresolved_partial(self):
        r=self.model([(30,"102.10","102.20"),(40,"101","101.10")])
        self.assertEqual(r.status,"UNRESOLVED_COVERAGE")
        self.assertEqual(r.remaining_lots,D(".02"))
        self.assertEqual(r.net_closed_pnl,D(".92"))

    def test_no_contact(self):
        r=self.model([(30,"101","101.10")])
        self.assertEqual(r.remaining_lots,D(".03"))
        self.assertEqual(r.exits,())

    def test_target_price_constraint(self):
        r=self.model([(30,"102","102.10"),(40,"102.02","102.12")])
        self.assertEqual(len(r.exits),1)
        self.assertEqual(r.exits[0].tick.time_ms,40)
        self.assertEqual(r.exits[0].price,D("102"))

    def test_short_side_ask(self):
        r=self.model([(30,"98.00","98.10"),(40,"101.50","101.60")],
            side="sell",stop="101.50",targets=(Target(D("98.50"),D(".01")),Target(D("97"),D(".02"))))
        self.assertEqual(r.status,"CLOSED_STOP")
        self.assertEqual([x.price for x in r.exits],[D("98.12"),D("101.62")])
        self.assertEqual(r.net_closed_pnl,D("-1.84"))

    def test_immediate_spread_stop_ambiguity(self):
        r=self.model([(30,"104","104.10")],stop="100")
        self.assertEqual(r.status,"UNRESOLVED_ENTRY_PROTECTION")
        self.assertEqual(r.exits,())

    def test_same_time_later_sequence_ambiguity(self):
        r=self.model([(20,"104","104.10"),(30,"104","104.10")])
        self.assertEqual(r.status,"UNRESOLVED_ENTRY_PROTECTION")

    def test_allocation_conservation(self):
        for plan in ((Target(D("102"),D(".02")),),(Target(D("102"),D(".04")),)):
            with self.assertRaises(TickContractError):
                self.model([(30,"104","104.10")],targets=plan)

    def test_off_grid_lot(self):
        with self.assertRaises(TickContractError):
            self.model([(30,"104","104.10")],targets=(Target(D("102"),D(".015")),Target(D("103"),D(".015"))))

    def test_bad_target_order(self):
        with self.assertRaises(TickContractError):
            self.model([(30,"104","104.10")],targets=(Target(D("103"),D(".01")),Target(D("102"),D(".02"))))

    def test_stop_geometry(self):
        with self.assertRaises(TickContractError):
            self.model([(30,"104","104.10")],stop="102")

    def test_forged_entry(self):
        w,e,s,p=self.case([(30,"104","104.10")])
        with self.assertRaises(TickContractError):
            model_protection(w,replace(e,candidate=replace(e.candidate,price=D("100"))),s,p)

    def test_replay_context_independent(self):
        args=self.case([(30,"104","104.10")])
        expected=model_protection(*args)
        with localcontext() as ctx:
            ctx.prec=2
            self.assertEqual(model_protection(*args),expected)

    def test_no_double_slippage_deduction(self):
        r=self.model([(30,"104","104.10")])
        for e in r.exits:
            self.assertEqual(e.net_pnl,e.gross_pnl-e.commission-e.allocated_entry_commission)


if __name__ == "__main__":
    unittest.main()
