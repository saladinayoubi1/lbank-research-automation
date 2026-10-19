"""Causal target timing and independent wallet tests; no market optimization."""
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as engine
from scripts import nexus_portfolio_risk_cadence_diagnostic as study


def sample(n=90):
    ts = pd.Series(pd.date_range("2022-12-01", periods=n, freq="4h", tz="UTC"))
    baseline = np.zeros((n, 2))
    baseline[:, 0] = .75
    vol = np.full_like(baseline, .3)
    weekly = np.arange(n) % 42 == 0
    return ts, baseline, vol, weekly


def market_from_close(ts, close):
    return {"timestamps": ts, "symbols": study.SYMBOLS,
            "open": close.copy(), "close": close.copy(),
            "high": close * 1.01, "low": close * .99}


class RiskCadenceTests(unittest.TestCase):
    def test_no_risk_change_reproduces_original_targets(self):
        ts, base, vol, weekly = sample()
        out, reduced = study.target_ratchet(ts, base, vol, weekly)
        np.testing.assert_array_equal(out, base)
        self.assertEqual(int(reduced.sum()), 0)

    def test_daily_close_reduces_then_weekly_reset_restores(self):
        ts, base, vol, weekly = sample()
        vol[5, 0] = 1.2
        out, reduced = study.target_ratchet(ts, base, vol, weekly)
        self.assertEqual(ts.iloc[5].hour, 20)
        self.assertEqual(out[4, 0], .75)
        np.testing.assert_array_equal(out[5:42, 0], .25)
        self.assertEqual(out[42, 0], .75)
        self.assertEqual(np.flatnonzero(reduced).tolist(), [5])

    def test_non_daily_observation_does_not_reduce(self):
        ts, base, vol, weekly = sample()
        vol[4, 0] = 10
        out, _ = study.target_ratchet(ts, base, vol, weekly)
        np.testing.assert_array_equal(out, base)

    def test_daily_risk_cannot_enter_from_cash_or_switch_asset(self):
        ts, base, vol, weekly = sample()
        base[:42] = 0
        base[42:] = [0, .75]
        vol[47, 1] = 1.2
        out, _ = study.target_ratchet(ts, base, vol, weekly)
        self.assertEqual(out[:42].sum(), 0)
        self.assertEqual(out[:, 0].sum(), 0)
        self.assertEqual(out[47, 1], .25)

    def test_weekly_priority_when_both_reviews_collide(self):
        ts, base, vol, weekly = sample()
        weekly[5] = True
        vol[5, 0] = 10
        out, reduced = study.target_ratchet(ts, base, vol, weekly)
        self.assertEqual(out[5, 0], .75)
        self.assertFalse(reduced[5])

    def test_missing_risk_goes_cash_without_daily_reentry(self):
        ts, base, vol, weekly = sample()
        vol[5, 0] = np.nan
        out, reduced = study.target_ratchet(ts, base, vol, weekly)
        self.assertEqual(out[5:42].sum(), 0)
        self.assertTrue(reduced[5])
        self.assertEqual(out[42, 0], .75)

    def test_invalid_calendar_or_two_winners_rejected(self):
        ts, base, vol, weekly = sample()
        ts.iloc[3] += pd.Timedelta(hours=1)
        with self.assertRaises(study.CadenceError):
            study.target_ratchet(ts, base, vol, weekly)
        ts, base, vol, weekly = sample()
        base[0] = [.5, .5]
        with self.assertRaises(study.CadenceError):
            study.target_ratchet(ts, base, vol, weekly)

    def test_first_fill_after_daily_close_is_next_00_open(self):
        ts, base, vol, weekly = sample(12)
        vol[5, 0] = 1.2
        out, reduced = study.target_ratchet(ts, base, vol, weekly)
        market = market_from_close(ts, np.full((12, 2), 100.))
        profile = {"initial_cash": 500, "fee_bps": 10, "slippage_bps": 5}
        period = {"start": "2022-12-01", "end": "2022-12-03"}
        trace = {}
        metrics = engine.exact_backtest(market, out, period, profile,
                                       rebalance_mask=weekly, fill_trace=trace)
        risk_fills = [f for f in trace["fills"] if f["source_bar_open_utc"] == ts.iloc[6].isoformat()]
        self.assertEqual(len(risk_fills), 1)
        self.assertEqual(risk_fills[0]["side"], "sell")
        self.assertEqual(pd.Timestamp(risk_fills[0]["executed_at_utc"]),
                         ts.iloc[5] + pd.Timedelta(hours=4))
        qa = study.verify_trace(market, trace, metrics, profile, period, reduced)
        self.assertTrue(qa["ledger_replay_passed"])
        self.assertEqual(qa["buys_after_daily_target_reductions"], 0)

    def test_gap_witness_target_ratchet_is_not_guaranteed_sell_only(self):
        ts, base, vol, weekly = sample(12)
        base[:, 0] = .5
        vol[5, 0] = 1.2
        out, reduced = study.target_ratchet(ts, base, vol, weekly)
        close = np.full((12, 2), 100.)
        close[6:] = 10
        market = market_from_close(ts, close)
        profile = {"initial_cash": 500, "fee_bps": 10, "slippage_bps": 5}
        period = {"start": "2022-12-01", "end": "2022-12-03"}
        trace = {}
        metrics = engine.exact_backtest(market, out, period, profile,
                                       rebalance_mask=weekly, fill_trace=trace)
        qa = study.verify_trace(market, trace, metrics, profile, period, reduced)
        self.assertEqual(qa["buys_after_daily_target_reductions"], 1)

    def test_tail_mutation_preserves_features_targets_fills_and_marks(self):
        n, cut = 1600, 1300
        ts, _, _, weekly = sample(n)
        t = np.arange(n)
        close = np.column_stack([100 * np.exp(.0007*t + .02*np.sin(t/13)),
                                 80 * np.exp(.0006*t + .03*np.cos(t/17))])
        changed = close.copy()
        changed[cut:] *= np.exp(.1*np.sin(t[cut:, None]))
        cfg = json.loads(Path(study.BASELINE_CONFIG).read_text())["candidate"]
        outputs = []
        for prices in (close, changed):
            market = market_from_close(ts, prices)
            state = engine.build_structural_state(market, cfg)
            vol = engine.realized_vol(prices, 30)
            base = engine.construct_weights(state, vol, cfg)
            target, _ = study.target_ratchet(ts, base, vol, weekly)
            trace = {}
            engine.exact_backtest(market, target,
                                 {"start": "2022-12-01", "end": "2023-09-01"},
                                 {"initial_cash": 500, "fee_bps": 10, "slippage_bps": 5},
                                 rebalance_mask=weekly, fill_trace=trace)
            outputs.append((state, vol, target, trace))
        for a, b in zip(outputs[0][0], outputs[1][0]):
            np.testing.assert_array_equal(a[:cut], b[:cut])
        np.testing.assert_array_equal(outputs[0][1][:cut], outputs[1][1][:cut])
        np.testing.assert_array_equal(outputs[0][2][:cut], outputs[1][2][:cut])
        cutoff = ts.iloc[cut]
        for field, timestamp, inclusive in (("fills", "executed_at_utc", False),
                                             ("equity_marks", "bar_closed_at_utc", True)):
            before = lambda row: pd.Timestamp(row[timestamp]) <= cutoff if inclusive else pd.Timestamp(row[timestamp]) < cutoff
            self.assertEqual([r for r in outputs[0][3][field] if before(r)],
                             [r for r in outputs[1][3][field] if before(r)])

    def test_observer_detects_bad_accounting_and_receipt_is_locked(self):
        ts, base, vol, weekly = sample(12)
        market = market_from_close(ts, np.full((12, 2), 100.))
        profile = {"initial_cash": 500, "fee_bps": 10, "slippage_bps": 5}
        period = {"start": "2022-12-01", "end": "2022-12-03"}
        trace = {}
        metrics = engine.exact_backtest(market, base, period, profile, fill_trace=trace)
        trace["equity_marks"][2]["equity_usdt"] += 1
        with self.assertRaises(study.CadenceError):
            study.verify_trace(market, trace, metrics, profile, period, np.zeros(12, dtype=bool))
        contract = json.loads(study.DEFAULT_CONTRACT.read_text())
        lock = json.loads(study.DEFAULT_CONTRACT.with_suffix(".lock.json").read_text())
        self.assertEqual(lock["contract_sha256"], study.digest(contract))
        self.assertEqual(study.source_hash(Path(engine.__file__)), study.ENGINE_SHA256_LF)


if __name__ == "__main__":
    unittest.main()
