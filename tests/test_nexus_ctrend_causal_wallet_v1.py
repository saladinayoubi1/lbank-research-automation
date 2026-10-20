"""Concrete synthetic accounting witnesses; no vendor code or market data."""
import json
import unittest
from decimal import Decimal, localcontext

from research.nexus_ctrend_causal_wallet_v1 import LotSpec, PaperWallet, WalletError

D = Decimal


def specs(timestamp, symbols=("A", "B", "C"), *, step=".000001", minimum="0", notional="0"):
    return {s: LotSpec(step, minimum, notional, timestamp) for s in symbols}


def trade(wallet, weights, prices, timestamp=1, *, fee="0", slip="0", lots=None):
    return wallet.rebalance(weights, prices, specs(timestamp) if lots is None else lots,
                            timestamp=timestamp, fee_rate=fee, slippage_rate=slip)


class WalletTests(unittest.TestCase):
    def assertIdentity(self, report):
        with localcontext() as ctx:
            ctx.prec = 250
            expected = D(report["pre_nav"]) - D(report["fees"]) - D(report["slippage"])
        self.assertEqual(D(report["post_nav"]), expected)
        self.assertGreaterEqual(D(report["cash"]), 0)
        self.assertTrue(all(D(q) >= 0 for q in report["positions"].values()))
        json.dumps(report)

    def assertAtomic(self, wallet, operation):
        before = (wallet.cash, wallet.positions, wallet.journal)
        with self.assertRaises(WalletError):
            operation()
        self.assertEqual((wallet.cash, wallet.positions, wallet.journal), before)

    def test_cash_and_public_snapshots(self):
        wallet = PaperWallet()
        self.assertEqual(wallet.nav({}), D(500))
        self.assertEqual(wallet.journal, [])
        report = wallet.mark({}, timestamp=1)
        self.assertEqual(report["max_drawdown"], "0")
        journal = wallet.journal
        journal[0]["cash"] = "-999"
        self.assertEqual(wallet.cash, D(500))
        self.assertEqual(wallet.journal[0]["cash"], "500")

    def test_fee_and_adverse_slippage_paid_on_entry(self):
        wallet = PaperWallet()
        report = trade(wallet, {"A": "1"}, {"A": "100"}, fee=".01", slip=".02",
                       lots=specs(1, step=".001"))
        # 500/(100*1.02*1.01), then floor to .001 units.
        self.assertEqual(wallet.positions, {"A": D("4.853")})
        self.assertEqual(wallet.cash, D(".04394"))
        self.assertEqual(D(report["fees"]), D("4.95006"))
        self.assertEqual(D(report["slippage"]), D("9.706"))
        self.assertEqual(D(report["post_nav"]), D("485.34394"))
        self.assertIdentity(report)

    def test_fractional_cash_target_reserves_all_costs(self):
        wallet = PaperWallet()
        report = trade(wallet, {"A": ".5"}, {"A": "100"}, fee=".01", slip=".02",
                       lots=specs(1, step=".001"))
        self.assertGreaterEqual(wallet.cash, D(report["post_nav"]) / 2)
        self.assertLess(D(report["continuous_target_nav"]), D(500))
        self.assertIdentity(report)

    def test_sells_fund_buys_without_borrowing(self):
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"})
        report = trade(wallet, {"B": "1"}, {"A": "100", "B": "100"}, 2,
                       fee=".01", slip=".02", lots=specs(2, step=".001"))
        self.assertEqual([(f["side"], f["symbol"]) for f in report["fills"]],
                         [("sell", "A"), ("buy", "B")])
        self.assertEqual(D(report["fills"][0]["cash_after"]), D("485.100"))
        self.assertTrue(all(D(f["cash_after"]) >= 0 for f in report["fills"]))
        self.assertIdentity(report)

    def test_held_drift_requires_rebalance_even_when_targets_unchanged(self):
        wallet = PaperWallet()
        trade(wallet, {"A": ".5", "B": ".5"}, {"A": "100", "B": "100"})
        report = trade(wallet, {"A": ".5", "B": ".5"}, {"A": "200", "B": "100"},
                       2, fee=".003")
        self.assertEqual(D(report["pre_nav"]), D(750))
        self.assertEqual([(f["symbol"], f["side"]) for f in report["fills"]],
                         [("A", "sell"), ("B", "buy")])
        self.assertEqual(D(report["fees"]), D(".75"))
        self.assertEqual(D(report["traded_reference_notional"]), D(250))
        self.assertIdentity(report)

    def test_target_equal_to_drifted_weights_needs_no_trades(self):
        wallet = PaperWallet()
        trade(wallet, {"A": ".5", "B": ".5"}, {"A": "100", "B": "100"})
        # Both division and the residual use the documented 50-digit context.
        with localcontext() as ctx:
            ctx.prec = 50
            weights = {"A": D(2) / 3}
            weights["B"] = D(1) - weights["A"]
        report = trade(wallet, weights, {"A": "200", "B": "100"}, 2, fee=".003")
        self.assertEqual(report["fills"], [])
        self.assertEqual(D(report["fees"]), 0)
        self.assertEqual(wallet.positions, {"A": D("2.5"), "B": D("2.5")})
        self.assertIdentity(report)

    def test_floor_rounding_leaves_cash(self):
        wallet = PaperWallet()
        report = trade(wallet, {"A": "1"}, {"A": "30"}, lots=specs(1, step=".1"))
        self.assertEqual(wallet.positions, {"A": D("16.6")})
        self.assertEqual(wallet.cash, D(2))
        self.assertGreater(D(report["rounding"]["A"]["unallocated_quantity"]), 0)
        self.assertIdentity(report)

    def test_one_invalid_buy_prevents_every_planned_sale(self):
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"})
        self.assertAtomic(wallet, lambda: trade(wallet, {"B": ".9", "C": ".1"},
                          {"A": "100", "B": "100", "C": "100"}, 2,
                          lots={**specs(2), "C": LotSpec(".001", "0", "100", 2)}))
        # Failure did not advance the timestamp or consume the snapshot.
        self.assertEqual(wallet.mark({"A": "100"}, timestamp=1)["nav"], "500")

    def test_tiny_delta_is_rejected_instead_of_omitted(self):
        for minimum, notional in ((".1", "0"), ("0", "10")):
            with self.subTest(minimum=minimum, notional=notional):
                wallet = PaperWallet()
                trade(wallet, {"A": "1"}, {"A": "100"})
                self.assertAtomic(wallet, lambda: trade(wallet, {"A": ".99"}, {"A": "100"},
                                  2, lots=specs(2, minimum=minimum, notional=notional)))

    def test_positive_target_rounding_to_zero_blocks_whole_batch(self):
        wallet = PaperWallet()
        self.assertAtomic(wallet, lambda: trade(wallet, {"A": ".999", "B": ".001"},
                          {"A": "100", "B": "100"}, lots=specs(1, step="1")))

    def test_changed_lot_step_does_not_hide_unsellable_dust(self):
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"})
        self.assertAtomic(wallet, lambda: trade(wallet, {}, {"A": "100"}, 2,
                          lots=specs(2, step="2")))

    def test_missing_held_mark_never_renormalizes_survivors(self):
        wallet = PaperWallet()
        trade(wallet, {"A": ".5", "B": ".5"}, {"A": "100", "B": "100"})
        self.assertAtomic(wallet, lambda: wallet.mark({"A": "100"}, timestamp=2))
        self.assertAtomic(wallet, lambda: trade(wallet, {"A": "1"}, {"A": "100"}, 2))
        before = wallet.journal
        with self.assertRaises(WalletError):
            wallet.nav({"A": "100"})
        self.assertEqual(wallet.journal, before)

    def test_liquidation_occurs_only_on_explicit_empty_target(self):
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"})
        wallet.mark({"A": "110"}, timestamp=2)
        self.assertEqual(wallet.positions, {"A": D(5)})
        report = trade(wallet, {}, {"A": "110"}, 2, fee=".01", slip=".02")
        self.assertEqual(wallet.positions, {})
        self.assertEqual(wallet.cash, D("533.610"))
        self.assertEqual(report["fills"][0]["side"], "sell")
        self.assertIdentity(report)

    def test_true_compounded_drawdown_is_nineteen_percent(self):
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"})
        self.assertEqual(D(wallet.mark({"A": "110"}, timestamp=2)["nav"]), D(550))
        wallet.mark({"A": "99"}, timestamp=3)
        report = wallet.mark({"A": "89.1"}, timestamp=4)
        self.assertEqual(D(report["max_drawdown"]), D(".19"))
        self.assertEqual(D(report["peak_nav"]), D(550))

    def test_first_loss_is_included(self):
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"})
        self.assertEqual(D(wallet.mark({"A": "90"}, timestamp=2)["max_drawdown"]), D(".1"))

    def test_snapshot_expiry_future_and_explicit_validity(self):
        for spec in (LotSpec(".01", "0", "0", 2), LotSpec(".01", "0", "0", 0),
                     LotSpec(".01", "0", "0", 0, valid_until=0)):
            wallet = PaperWallet()
            self.assertAtomic(wallet, lambda: trade(wallet, {"A": "1"}, {"A": "100"},
                              lots={"A": spec}))
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"},
              lots={"A": LotSpec(".01", "0", "0", 0, valid_until=1)})
        self.assertEqual(wallet.positions, {"A": D(5)})
        with self.assertRaises(WalletError):
            LotSpec(".01", "0", "0", 3, valid_until=2)

    def test_clock_allows_coherent_same_timestamp_but_rejects_conflict(self):
        wallet = PaperWallet()
        trade(wallet, {"A": "1"}, {"A": "100"})
        wallet.mark({"A": "100"}, timestamp=1)
        trade(wallet, {"A": ".5"}, {"A": "100"}, 1)
        self.assertAtomic(wallet, lambda: wallet.mark({"A": "101"}, timestamp=1))
        self.assertAtomic(wallet, lambda: wallet.mark({"A": "100"}, timestamp=0))
        self.assertAtomic(wallet, lambda: wallet.mark({"A": "100"}, timestamp=True))

    def test_invalid_numbers_and_leverage_are_atomic(self):
        cases = [lambda w, x=x: trade(w, {"A": x}, {"A": "100"})
                 for x in ("-1", "1.01", "NaN", "Infinity", "bad", True, .5, None)]
        cases += [lambda w, x=x: trade(w, {"A": "1"}, {"A": x})
                  for x in ("0", "-1", "NaN", "Infinity", "bad", True)]
        cases += [lambda w, x=x: trade(w, {"A": "1"}, {"A": "100"}, fee=x)
                  for x in ("-1", "1", "NaN", True)]
        cases += [lambda w, x=x: trade(w, {"A": "1"}, {"A": "100"}, slip=x)
                  for x in ("-1", "1", "NaN", True)]
        for i, case in enumerate(cases):
            with self.subTest(case=i):
                wallet = PaperWallet()
                self.assertAtomic(wallet, lambda: case(wallet))
        wallet = PaperWallet()
        self.assertAtomic(wallet, lambda: trade(wallet, {"A": ".6", "B": ".5"},
                                                {"A": "100", "B": "100"}))


if __name__ == "__main__":
    unittest.main()
