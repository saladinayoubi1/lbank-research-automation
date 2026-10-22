"""Rigorous intraposition 4h high/low DD bounds, not invented intrabar paths."""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_all47_intratrade_ohlc_equity_bounds_v1 import (
    dd_fraction,mtm_liquidation_balance,intrapos_risk,run
)


def bar(i,op,high,low,close):
    return [i*14400000,str(op),str(high),str(low),str(close),"1"]


def pair(ent,ex,rows):
    return {
        "entry_signal_index":ent-1,
        "exit_signal_index":ex-1,
        "entry_next_open_index":ent,
        "exit_next_open_index":ex,
        "entry_next_open_ms":rows[ent][0],
        "exit_next_open_ms":rows[ex][0],
        "entry_next_open_price":rows[ent][1],
        "exit_next_open_price":rows[ex][1],
        "window":"train",
    }


class TestMR40OHLCBounds(unittest.TestCase):
    def test_one_bar_unknown_high_low_order_yields_nontrivial_range(self):
        rows=[bar(0,100,120,80,100),bar(1,100,101,99,100)]
        r=intrapos_risk(rows,[pair(0,1,rows)],D("0"))
        self.assertEqual(D(r["closed_trade_only_max_dd_pct"]),D(0))
        self.assertEqual(D(r["guaranteed_minimum_drawdown_from_prior_4h_highs_to_lows_pct"]),D(20))
        self.assertLess(abs(D(r["adversarial_high_before_low_max_dd_upper_bound_pct"])-D("33.33333333333333333333333333")),D("1e-20"))
        self.assertEqual(r["max_holding_hours"],4)
        self.assertEqual(D(r["largest_price_only_MAE_pct"]),D(-20))

    def test_prior_finished_high_must_beat_later_low_even_with_unknown_order(self):
        rows=[bar(0,100,120,100,110),
              bar(1,110,110,90,100),
              bar(2,100,105,95,100)]
        r=intrapos_risk(rows,[pair(0,2,rows)],D("0"))
        self.assertEqual(D(r["guaranteed_minimum_drawdown_from_prior_4h_highs_to_lows_pct"]),D(25))
        self.assertEqual(D(r["adversarial_high_before_low_max_dd_upper_bound_pct"]),D(25))
        self.assertEqual(r["max_holding_4h_bars"],2)

    def test_fees_multiply_held_mark_to_market_liquidation(self):
        got=mtm_liquidation_balance(D(500),D(100),D(80),D("0.001"))
        self.assertEqual(got,D(500)*D("0.999")*D("0.8")*D("0.999"))
        self.assertTrue(got<D(400))

    def test_already_exited_cannot_read_exit_bar_low(self):
        rows=[bar(0,100,101,99,100),bar(1,100,100,1,1)]
        r=intrapos_risk(rows,[pair(0,1,rows)],D("0"))
        self.assertEqual(D(r["largest_price_only_MAE_pct"]),D(-1))
        self.assertLess(D(r["adversarial_high_before_low_max_dd_upper_bound_pct"]),D(3))

    def test_source_bar_timestamp_gap_is_hard_failure(self):
        rows=[bar(0,100,120,80,100),bar(1,101,110,90,100),bar(2,100,101,99,100)]
        p=pair(0,2,rows)
        rows[1][0]+=5000
        with self.assertRaisesRegex(ValueError,"market_bar_gap"):
            intrapos_risk(rows,[p],D("0"))

    def test_no_output_file_overwrite_even_without_market_data(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            out=d/"existing.json";out.write_text("do not replace")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(d/"not.json",d,d/"not.gz",d/"not_fee.json",out)
            self.assertEqual(out.read_text(),"do not replace")


if __name__=="__main__":
    unittest.main()
