from dataclasses import replace
from decimal import Decimal as D, localcontext
import unittest

import test_nexus_fx_protection_research as fixtures
from nexus_fx_protection_research import Target, ExitPolicy, NextBarStopMove, model_protection
from nexus_fx_quote_research import TickContractError


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProtectionTests()
        self.move = NextBarStopMove(1,D("101.02"),100,0)
        self.policy = ExitPolicy("ORDER_PRICE",self.move)

    def model(self, after, policy=None, **kwargs):
        return model_protection(*self.fixture.case(after,**kwargs),
                                policy=self.policy if policy is None else policy)

    def test_gap_targets_no_price_improvement(self):
        r=self.model([(30,"104","104.10")])
        self.assertEqual([x.price for x in r.exits],[D("102"),D("103")])
        self.assertEqual(r.status,"CLOSED_TARGETS")
        self.assertEqual(r.net_closed_pnl,D("4.52"))
        self.assertIsNone(r.pending_activation_ms)

    def test_limit_touch_exact_price(self):
        r=self.model([(30,"102","102.10")])
        self.assertEqual(r.exits[0].price,D("102"))
        self.assertEqual(r.exits[0].slippage_cost,D(0))
        self.assertEqual(r.pending_activation_ms,100)

    def test_old_stop_same_bar(self):
        r=self.model([(30,"102","102.10"),(40,"100","100.10"),(100,"103","103.10")])
        self.assertEqual(r.status,"CLOSED_TARGETS")
        self.assertEqual([x.reason for x in r.exits],["TARGET","TARGET"])

    def test_old_stop_hit_same_bar(self):
        r=self.model([(30,"102","102.10"),(40,"97","97.10")])
        self.assertEqual(r.exits[-1].price,D("96.98"))
        self.assertEqual(r.active_stop,D("98"))
        self.assertIsNone(r.pending_activation_ms)

    def test_move_at_next_boundary(self):
        r=self.model([(30,"102","102.10"),(99,"100","100.10"),(100,"101.02","101.12")])
        self.assertEqual(r.status,"CLOSED_STOP")
        self.assertEqual(r.exits[-1].tick.time_ms,100)
        self.assertEqual(r.exits[-1].price,D("101.00"))
        self.assertEqual(r.active_stop,D("101.02"))
        self.assertEqual(r.exits[-1].lots,D(".02"))

    def test_gap_through_moved_stop(self):
        r=self.model([(30,"102","102.10"),(110,"99","99.10")])
        self.assertEqual(r.exits[-1].price,D("98.98"))

    def test_anchor(self):
        r=self.model([(30,"102","102.10"),(49,"100","100.10"),(50,"100","100.10")],
                     policy=ExitPolicy("ORDER_PRICE",NextBarStopMove(1,D("101.02"),100,50)))
        self.assertEqual(r.exits[-1].tick.time_ms,50)

    def test_target_at_boundary_waits_full_bar(self):
        r=self.model([(30,"101","101.10"),(100,"102","102.10"),(150,"100","100.10")])
        self.assertEqual(r.status,"UNRESOLVED_COVERAGE")
        self.assertEqual(r.pending_activation_ms,200)
        self.assertEqual(r.active_stop,D("98"))

    def test_short_mirror(self):
        policy=ExitPolicy("ORDER_PRICE",NextBarStopMove(1,D("99.98"),100,0))
        r=self.model([(30,"98","98.10"),(50,"100","100.10"),(100,"100","100.10")],
            policy=policy,side="sell",stop="102",
            targets=(Target(D("98.50"),D(".01")),Target(D("97"),D(".02"))))
        self.assertEqual([x.price for x in r.exits],[D("98.50"),D("100.12")])
        self.assertEqual(r.active_stop,D("99.98"))

    def test_short_gap_targets_exact(self):
        r=self.model([(30,"96","96.10")],policy=ExitPolicy("ORDER_PRICE"),
          side="sell",stop="102",targets=(Target(D("98.50"),D(".01")),Target(D("97"),D(".02"))))
        self.assertEqual([x.price for x in r.exits],[D("98.50"),D("97")])

    def test_no_move_policy(self):
        r=self.model([(30,"102","102.10"),(100,"100","100.10")],policy=ExitPolicy("ORDER_PRICE"))
        self.assertEqual(r.remaining_lots,D(".02"))
        self.assertEqual(r.active_stop,D("98"))

    def test_invalid_move(self):
        for move in (NextBarStopMove(2,D("101.02"),100,0),
                     NextBarStopMove(1,D("97"),100,0),
                     NextBarStopMove(1,D("102"),100,0),
                     NextBarStopMove(1,D("101.021"),100,0)):
            with self.assertRaises(TickContractError):
                self.model([(30,"104","104.10")],policy=ExitPolicy("ORDER_PRICE",move))

    def test_invalid_grid_and_mode(self):
        for args in ((1,D("101"),0,0),(1,D("101"),100,100),(True,D("101"),100,0)):
            with self.assertRaises(TickContractError):
                NextBarStopMove(*args)
        with self.assertRaises(TickContractError):
            ExitPolicy("UNKNOWN")

    def test_replay(self):
        expected=self.model([(30,"102","102.10"),(100,"100","100.10")])
        with localcontext() as c:
            c.prec=2
            self.assertEqual(expected,self.model([(30,"102","102.10"),(100,"100","100.10")]))


if __name__=="__main__":
    unittest.main()
