from dataclasses import replace
from decimal import Decimal as D, localcontext
import unittest

from nexus_fx_quote_research import Instrument, Tick, QuoteWindow, EntryIntent, quote_digest, TickContractError
from nexus_fx_cost_research import CostProfile
from nexus_fx_entry_lifecycle_research import DelayPolicy, model_entry_lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.instrument = Instrument("XAUUSD", D(".01"), D("100"), "USD")
        ts = tuple(Tick(t, n, D(b), D(a)) for n, (t,b,a) in enumerate([
            (0,"99","100"), (10,"100","101"), (10,"101","102"),
            (20,"103","104"), (30,"99","100"), (40,"102","103"), (50,"98","99")]))
        self.w = QuoteWindow(self.instrument, "synthetic", "v1", 0, 50, 20, quote_digest(ts), ts)
        self.p = CostProfile(self.instrument, "synthetic", "v1", "scenario",
                             D(".01"), D(".01"), D("10"), D("7"), 2)

    def run_case(self, side="buy", kind="market", level=None, expiry=60, cancel=None, delay=0, profile=None, lots=D(".03")):
        i = EntryIntent(side, kind, 0, expiry, level, cancel)
        return model_entry_lifecycle(self.w, i, profile or self.p, lots, DelayPolicy(delay))

    def test_strict_zero_delay(self):
        r = self.run_case()
        self.assertEqual((r.first_contact.tick.sequence, r.candidate.tick.sequence), (1,3))
        self.assertEqual(r.candidate.price, D("104.02"))

    def test_latency_boundary(self):
        r = self.run_case(delay=10)
        self.assertEqual(r.candidate.tick.time_ms, 30)

    def test_cost_at_candidate_not_trigger(self):
        r = self.run_case(delay=10)
        self.assertEqual((r.candidate.price,r.candidate.units,r.candidate.notional,
                          r.candidate.commission,r.candidate.slippage_cost),
                         (D("100.02"),D("3"),D("300.06"),D(".21"),D(".06")))

    def test_sell_uses_bid(self):
        self.assertEqual(self.run_case(side="sell").candidate.price, D("102.98"))

    def test_stop_latches(self):
        r = self.run_case(kind="stop",level=D("101"),delay=10)
        self.assertEqual(r.candidate.price, D("100.02"))

    def test_buy_limit_rechecks_after_latency(self):
        r = self.run_case(kind="limit",level=D("101"))
        self.assertEqual(r.candidate.tick.time_ms,30)

    def test_sell_limit_rechecks_adverse_slippage(self):
        r = self.run_case(side="sell",kind="limit",level=D("102"))
        self.assertEqual(r.status,"UNRESOLVED_COVERAGE")
        self.assertIsNone(r.candidate)

    def test_cancel_before_contact(self):
        self.assertEqual(self.run_case(cancel=10).status,"CANCELLED")

    def test_cancel_at_candidate(self):
        r=self.run_case(cancel=20)
        self.assertEqual(r.status,"CANCELLED")
        self.assertIsNone(r.candidate)

    def test_expiry_at_candidate(self):
        self.assertEqual(self.run_case(expiry=20).status,"EXPIRED")

    def test_cancel_after_candidate(self):
        self.assertEqual(self.run_case(cancel=21).status,"HYPOTHETICAL_ENTRY")

    def test_cancel_expiry_tie(self):
        self.assertEqual(self.run_case(cancel=20,expiry=20).status,"CANCELLED")

    def test_incomplete_coverage(self):
        r=self.run_case(delay=100)
        self.assertEqual(r.status,"UNRESOLVED_COVERAGE")
        self.assertIsNone(r.candidate)

    def test_no_trigger(self):
        self.assertEqual(self.run_case(kind="limit",level=D("1")).status,"UNRESOLVED_COVERAGE")

    def test_invalid_latency(self):
        for d in (-1,True,None,1.5,86400001):
            with self.assertRaises(TickContractError):
                DelayPolicy(d)

    def test_invalid_profile_and_quantity_even_without_trigger(self):
        with self.assertRaises(TickContractError):
            self.run_case(kind="limit",level=D("1"),profile=replace(self.p,source_revision="v2"))
        with self.assertRaises(TickContractError):
            self.run_case(kind="limit",level=D("1"),lots=D(".015"))

    def test_replay_context_independent(self):
        expected=self.run_case()
        with localcontext() as c:
            c.prec=2
            self.assertEqual(self.run_case(),expected)


if __name__ == "__main__":
    unittest.main()
