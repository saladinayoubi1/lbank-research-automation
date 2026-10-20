"""Artificial-price tests of independent fixed signals and cash reconstruction."""
from copy import deepcopy
import unittest
import warnings

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as original
from research import portfolio_v3_forward_independent_qa as qa

PROFILE = {"initial_cash": 500, "fee_bps": 10, "slippage_bps": 5}
RISK = {"schema": "nexus.portfolio-v3-causal-close-dd20-nextopen.v1",
        "max_closed_bar_drawdown_fraction": 0.2,
        "halt_rest_of_research_period": True,
        "exit": "next_4h_open_sell_first_no_reentry", "live_authority": False}
CANDIDATE = {"family": "dual_rotation", "params": {
    "absolute_days": 90, "allocation": "winner", "lookbacks": [30, 90, 180],
    "ma_filter_days": 0, "minimum_absolute_return": 0, "quantum": 0.25,
    "rebalance_days": 7, "target_vol": 0.3, "vol_days": 30}}


def market(n=96, *, varying=True):
    x = np.arange(n)
    if varying:
        close = np.column_stack([100 * np.exp(x * 0.0003 + 0.018 * np.sin(x / 7)),
                                 70 * np.exp(x * 0.0002 + 0.025 * np.sin(x / 11))])
    else:
        close = np.full((n, 2), 100.0)
    opened = close * np.column_stack([1 + 0.001 * np.cos(x / 3),
                                     1 - 0.001 * np.sin(x / 5)]) if varying else close.copy()
    return {"symbols": list(qa.SYMBOLS),
            "timestamps": pd.Series(pd.date_range(qa.ANCHOR, periods=n, freq="4h")),
            "open": opened, "high": np.maximum(opened, close) * 1.001,
            "low": np.minimum(opened, close) * 0.999, "close": close}


def case(source=None, weights=None, *, scheduled=True, guarded=False):
    source = market() if source is None else source
    n = len(source["timestamps"])
    weights = np.full((n, 2), 0.5) if weights is None else weights
    end = source["timestamps"].iloc[-1] + pd.Timedelta(hours=4)
    period = {"start": source["timestamps"].iloc[0].strftime("%Y-%m-%d"),
              "end": end.strftime("%Y-%m-%d")}
    mask = np.arange(n) % 42 == 0 if scheduled else None
    trace = {}
    metrics = original.exact_backtest(source, weights, period, PROFILE,
                                     rebalance_mask=mask, fill_trace=trace,
                                     risk_policy=RISK if guarded else None)
    return source, weights, trace, metrics, period


def audit(parts, *, scheduled=True, guarded=False, profile=PROFILE):
    source, weights, trace, metrics, period = parts
    return qa._audit(source, weights, trace, metrics, profile,
                     scheduled=scheduled, guarded=guarded, period=period)


class IndependentSignalTests(unittest.TestCase):
    def test_reference_matches_original_on_variable_artificial_prices(self):
        source = market(1900)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            expected = original.construct_weights(
                original.build_structural_state(source, CANDIDATE),
                original.realized_vol(source["close"], 30), CANDIDATE)
        actual = qa.reference_weights(source)
        np.testing.assert_array_equal(expected, actual)
        self.assertTrue((actual.sum(axis=1) > 0).any())
        for row in range(0, len(actual), 42):
            np.testing.assert_array_equal(actual[row:row + 42],
                                          np.repeat(actual[row:row + 1], len(actual[row:row + 42]), axis=0))

    def test_ties_keep_btc_and_flat_context_stays_cash(self):
        source = market(1500)
        for key in ("open", "high", "low", "close"):
            source[key][:, 1] = source[key][:, 0]
        weights = qa.reference_weights(source)
        self.assertTrue((weights[:, 0] > 0).any())
        self.assertFalse((weights[:, 1] > 0).any())
        self.assertFalse(qa.reference_weights(market(1500, varying=False)).any())

    def test_suffix_mutation_does_not_change_earlier_targets(self):
        source = market(1900)
        expected = qa.reference_weights(source)
        for key in ("open", "high", "low", "close"):
            source[key][1200:] *= np.array([0.2, 4.0])
        np.testing.assert_array_equal(expected[:1200], qa.reference_weights(source)[:1200])

    def test_shifted_or_broken_global_grid_rejected(self):
        source = market(1500)
        source["timestamps"] += pd.Timedelta(hours=4)
        with self.assertRaises(qa.IndependentQAError):
            qa.reference_weights(source)


class IndependentMoneyTests(unittest.TestCase):
    def test_shared_book_partials_and_position_fifo_counts_are_distinct(self):
        result = audit(case())
        self.assertTrue(result["independent_numerical_qa_complete"])
        self.assertEqual(result["closed_positions"], 2)
        self.assertGreater(result["closed_fifo_lot_segments"], 2)
        self.assertGreater(result["fill_events"], result["closed_positions"])
        self.assertAlmostEqual(sum(m["mark_to_market_net_pnl_usdt"] for m in result["monthly"].values()),
                               result["net_pnl_usdt"], places=8)
        self.assertAlmostEqual(sum(p["net_pnl_usdt"] for p in result["closed_position_ledger"]),
                               result["net_pnl_usdt"], places=8)
        self.assertFalse(result["paper_eligible"])

    def test_peer_switch_sells_before_buy_and_first_execution_is_next_open(self):
        source = market()
        weights = np.zeros((96, 2))
        weights[:48, 0], weights[48:, 1] = 1, 1
        parts = case(source, weights, scheduled=False)
        result = audit(parts, scheduled=False)
        fills = parts[2]["fills"]
        self.assertEqual(fills[0]["executed_at_utc"], source["timestamps"].iloc[1].isoformat())
        self.assertEqual([f["side"] for f in fills[1:3]], ["sell", "buy"])
        self.assertEqual(fills[1]["executed_at_utc"], source["timestamps"].iloc[49].isoformat())
        self.assertEqual(result["closed_positions"], 2)

    def test_guarded_gap_exit_uses_next_open_and_never_reenters(self):
        source = market(varying=False)
        source["close"][10:, 0] = 75
        source["open"][11:, 0] = 50
        source["close"][11:, 0] = 50
        source["high"] = np.maximum(source["open"], source["close"]) * 1.001
        source["low"] = np.minimum(source["open"], source["close"]) * 0.999
        weights = np.zeros((96, 2)); weights[:, 0] = 1
        parts = case(source, weights, guarded=True)
        result = audit(parts, guarded=True)
        fills = parts[2]["fills"]
        self.assertEqual(len(fills), 2)
        self.assertEqual(fills[-1]["executed_at_utc"], source["timestamps"].iloc[11].isoformat())
        self.assertLess(fills[-1]["price_usdt"], 50)
        self.assertGreater(result["max_drawdown_fraction"], 0.49)
        self.assertTrue(parts[3]["causal_risk_audit"]["halted_for_rest_of_period"])

    def test_last_bar_trigger_has_only_terminal_close_available(self):
        source = market(varying=False)
        source["close"][-1, 0] = 50
        source["low"][-1, 0] = 49
        weights = np.zeros((96, 2)); weights[:, 0] = 1
        parts = case(source, weights, guarded=True)
        audit(parts, guarded=True)
        risk = parts[3]["causal_risk_audit"]
        self.assertTrue(risk["trigger_on_last_bar_no_next_open"])
        self.assertFalse(risk["halted_for_rest_of_period"])
        self.assertEqual(parts[2]["fills"][-1]["fill_kind"], "terminal_bar_close")

    def test_cash_only_has_no_execution_and_no_average_position(self):
        parts = case(weights=np.zeros((96, 2)))
        result = audit(parts)
        self.assertEqual(result["execution_evidence"], "NO_OBSERVED_EXECUTION")
        self.assertIsNone(result["mean_net_per_closed_position_usdt"])
        self.assertEqual(result["terminal_cash_usdt"], 500)
        self.assertEqual(result["net_pnl_usdt"], 0)

    def test_source_fill_and_mark_corruptions_rejected(self):
        good = case()
        mutations = [
            lambda t: t["fills"].pop(),
            lambda t: t["fills"].append(deepcopy(t["fills"][-1])),
            lambda t: t["fills"][0].update(sequence=True),
            lambda t: t["fills"][0].update(executed_at_utc=(pd.Timestamp(t["fills"][0]["executed_at_utc"]) + pd.Timedelta(hours=4)).isoformat()),
            lambda t: t["fills"][0].update(source_bar_open_utc=(pd.Timestamp(t["fills"][0]["source_bar_open_utc"]) + pd.Timedelta(hours=4)).isoformat()),
            lambda t: t["fills"][0].update(price_usdt=t["fills"][0]["price_usdt"] + 0.1),
            lambda t: t["fills"][0].update(quantity=t["fills"][0]["quantity"] * 1.01),
            lambda t: t["fills"][0].update(fee_usdt=t["fills"][0]["fee_usdt"] + 0.1),
            lambda t: t["fills"][0].update(cash_after_usdt=100),
            lambda t: t["fills"][0].update(asset_quantity_after=100),
            lambda t: t["fills"][0].update(price_usdt=float("nan")),
            lambda t: t["equity_marks"][2].update(equity_usdt=100),
            lambda t: t["equity_marks"][2].update(cash_usdt=100),
            lambda t: t["equity_marks"][2].update(asset_quantities=[0, 0]),
            lambda t: t["equity_marks"][2].update(bar_closed_at_utc=t["equity_marks"][3]["bar_closed_at_utc"]),
            lambda t: t.update(terminal_cash_usdt=501),
            lambda t: t.update(initial_cash_usdt=True),
        ]
        for number, mutate in enumerate(mutations):
            with self.subTest(number=number):
                parts = list(good); parts[2] = deepcopy(good[2]); mutate(parts[2])
                with self.assertRaises(qa.IndependentQAError):
                    audit(parts)

    def test_metric_and_cost_or_schedule_substitutions_rejected(self):
        parts = case()
        for field in ("total_return", "max_drawdown", "sharpe", "turnover", "total_fees",
                      "average_exposure", "minimum_cash_usdt", "rebalance_event_count"):
            with self.subTest(field=field):
                changed = list(parts); changed[3] = deepcopy(parts[3]); changed[3][field] += 0.1
                with self.assertRaises(qa.IndependentQAError):
                    audit(changed)
        for field in ("fill_count", "asset_fill_counts"):
            changed = list(parts); changed[3] = deepcopy(parts[3])
            changed[3][field] = True
            with self.assertRaises(qa.IndependentQAError):
                audit(changed)
        with self.assertRaises(qa.IndependentQAError):
            audit(parts, scheduled=False)
        with self.assertRaises(qa.IndependentQAError):
            audit(parts, profile={"initial_cash": 501, "fee_bps": 10, "slippage_bps": 5})
        with self.assertRaises(qa.IndependentQAError):
            audit(parts, profile={"initial_cash": 500, "fee_bps": 25, "slippage_bps": 15})
        changed = list(parts); changed[1] = np.zeros_like(parts[1])
        with self.assertRaises(qa.IndependentQAError):
            audit(changed)

    def test_public_audit_requires_the_full_fixed_horizon(self):
        times = pd.date_range(qa.ANCHOR, "2027-01-17T00:00:00Z", inclusive="left", freq="4h")
        source = market(len(times), varying=False)
        weights = np.zeros((len(times), 2))
        trace = {}
        metrics = original.exact_backtest(source, weights, qa.PERIOD, PROFILE, fill_trace=trace)
        result = qa.audit_cell(source, weights, trace, metrics, PROFILE, scheduled=False, guarded=False)
        self.assertEqual(result["observed_bars"], 540)
        source = {k: v[:-1].copy() if isinstance(v, (np.ndarray, pd.Series)) else v
                  for k, v in source.items()}
        with self.assertRaises(qa.IndependentQAError):
            qa.audit_cell(source, weights[:-1], trace, metrics, PROFILE, scheduled=False, guarded=False)


if __name__ == "__main__":
    unittest.main()
