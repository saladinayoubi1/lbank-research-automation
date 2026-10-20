"""Independent exact examples and bad-receipt tests; no prices or exchange I/O."""
import copy
from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import unittest

from research.nexus_ctrend_bybit_spot_ioc_v1 import (
    SpotError, SpotRules, IOCIntent, SyntheticFill, SpotResearchWallet,
    rules_from_response, plan_initial_allocation,
)
from research.nexus_ctrend_causal_wallet_v1 import WalletError

D = Decimal


def rules(symbol="BTCUSDT", **changes):
    args = dict(symbol=symbol, base_coin=symbol[:-4], quote_coin="USDT",
        base_precision="0.001", quote_precision="0.01", min_order_amt="5",
        max_market_order_qty="10", max_limit_order_qty="20", tick_size="0.01",
        as_of_ms=100, source_id="synthetic:rules", evidence_class="synthetic", valid_until_ms=1000)
    return SpotRules(**{**args, **changes})


def intent(order_id="buy1", **changes):
    args = dict(order_id=order_id, symbol="BTCUSDT", side="Buy", order_type="Market",
        quantity="1", market_unit="baseCoin", reference_price="100", price_bound="101",
        decision_ms=100, submitted_ms=101, source_id="synthetic:orders")
    return IOCIntent(**{**args, **changes})


def fills(order_id="buy1", parts=(("1", "100"),), at=101):
    return [SyntheticFill(f"{order_id}_f{i}", order_id, q, p, at+i) for i, (q, p) in enumerate(parts)]


def settle(wallet, order=None, executions=None, spec=None, *, fee="0.001", at=110, marks=None):
    order = intent() if order is None else order
    executions = fills(order.order_id) if executions is None else executions
    return wallet.settle_ioc(order, executions, rules() if spec is None else spec,
        {"BTCUSDT": "100"} if marks is None else marks, fee_rate=fee, closed_at_ms=at)


class SpotAccountingTests(unittest.TestCase):
    def test_buy_fee_is_received_base_not_extra_cash(self):
        w=SpotResearchWallet(); r=settle(w)
        self.assertEqual(w.cash,D("400")); self.assertEqual(w.positions,{"BTCUSDT":D("0.999")})
        self.assertEqual(r["fills"][0]["fee_coin"],"BTC")
        self.assertEqual(D(r["post_nav"]),D("499.900"))

    def test_partial_buy_cancels_rest_and_charges_only_fills(self):
        w=SpotResearchWallet();r=settle(w,executions=fills(parts=(("0.1","100"),("0.2","101"))))
        self.assertEqual(w.cash,D("469.8"));self.assertEqual(w.positions["BTCUSDT"],D("0.2997"))
        self.assertEqual(r["status"],"PartiallyFilledCanceled")
        self.assertEqual(D(r["canceled_quantity"]),D("0.7"))
        self.assertEqual(D(r["post_nav"]),D("499.77"))

    def test_no_liquidity_changes_no_balance_and_charges_no_fee(self):
        w=SpotResearchWallet();r=settle(w,executions=[])
        self.assertEqual(w.cash,D("500"));self.assertEqual(w.positions,{})
        self.assertEqual(r["status"],"Canceled");self.assertEqual(D(r["fee_marked_usdt"]),0)

    def test_quote_budget_is_spend_not_base_quantity(self):
        w=SpotResearchWallet();o=intent(quantity="100",market_unit="quoteCoin")
        r=settle(w,o,fills(parts=(("0.5","100"),)))
        self.assertEqual(w.cash,D("450"));self.assertEqual(w.positions["BTCUSDT"],D("0.4995"))
        self.assertEqual(D(r["canceled_quantity"]),50);self.assertEqual(r["canceled_quantity_unit"],"quoteCoin")

    def test_sell_fee_is_received_quote_and_fee_dust_is_retained(self):
        w=SpotResearchWallet();settle(w)
        o=intent("sell1",side="Sell",quantity="0.999",reference_price="100",price_bound="99",submitted_ms=111)
        r=settle(w,o,fills("sell1",(("0.999","99"),),at=111),at=112)
        self.assertEqual(w.positions,{})
        self.assertEqual(w.cash,D("498.802099"))
        self.assertEqual(r["fills"][0]["fee_coin"],"USDT")

    def test_partial_execution_below_order_minimum_is_valid(self):
        r=settle(SpotResearchWallet(),executions=fills(parts=(("0.0001","100"),)))
        self.assertEqual(D(r["filled_quote"]),D("0.01"))

    def test_buy_fee_dust_does_not_get_rounded_to_order_grid(self):
        w=SpotResearchWallet();settle(w,fee="0.0015")
        self.assertEqual(w.positions["BTCUSDT"],D("0.9985"))
        o=intent("sell1",side="Sell",quantity="0.998",price_bound="99",submitted_ms=111)
        settle(w,o,fills("sell1",(("0.998","100"),),111),at=112)
        self.assertEqual(w.positions["BTCUSDT"],D("0.0005"))

    def test_favorable_fill_does_not_invent_drawdown_from_a_future_peak(self):
        r=settle(SpotResearchWallet(),executions=fills(parts=(("1","90"),)),fee="0")
        self.assertEqual(D(r["post_nav"]),510);self.assertEqual(D(r["max_drawdown"]),0)

    def test_drawdown_includes_initial_entry_cost(self):
        r=settle(SpotResearchWallet())
        self.assertEqual(D(r["max_drawdown"]),D("0.0002"))

    def test_fraction_reference_reconstructs_multifill_round_trip(self):
        # Separate rational accounting; no adapter arithmetic helpers are used.
        w=SpotResearchWallet();cash=Fraction(500);base=Fraction(0)
        for order,parts,rate in [
            (intent(),(("0.4","100.25"),("0.2","100.75")),"0.0015"),
            (intent("sell1",side="Sell",quantity="0.5",price_bound="99",submitted_ms=111),
             (("0.1","99.25"),("0.3","99.75")),"0.0025")]:
            for q,p in parts:
                q,p,f=Fraction(q),Fraction(p),Fraction(rate)
                if order.side=="Buy":cash-=q*p;base+=q*(1-f)
                else:cash+=q*p*(1-f);base-=q
            r=settle(w,order,fills(order.order_id,parts,order.submitted_ms),fee=rate,at=order.submitted_ms+3)
            self.assertEqual(Fraction(w.cash),cash)
            self.assertEqual(Fraction(w.positions["BTCUSDT"]),base)
            self.assertEqual(Fraction(r["post_nav"]),cash+base*100)

    def test_result_and_journal_copies_cannot_mutate_balances(self):
        w=SpotResearchWallet();r=settle(w);r["positions"].clear();w.journal[0]["fills"].clear()
        self.assertEqual(len(w.journal[0]["fills"]),1);self.assertIn("BTCUSDT",w.positions)

    def test_low_ambient_decimal_precision_does_not_change_settlement(self):
        normal=settle(SpotResearchWallet())
        with localcontext() as ctx:
            ctx.prec=3
            constrained=settle(SpotResearchWallet())
        self.assertEqual(normal,constrained)


class SpotRejectionTests(unittest.TestCase):
    def assertAtomic(self,w,order,executions,**kwargs):
        old=(w.cash,w.positions,w.journal)
        with self.assertRaises(WalletError):settle(w,order,executions,**kwargs)
        self.assertEqual((w.cash,w.positions,w.journal),old)

    def test_overfill_and_duplicate_fill_are_atomic(self):
        for parts in [(("0.6","100"),("0.5","100")),]:
            self.assertAtomic(SpotResearchWallet(),intent(),fills(parts=parts))
        f=fills()[0];self.assertAtomic(SpotResearchWallet(),intent(),[f,f])

    def test_order_replay_is_rejected(self):
        w=SpotResearchWallet();settle(w);self.assertAtomic(w,intent(),fills())

    def test_detached_fill_and_time_corruption_are_rejected(self):
        variants=[fills("other"),fills(at=100),fills(at=111),
                  [SyntheticFill("f1","buy1","0.2","100",105),SyntheticFill("f2","buy1","0.2","100",104)]]
        for receipt in variants:self.assertAtomic(SpotResearchWallet(),intent(),receipt)

    def test_bounds_and_limit_ticks_are_enforced(self):
        self.assertAtomic(SpotResearchWallet(),intent(),fills(parts=(("1","101.01"),)))
        o=intent(order_type="Limit",market_unit=None,price_bound="100.005")
        self.assertAtomic(SpotResearchWallet(),o,[])

    def test_limit_uses_its_own_maximum(self):
        o=intent(order_type="Limit",market_unit=None,quantity="2",price_bound="100")
        r=settle(SpotResearchWallet(),o,fills(parts=(("2","100"),)),rules(max_market_order_qty="1",max_limit_order_qty="2"))
        self.assertEqual(r["status"],"Filled")
        self.assertAtomic(SpotResearchWallet(),intent(quantity="2"),[],spec=rules(max_market_order_qty="1"))

    def test_quote_buy_actual_base_cap_is_enforced(self):
        o=intent(quantity="200",market_unit="quoteCoin")
        self.assertAtomic(SpotResearchWallet(),o,fills(parts=(("2","100"),)),spec=rules(max_market_order_qty="1"))

    def test_request_precision_and_minimum_are_enforced(self):
        for o in [intent(quantity="0.0001"),intent(quantity="0.01"),
                  intent(quantity="10.001",market_unit="quoteCoin")]:
            self.assertAtomic(SpotResearchWallet(),o,[])

    def test_cash_shorting_and_current_metadata_cannot_execute(self):
        self.assertAtomic(SpotResearchWallet(),intent(quantity="5"),[])
        self.assertAtomic(SpotResearchWallet(),intent(side="Sell",price_bound="99"),[])
        self.assertAtomic(SpotResearchWallet(),intent(),[],spec=rules(evidence_class="observed_metadata",source_id="bybit:current",valid_until_ms=None))

    def test_partial_sale_cannot_fund_expected_full_sale_proceeds(self):
        w=SpotResearchWallet();settle(w,intent(quantity="4"),fills(parts=(("4","100"),)))
        o=intent("sell1",side="Sell",quantity="3",price_bound="99",submitted_ms=111)
        settle(w,o,fills("sell1",(("1","100"),),111),at=112)
        self.assertAtomic(w,intent("buy2",quantity="3",submitted_ms=113),[])
        self.assertEqual(w.positions["BTCUSDT"],D("2.996"))

    def test_missing_held_mark_expired_rules_and_time_reversal_fail(self):
        w=SpotResearchWallet();settle(w)
        self.assertAtomic(w,intent("buy2",submitted_ms=111),[],marks={})
        self.assertAtomic(w,intent("buy2",submitted_ms=111),[],spec=rules(valid_until_ms=105),at=112)
        self.assertAtomic(w,intent("buy2",submitted_ms=109),[],at=112)

    def test_invalid_scalar_types_and_unsupported_units_fail(self):
        for changes in [dict(quantity=True),dict(quantity=float("nan")),dict(quantity="Infinity"),
                        dict(market_unit=None),dict(side="Sell",market_unit="quoteCoin"),
                        dict(source_id="bybit:real"),dict(submitted_ms=100)]:
            with self.assertRaises(WalletError):intent(**changes)


class SpotMetadataAndFormationTests(unittest.TestCase):
    def response(self):
        return {"retCode":0,"result":{"category":"spot","list":[{"symbol":"BTCUSDT",
            "baseCoin":"BTC","quoteCoin":"USDT","status":"Trading",
            "lotSizeFilter":{"basePrecision":"0.001","quotePrecision":"0.01","minOrderAmt":"5",
              "maxMarketOrderQty":"10","maxLimitOrderQty":"20","minOrderQty":"999","maxOrderAmt":"1"},
            "priceFilter":{"tickSize":"0.01"}}]}}

    def parse(self,payload):
        return rules_from_response(payload,symbol="BTCUSDT",captured_at_ms=101,
            source_id="bybit:metadata-receipt",evidence_class="observed_metadata")

    def test_parse_spot_fields_without_derivative_or_deprecated_fallback(self):
        r=self.parse(self.response());self.assertEqual(r.min_order_amt,D("5"))
        self.assertEqual(r.base_precision,D("0.001"));self.assertIsNone(r.valid_until_ms)
        with self.assertRaises(SpotError):r.validate_at(102)

    def test_missing_required_field_does_not_use_deprecated_maximum(self):
        p=self.response();del p["result"]["list"][0]["lotSizeFilter"]["maxMarketOrderQty"]
        with self.assertRaises(SpotError):self.parse(p)

    def test_provider_errors_duplicate_symbols_and_nonspot_fail(self):
        cases=[]
        for value in [True,"0",10001]:
            p=self.response();p["retCode"]=value;cases.append(p)
        p=self.response();p["result"]["list"]*=2;cases.append(p)
        p=self.response();p["result"]["category"]="linear";cases.append(p)
        for p in cases:
            with self.assertRaises(SpotError):self.parse(p)

    def test_observed_metadata_cannot_be_backdated_or_given_invented_ttl(self):
        with self.assertRaises(SpotError):rules(evidence_class="observed_metadata",source_id="bybit:current")
        r=self.parse(self.response())
        with self.assertRaises(SpotError):r.validate_at(100)

    def test_five_member_initial_plan_retains_cash_and_actual_partial_positions(self):
        symbols=[f"ASSET{i}USDT" for i in range(5)]
        specs={s:rules(s) for s in symbols};marks={s:"100" for s in symbols}
        orders,residual=plan_initial_allocation({s:"0.19" for s in symbols},specs,marks,
            decision_ms=100,submitted_ms=101)
        self.assertEqual(residual,D("25"));w=SpotResearchWallet()
        for o in orders:
            w.settle_ioc(o,fills(o.order_id,(("0.5","100"),)),specs[o.symbol],marks,
                fee_rate="0.001",closed_at_ms=101)
        self.assertEqual(w.cash,D("250"));self.assertEqual(len(w.positions),5)
        self.assertTrue(all(q==D("0.4995") for q in w.positions.values()))

    def test_small_selected_member_blocks_plan_without_redistribution(self):
        with self.assertRaises(SpotError):
            plan_initial_allocation({"BTCUSDT":"0.001"},{"BTCUSDT":rules()},{"BTCUSDT":"100"},
                decision_ms=100,submitted_ms=101)

    def test_quote_rounding_cash_is_not_redistributed(self):
        orders,residual=plan_initial_allocation({"BTCUSDT":"0.333333"},{"BTCUSDT":rules()},
            {"BTCUSDT":"100"},decision_ms=100,submitted_ms=101)
        self.assertEqual(orders[0].quantity,D("166.66"));self.assertEqual(residual,D("333.34"))


if __name__=="__main__":unittest.main()
