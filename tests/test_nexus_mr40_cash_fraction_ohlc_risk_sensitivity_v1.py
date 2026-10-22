"""No-network fixed cash-reserve MR40 OHLC DD sensitivity safety tests."""
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from research.nexus_mr40_cash_fraction_ohlc_risk_sensitivity_v1 import (
    possible_equity, evaluate_fraction, compare_reference, locked_protocol, run,
    FRACTIONS, PROTOCOL
)


def bar(i,op,hi,lo,cl):
    return [i*14400000,str(op),str(hi),str(lo),str(cl),"1"]


def trade(rows,ent,ex):
    return {
        "entry_next_open_index":ent,"exit_next_open_index":ex,
        "entry_next_open_ms":rows[ent][0],"exit_next_open_ms":rows[ex][0],
        "entry_next_open_price":rows[ent][1],"exit_next_open_price":rows[ex][1],
    }


class TestCashFractionRisk(unittest.TestCase):
    def test_one_half_fraction_pays_fees_only_on_invested_half(self):
        q=possible_equity(D(500),D("0.5"),D(100),D(100),D("0.001"))
        self.assertEqual(q,D(250)+D(250)*D("0.999")**2)

    def test_zero_fee_half_fraction_float_bounds_distinct_with_same_candle_ambiguity(self):
        rows=[bar(0,100,120,80,100),bar(1,100,101,99,100)]
        # Explicit zero-fee synthetic branch, independent of VIP0 study rate.
        z=evaluate_fraction(rows,[trade(rows,0,1)],D("0.50"),fee=D(0))
        self.assertEqual(D(z["realized_only_max_dd_pct"]),D(0))
        self.assertEqual(D(z["prior_high_to_current_low_global_OHLC_dd_lower_pct"]),D(10))
        self.assertTrue(D(z["adversarial_same_bar_high_first_OHLC_dd_upper_pct"])>D(18))
        self.assertTrue(D(z["adversarial_same_bar_high_first_OHLC_dd_upper_pct"])<D(19))

    def test_full_fraction_same_as_original_fee_buy_and_sell(self):
        self.assertEqual(possible_equity(D(500),D(1),D(100),D(110),D("0.001")),
                         D(500)*D("0.999")**2*D("1.1"))

    def test_fraction_above_one_refused_instead_of_leverage(self):
        with self.assertRaisesRegex(ValueError,"unsafe_sizing"):
            possible_equity(D(500),D("1.01"),D(100),D(110))

    def test_exit_bar_low_must_be_excluded_when_flat(self):
        rows=[bar(0,100,101,99,100),bar(1,100,100,1,1)]
        z=evaluate_fraction(rows,[trade(rows,0,1)],D("1.00"))
        self.assertTrue(D(z["adversarial_same_bar_high_first_OHLC_dd_upper_pct"])<D(3))

    def test_only_four_fixed_fractions_allowed(self):
        rows=[bar(0,100,110,90,100),bar(1,100,101,99,100)]
        with self.assertRaisesRegex(ValueError,"not_preregistered"):
            evaluate_fraction(rows,[trade(rows,0,1)],D("0.33"))
        self.assertEqual(FRACTIONS,(D("0.25"),D("0.50"),D("0.75"),D("1.00")))

    def test_wrong_baseline_fails_even_if_result_attractive(self):
        v={
            "compound_exit_equity_usdt":"500",
            "realized_only_max_dd_pct":"0",
            "prior_high_to_current_low_global_OHLC_dd_lower_pct":"1",
            "adversarial_same_bar_high_first_OHLC_dd_upper_pct":"1",
            "held_4h_bars":1,
        }
        fee={"closed_trade_equity_end_usdt":"500","max_closed_trade_only_drawdown_pct":"0"}
        risk={
            "guaranteed_minimum_drawdown_from_prior_4h_highs_to_lows_pct":"2",
            "adversarial_high_before_low_max_dd_upper_bound_pct":"2","total_held_4h_bars":1,
        }
        with self.assertRaisesRegex(ValueError,"parity_failed"):
            compare_reference(v,fee,risk)

    def test_no_result_overwrite_even_when_sources_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d);out=path/"locked.json"
            out.write_text("do not delete")
            with self.assertRaisesRegex(ValueError,"refuse_overwrite"):
                run(path/"none",path,path/"none.gz",path/"none-fee",path/"none-risk",out)
            self.assertEqual(out.read_text(),"do not delete")

    def test_wrong_schema_never_passes(self):
        with self.assertRaisesRegex(ValueError,"protocol_changed"):
            locked_protocol({"schema":PROTOCOL})


if __name__=="__main__":
    unittest.main()
