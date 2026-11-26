import unittest
from dataclasses import replace
from decimal import Decimal as D, localcontext

from nexus_fx_quote_research import (
    EntryIntent, Instrument, QuoteWindow, Tick, TickContractError,
    observe_entry, observe_protection, quote_digest,
)


def tick(t, seq, bid, ask):
    return Tick(t, seq, D(bid), D(ask))


def window(*quotes, gap=20):
    ts = tuple(quotes)
    return QuoteWindow(Instrument("XAUUSD", D(".01"), D("100"), "USD"),
                       "synthetic", "test-v1", ts[0].time_ms, ts[-1].time_ms,
                       gap, quote_digest(ts), ts)


class QuoteTests(unittest.TestCase):
    def setUp(self):
        self.w = window(tick(0, 0, "99", "100"), tick(10, 1, "100", "101"),
                        tick(20, 2, "98", "99"), tick(30, 3, "102", "103"))

    def contact(self, side, kind, level=None, active=0, expiry=40, cancel=None):
        return observe_entry(self.w, EntryIntent(side, kind, active, expiry, level, cancel))

    def test_market_next_quote(self):
        self.assertEqual(self.contact("buy", "market").tick.sequence, 1)

    def test_buy_limit_ask(self):
        self.assertEqual(self.contact("buy", "limit", D("100")).tick.sequence, 2)

    def test_sell_limit_bid(self):
        self.assertEqual(self.contact("sell", "limit", D("101")).tick.sequence, 3)

    def test_buy_stop_ask(self):
        self.assertEqual(self.contact("buy", "stop", D("101")).tick.sequence, 1)

    def test_sell_stop_bid(self):
        self.assertEqual(self.contact("sell", "stop", D("99")).tick.sequence, 2)

    def test_stop_gap_quote_not_level(self):
        self.assertEqual(self.contact("buy", "stop", D("102")).executable_quote, D("103"))

    def test_cancel_wins_same_timestamp(self):
        self.assertEqual(self.contact("buy", "limit", D("100"), cancel=20).status, "CANCELLED")

    def test_expiry_wins_same_timestamp(self):
        self.assertEqual(self.contact("buy", "limit", D("100"), expiry=20).status, "EXPIRED")

    def test_no_fake_expiry(self):
        self.assertEqual(self.contact("buy", "limit", D("1")).status, "UNRESOLVED_COVERAGE")

    def test_bad_digest(self):
        with self.assertRaises(TickContractError):
            replace(self.w, expected_sha256="0"*64)

    def test_gap(self):
        with self.assertRaises(TickContractError):
            replace(self.w, max_gap_ms=9)

    def test_duplicate_sequence(self):
        with self.assertRaises(TickContractError):
            window(tick(0, 0, "99", "100"), tick(10, 0, "99", "100"))

    def test_missing_sequence(self):
        with self.assertRaises(TickContractError):
            window(tick(0, 0, "99", "100"), tick(10, 2, "99", "100"))

    def test_reverse_time(self):
        with self.assertRaises(TickContractError):
            window(tick(0, 0, "99", "100"), tick(15, 1, "99", "100"),
                   tick(10, 2, "99", "100"), tick(20, 3, "99", "100"))

    def test_crossed_quote(self):
        with self.assertRaises(TickContractError):
            tick(0, 0, "101", "100")

    def test_off_grid(self):
        with self.assertRaises(TickContractError):
            self.contact("buy", "limit", D("99.001"))

    def test_same_timestamp_signal_exclusion(self):
        self.assertEqual(self.contact("buy", "market", active=10).tick.sequence, 2)

    def test_protection_long_bid_stop(self):
        result = observe_protection(self.w, entry_contact=self.contact("buy", "market"),
                                    intent=EntryIntent("buy", "market", 0, 40), stop=D("99"), target=D("102"))
        self.assertEqual((result.status, result.tick.sequence), ("STOP_CONTACT", 2))

    def test_protection_short_ask_target(self):
        result = observe_protection(self.w, entry_contact=self.contact("sell", "market"),
                                    intent=EntryIntent("sell", "market", 0, 40), stop=D("102"), target=D("99"))
        self.assertEqual((result.status, result.tick.sequence), ("TARGET_CONTACT", 2))

    def test_protection_same_time_sequence(self):
        w = window(tick(0, 0, "99", "100"), tick(10, 1, "100", "101"),
                   tick(10, 2, "103", "104"), tick(20, 3, "98", "99"))
        e = observe_entry(w, EntryIntent("buy", "market", 0, 30))
        r = observe_protection(w, entry_contact=e, intent=EntryIntent("buy", "market", 0, 30), stop=D("99"), target=D("103"))
        self.assertEqual((r.status, r.tick.sequence), ("TARGET_CONTACT", 2))

    def test_entry_spread_ambiguity(self):
        result = observe_protection(self.w, entry_contact=self.contact("buy", "market"),
                                    intent=EntryIntent("buy", "market", 0, 40), stop=D("100"), target=D("103"))
        self.assertEqual(result.status, "UNRESOLVED_ENTRY_PROTECTION")

    def test_wrong_window_rejected(self):
        with self.assertRaises(TickContractError):
            observe_protection(replace(self.w, source_revision="different"),
                               entry_contact=self.contact("buy", "market"),
                               intent=EntryIntent("buy", "market", 0, 40), stop=D("99"), target=D("103"))

    def test_forged_entry_rejected(self):
        intent = EntryIntent("buy", "market", 0, 40)
        actual = observe_entry(self.w, intent)
        forged = replace(actual, tick=self.w.ticks[2], executable_quote=D("99"))
        with self.assertRaises(TickContractError):
            observe_protection(self.w, entry_contact=forged, intent=intent,
                               stop=D("97"), target=D("103"))

    def test_wrong_intent_rejected(self):
        with self.assertRaises(TickContractError):
            observe_protection(self.w, entry_contact=self.contact("buy", "market"),
                               intent=EntryIntent("buy", "limit", 0, 40, D("100")),
                               stop=D("97"), target=D("103"))

    def test_decimal_context_independence(self):
        ts = (tick(0, 0, "1234.56", "1234.57"), tick(10, 1, "1234.58", "1234.59"))
        normal = window(*ts)
        with localcontext() as ctx:
            ctx.prec = 3
            low = window(*ts)
            self.assertEqual(low.binding, normal.binding)
            self.assertEqual(observe_entry(low, EntryIntent("buy", "market", 0, 20)).executable_quote, D("1234.59"))

    def test_replay(self):
        self.assertEqual(self.contact("sell", "stop", D("99")), self.contact("sell", "stop", D("99")))

    def test_no_future_activation(self):
        with self.assertRaises(TickContractError):
            self.contact("buy", "market", active=35)


if __name__ == "__main__":
    unittest.main()
