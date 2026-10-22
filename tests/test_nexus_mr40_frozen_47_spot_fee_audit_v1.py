"""Synthetic spot BUY-in-BTC fee then SELL-in-USDT fee accounting tests."""
from decimal import Decimal as D
import tempfile,unittest
from pathlib import Path
from research.nexus_mr40_frozen_47_spot_fee_audit_v1 import (
    summarize,factor,run,RATES,START
)


def toy(entry,exit_,index=10):
    return {"entry_signal_index":index,"exit_signal_index":index+2,
            "entry_next_open_price":str(entry),
            "exit_next_open_price":str(exit_)}


class TestAll47FeeLedgerMath(unittest.TestCase):
    def test_bybit_spot_vip0_fee_both_sides_no_price_move(self):
        m=factor(toy(100,100),D("0.001"))
        self.assertEqual(m,D("0.999")*D("0.999"))
        self.assertEqual(START*(m-D(1)),D("-0.999500"))
        z=summarize([toy(100,100)])["OFFICIAL_SPOT_VIP0_TAKER_REFERENCE"]
        self.assertEqual(D(z["closed_trade_equity_end_usdt"]),D("499.000500"))
        self.assertEqual(z["positive_net_positions"],0)

    def test_no_fee_break_even_is_exactly_flat(self):
        r=summarize([toy(100,100)])["ZERO_FEE_UPPER_BOUND"]
        self.assertEqual(D(r["closed_trade_equity_end_usdt"]),START)
        self.assertEqual(D(r["max_closed_trade_only_drawdown_pct"]),D(0))

    def test_true_compounding_distinct_from_fixed_500_each_round(self):
        pairs=[toy(100,110,2),toy(100,110,8)]
        z=summarize(pairs)["OFFICIAL_SPOT_VIP0_TAKER_REFERENCE"]
        mult=D("0.999")*D("1.1")*D("0.999")
        self.assertEqual(D(z["closed_trade_equity_end_usdt"]),D("500")*mult*mult)
        self.assertEqual(D(z["fixed_500_quote_per_trade_total_pnl_usdt_NO_COMPOUND"]),
                         D("1000")*(mult-D(1)))

    def test_win_to_loss_drawdown_only_on_realized_closes(self):
        pairs=[toy(100,120,2),toy(100,50,8)]
        z=summarize(pairs)["ZERO_FEE_UPPER_BOUND"]
        self.assertEqual(D(z["closed_trade_equity_end_usdt"]),D("300"))
        self.assertEqual(D(z["max_closed_trade_only_drawdown_pct"]),D("50"))
        self.assertEqual(z["positive_net_positions"],1)

    def test_vip3_reference_must_be_strictly_between_zero_and_vip0_if_profitable(self):
        w=summarize([toy(100,101)])
        a=D(w["ZERO_FEE_UPPER_BOUND"]["closed_trade_equity_end_usdt"])
        b=D(w["OFFICIAL_SPOT_VIP3_TAKER_REFERENCE"]["closed_trade_equity_end_usdt"])
        c=D(w["OFFICIAL_SPOT_VIP0_TAKER_REFERENCE"]["closed_trade_equity_end_usdt"])
        self.assertGreater(a,b)
        self.assertGreater(b,c)

    def test_refuse_overwrite_before_accessing_market_or_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);out=d/"existing.json";out.write_text("immutable")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(d/"not-exist.json",d,d/"not-exist.gz",out)
            self.assertEqual(out.read_text(),"immutable")


if __name__=="__main__":
    unittest.main()
