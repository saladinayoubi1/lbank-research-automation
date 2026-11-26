from dataclasses import replace
from decimal import Decimal as D, localcontext
import unittest

from nexus_fx_quote_research import (
    Instrument, Tick, QuoteWindow, EntryIntent, observe_entry, quote_digest, TickContractError,
)
from nexus_fx_cost_research import CostProfile, model_entry_cost


class FXCostTests(unittest.TestCase):
    def setUp(self):
        self.instrument = Instrument("XAUUSD", D(".01"), D("100"), "USD")
        ts = (Tick(0, 0, D("99"), D("100")), Tick(10, 1, D("100"), D("101")))
        self.w = QuoteWindow(self.instrument, "synthetic", "v1", 0, 10, 20,
                             quote_digest(ts), ts)
        self.p = CostProfile(self.instrument, "synthetic", "v1", "test-only",
                             D(".01"), D(".01"), D("10"), D("7"), 2)

    def calc(self, side="buy", kind="market", level=None, lots=D(".03"), profile=None):
        i = EntryIntent(side, kind, 0, 20, level)
        return model_entry_cost(self.w, i, observe_entry(self.w, i), profile or self.p, lots)

    def test_buy_cost(self):
        x = self.calc()
        self.assertEqual((x.underlying_units, x.hypothetical_price, x.quote_notional,
                          x.commission, x.slippage_cost),
                         (D("3"), D("101.02"), D("303.06"), D(".21"), D(".06")))
        self.assertTrue(x.research_only)
        self.assertEqual(x.quote_currency, "USD")

    def test_sell_cost(self):
        x = self.calc(side="sell")
        self.assertEqual(x.hypothetical_price, D("99.98"))
        self.assertEqual(x.slippage_cost, D(".06"))

    def test_explicit_zero(self):
        x = self.calc(profile=replace(self.p, commission_per_lot=D("0"), slippage_ticks=0))
        self.assertEqual((x.commission, x.slippage_cost), (D("0"), D("0")))

    def test_missing_cost(self):
        with self.assertRaises(TickContractError):
            replace(self.p, commission_per_lot=None)
        with self.assertRaises(TickContractError):
            replace(self.p, slippage_ticks=None)

    def test_invalid_cost(self):
        for value in (D("-1"), D("NaN"), 0.01):
            with self.assertRaises(TickContractError):
                replace(self.p, commission_per_lot=value)
        with self.assertRaises(TickContractError):
            replace(self.p, slippage_ticks=True)

    def test_quantity_grid(self):
        for lots in (D(".015"), D("0"), D("10.01"), D("NaN")):
            with self.assertRaises(TickContractError):
                self.calc(lots=lots)

    def test_metadata_grid(self):
        with self.assertRaises(TickContractError):
            replace(self.p, min_lots=D(".015"))
        with self.assertRaises(TickContractError):
            replace(self.p, min_lots=D("11"))

    def test_source_mismatch(self):
        with self.assertRaises(TickContractError):
            self.calc(profile=replace(self.p, source_revision="v2"))

    def test_instrument_mismatch(self):
        with self.assertRaises(TickContractError):
            self.calc(profile=replace(self.p, instrument=replace(self.instrument, contract_size=D("1"))))

    def test_buy_limit(self):
        with self.assertRaises(TickContractError):
            self.calc(kind="limit", level=D("101"))
        self.assertEqual(self.calc(kind="limit", level=D("101.02")).hypothetical_price, D("101.02"))

    def test_sell_limit(self):
        with self.assertRaises(TickContractError):
            self.calc(side="sell", kind="limit", level=D("100"))

    def test_unresolved_rejected(self):
        with self.assertRaises(TickContractError):
            self.calc(kind="limit", level=D("1"))

    def test_forged_contact_rejected(self):
        i = EntryIntent("buy", "market", 0, 20)
        c = replace(observe_entry(self.w, i), executable_quote=D("100"))
        with self.assertRaises(TickContractError):
            model_entry_cost(self.w, i, c, self.p, D(".03"))

    def test_decimal_context(self):
        expected = self.calc()
        with localcontext() as ctx:
            ctx.prec = 2
            self.assertEqual(self.calc(), expected)


if __name__ == "__main__":
    unittest.main()
