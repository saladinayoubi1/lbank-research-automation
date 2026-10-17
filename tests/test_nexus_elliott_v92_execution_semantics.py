"""V92 strictly synthetic fill execution QA; immutable V91 real-case denial."""
import dataclasses
import unittest
from decimal import Decimal as D

from research.elliott_v92_execution_semantics import execution_v92 as v92

T=1709251200000
MINUTE=60000


def plan(side="long",**updates):
    base=dict(side=side,quantity=D("1"),
              stop=D("95") if side=="long" else D("105"),
              target=D("110") if side=="long" else D("90"),
              fee_bps_per_side=D("10"),
              spread_bps_full=D("4"),
              adverse_slippage_bps_per_side=D("2"),
              max_gross_notional=D("500"),
              max_nominal_risk_including_fees=D("15"))
    base.update(updates)
    return v92.DiagnosticPlan(**base)


def bar(t=T,op="100",hi="110",lo="95",cl="102"):
    return v92.Candle(t,D(op),D(hi),D(lo),D(cl))


def entry(c=None,side="long",p=None,asof=T,closed_through=None):
    c=bar() if c is None else c
    p=plan(side) if p is None else p
    closed_through=T+MINUTE if closed_through is None else closed_through
    return v92.hypothetical_entry_after_confirmation(asof,c,p,closed_through)


class V92SyntheticFillContractTests(unittest.TestCase):
    def test_v91_real_all_cases_still_denied(self):
        result=v92.audit_denied_cases()
        self.assertEqual(result["sources"]["BTCUSDT"]["denied"],6)
        self.assertEqual(result["sources"]["ETHUSDT"]["denied"],2)
        self.assertFalse(result["live_enabled"])
        self.assertFalse(result["paper_eligible"])
        self.assertEqual(result["orders"],0)
        self.assertIsNone(result["real_pnl"])

    def test_bullish_stop_and_target_tie_is_stop_first(self):
        result=entry(bar(hi="112",lo="94"))
        self.assertEqual(result["status"],"SYNTHETIC_CLOSED_WITHIN_ENTRY_BAR")
        self.assertEqual(result["exit"]["classification"],
                         "SYNTHETIC_STOP_FIRST_AMBIGUOUS")
        self.assertLess(D(result["exit"]["illustrative_net_usdt"]),0)
        self.assertIsNone(result["real_pnl"])
        self.assertFalse(result["new_order"])

    def test_bearish_stop_and_target_tie_is_stop_first(self):
        result=entry(bar(hi="107",lo="88"),side="short")
        self.assertEqual(result["exit"]["classification"],
                         "SYNTHETIC_STOP_FIRST_AMBIGUOUS")
        self.assertLess(D(result["exit"]["illustrative_net_usdt"]),0)

    def test_long_target_hit_is_synthetic_only(self):
        result=entry(bar(hi="112",lo="98"))
        self.assertEqual(result["exit"]["classification"],"SYNTHETIC_TARGET")
        self.assertTrue(result["exit"]["synthetic_only"])
        self.assertTrue(result["exit"]["not_historical_pnl"])
        self.assertGreater(D(result["exit"]["fees_usdt"]),0)
        self.assertLess(D(result["exit"]["illustrative_net_usdt"]),
                        D(result["exit"]["gross_usdt"]))
        self.assertIsNone(result["real_pnl"])

    def test_short_target_hit_is_synthetic_only(self):
        result=entry(bar(hi="103",lo="88"),side="short")
        self.assertEqual(result["exit"]["classification"],"SYNTHETIC_TARGET")
        self.assertGreater(D(result["exit"]["illustrative_net_usdt"]),0)
        self.assertFalse(result["exit"]["paper_eligible"])

    def test_no_stop_or_target_returns_no_pnl(self):
        result=entry(bar(hi="105",lo="98"))
        self.assertEqual(result["status"],
                         "SYNTHETIC_OPEN_UNRESOLVED_NO_MARK_TO_MARKET_PROFIT")
        self.assertIsNone(result["exit"])
        self.assertIsNone(result["real_pnl"])

    def test_immediate_postconfirmation_bar_only(self):
        with self.assertRaisesRegex(ValueError,"immediate first"):
            entry(bar(t=T-MINUTE),asof=T)
        with self.assertRaisesRegex(ValueError,"immediate first"):
            entry(bar(t=T+MINUTE),asof=T,closed_through=T+2*MINUTE)

    def test_closed_candle_only(self):
        with self.assertRaisesRegex(ValueError,"not yet closed"):
            entry(closed_through=T)
        with self.assertRaisesRegex(ValueError,"not yet closed"):
            entry(closed_through=T+MINUTE-1)

    def test_invalid_physical_ohlc_rejected(self):
        for c in (bar(hi="99"),bar(lo="101"),bar(op="-3",lo="-3"),
                  bar(hi="NaN"),bar(cl="Infinity")):
            with self.subTest(c=c):
                with self.assertRaises(ValueError):
                    entry(c)

    def test_invalid_binary_float_rejected(self):
        with self.assertRaisesRegex(ValueError,"binary-float"):
            v92.d(100.0)
        with self.assertRaisesRegex(ValueError,"binary-float"):
            v92.d(True)
        self.assertEqual(v92.d("100.00"),D("100.00"))

    def test_nominal_risk_limiter_is_not_profit_score(self):
        restrictive=plan(max_nominal_risk_including_fees=D("1"))
        result=entry(p=restrictive)
        self.assertEqual(result["status"],"REJECT_NOMINAL_STOP_RISK")
        self.assertIsNone(result["real_pnl"])
        self.assertFalse(result["new_order"])

    def test_notional_limiter_rejects_synthetic_fill(self):
        restrictive=plan(quantity=D("100"))
        result=entry(p=restrictive)
        self.assertEqual(result["status"],"REJECT_MAX_DIAGNOSTIC_NOTIONAL")
        self.assertFalse(result["paper_eligible"])

    def test_stop_and_target_direction_strict(self):
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            entry(p=plan(stop=D("102")))
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            entry(p=plan(target=D("92")))

    def test_illegal_fee_parameters_rejected(self):
        with self.assertRaisesRegex(ValueError,"invalid or negative"):
            entry(p=plan(fee_bps_per_side=D("-1")))
        with self.assertRaisesRegex(ValueError,"invalid or negative"):
            entry(p=plan(spread_bps_full=D("10000")))
        with self.assertRaisesRegex(ValueError,"combined adverse"):
            entry(p=plan(spread_bps_full=D("9990"),
                         adverse_slippage_bps_per_side=D("9000")))

    def test_closed_followup_gap_through_long_stop_uses_worse_open(self):
        p=plan()
        opened=entry(bar(hi="104",lo="97"))
        original=D(opened["entry_fill"])
        exit_bar=bar(t=T+MINUTE,op="89",hi="97",lo="87",cl="91")
        out=v92.hypothetical_followup_exit(
            "long",original,p.quantity,p.stop,p.target,exit_bar,p,
            T,T+2*MINUTE)
        self.assertEqual(out["exit"]["classification"],
                         "SYNTHETIC_STOP_GAP_AT_WORSE_OPEN")
        self.assertLess(D(out["exit"]["exit_fill"]),p.stop)
        self.assertLess(D(out["exit"]["illustrative_net_usdt"]),-D("5"))
        self.assertIsNone(out["real_pnl"])

    def test_closed_followup_gap_through_short_stop_uses_worse_open(self):
        p=plan("short")
        opened=entry(bar(hi="104",lo="97"),side="short")
        exit_bar=bar(t=T+MINUTE,op="111",hi="113",lo="105",cl="112")
        out=v92.hypothetical_followup_exit(
            "short",D(opened["entry_fill"]),p.quantity,p.stop,p.target,
            exit_bar,p,T,T+2*MINUTE)
        self.assertEqual(out["exit"]["classification"],
                         "SYNTHETIC_STOP_GAP_AT_WORSE_OPEN")
        self.assertGreater(D(out["exit"]["exit_fill"]),p.stop)

    def test_followup_both_extrema_choose_stop_first(self):
        p=plan()
        opened=entry(bar(hi="104",lo="97"))
        exit_bar=bar(t=T+MINUTE,op="100",hi="115",lo="92",cl="106")
        out=v92.hypothetical_followup_exit(
            "long",D(opened["entry_fill"]),p.quantity,p.stop,p.target,
            exit_bar,p,T,T+2*MINUTE)
        self.assertEqual(out["exit"]["classification"],
                         "SYNTHETIC_STOP_FIRST_AMBIGUOUS")

    def test_followup_unresolved_no_pnl(self):
        p=plan()
        opened=entry(bar(hi="104",lo="97"))
        exit_bar=bar(t=T+MINUTE,op="101",hi="104",lo="99",cl="103")
        out=v92.hypothetical_followup_exit(
            "long",D(opened["entry_fill"]),p.quantity,p.stop,p.target,
            exit_bar,p,T,T+2*MINUTE)
        self.assertEqual(out["status"],"SYNTHETIC_STILL_OPEN_NO_PNL")
        self.assertIsNone(out["real_pnl"])

    def test_future_followup_bar_rejected(self):
        p=plan()
        opened=entry(bar(hi="104",lo="97"))
        with self.assertRaisesRegex(ValueError,"next chronological minute"):
            v92.hypothetical_followup_exit(
                "long",D(opened["entry_fill"]),p.quantity,p.stop,p.target,
                bar(t=T+2*MINUTE,op="100",hi="104",lo="98"),p,T,T+3*MINUTE)
        with self.assertRaisesRegex(ValueError,"fully closed"):
            v92.hypothetical_followup_exit(
                "long",D(opened["entry_fill"]),p.quantity,p.stop,p.target,
                bar(t=T+MINUTE,op="100",hi="104",lo="98"),p,T,T+MINUTE)

    def test_reject_untrusted_prior_position(self):
        p=plan()
        with self.assertRaisesRegex(ValueError,"untrusted prior"):
            v92.hypothetical_followup_exit(
                "short",D("100"),p.quantity,p.stop,p.target,
                bar(t=T+MINUTE,op="100",hi="102",lo="99"),p,T,T+2*MINUTE)

    def test_no_connector_or_real_trade_intent(self):
        self.assertIsNone(v92.ORDER_CONNECTOR)
        self.assertTrue(v92.SYNTHETIC_ONLY)
        self.assertTrue(v92.V52_UNCHANGED)
        self.assertFalse(v92.LIVE_ENABLED)
        self.assertFalse(v92.PAPER_ELIGIBLE)
        self.assertFalse(v92.ENTRY_SIGNAL)
