"""Synthetic hand/clock/causality and exact prior-contract tests; no market run."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
import ast
import hashlib
import json
import unittest

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

import nexus_causal_elliott_wave12_features as wave
import nexus_composite_strategy_research as research

ROOT = Path(__file__).resolve().parents[1]
IDENT = "factory_causal_elliott_wave12_breakout"


def geometry_points(prices=(100., 120., 110.)):
    return [wave.ElliottPivot(kind, at, at + 3, price)
            for kind, at, price in zip(("low", "high", "low"), (4, 12, 20), prices)]


def pattern_frame(n=44):
    close = np.interp(np.arange(n), [0, 6, 14, 22, 25, 26, 34, 43],
                      [108, 100, 120, 110, 114, 122, 116, 115])
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
                         "open": close - .2, "high": close + .4, "low": close - .6, "close": close})


def controlled_frame(n=64, breakout=24):
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
                          "open": np.full(n, 111.8), "high": np.full(n, 113.),
                          "low": np.full(n, 111.), "close": np.full(n, 112.)})
    frame.loc[4, "low"] = 100.
    frame.loc[12, "high"] = 120.
    frame.loc[20, "low"] = 110.
    if breakout is not None:
        frame.loc[breakout, ["open", "high", "low", "close"]] = [120., 122., 119., 121.]
    return frame


def controlled_features(frame, extra=()):
    points = geometry_points() + list(extra)
    clock = {p.confirmed_at: p for p in points}
    with patch.object(wave, "_confirmed_pivot", side_effect=lambda high, low, at: clock.get(at)):
        return pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame))


def events(features):
    return np.flatnonzero(features["elliott_wave12_close_breakout_event"].to_numpy()).tolist()


def signal_frame(frame, feature_frame):
    frame = frame.copy()
    for name in feature_frame:
        frame[name] = feature_frame[name].to_numpy()
    frame["h4_up"] = 1.
    frame["h1_vol_ok"] = 1.
    frame["previous_close"] = frame["close"].shift(1)
    frame["atr"] = 1.
    return frame


class GeometryTests(unittest.TestCase):
    def test_hand_retracement_and_levels(self):
        got = wave.elliott_wave12_geometry(geometry_points())
        self.assertEqual(got, {"origin_price": 100., "wave1_high": 120., "wave2_low": 110., "retracement": .5})

    def test_fixed_ratio_bounds(self):
        for retracement in (.382, .786):
            self.assertIsNotNone(wave.elliott_wave12_geometry(geometry_points((100, 120, 120-20*retracement))))
        for retracement in (.3819, .7861):
            self.assertIsNone(wave.elliott_wave12_geometry(geometry_points((100, 120, 120-20*retracement))))

    def test_origin_erasure_and_wrong_geometry_are_rejected(self):
        for prices in ((100, 120, 100), (100, 120, 99), (100, 120, 121), (100, 100, 100)):
            self.assertIsNone(wave.elliott_wave12_geometry(geometry_points(prices)))

    def test_wrong_kinds_order_confirmation_and_span(self):
        points = geometry_points()
        variants = [points[:2], [replace(points[0], kind="high"), *points[1:]],
                    [points[0], replace(points[1], index=4, confirmed_at=7), points[2]],
                    [points[0], points[1], replace(points[2], confirmed_at=22)],
                    [points[0], points[1], replace(points[2], index=197, confirmed_at=200)]]
        for variant in variants:
            self.assertIsNone(wave.elliott_wave12_geometry(variant))
        edge = [points[0], points[1], replace(points[2], index=196, confirmed_at=199)]
        self.assertIsNotNone(wave.elliott_wave12_geometry(edge))

    def test_nonfinite_nonpositive_prices(self):
        for bad in (np.nan, np.inf, -1., 0.):
            self.assertIsNone(wave.elliott_wave12_geometry(geometry_points((100, 120, bad))))

    def test_price_scaling_preserves_retracement(self):
        a = wave.elliott_wave12_geometry(geometry_points())
        b = wave.elliott_wave12_geometry(geometry_points((10000, 12000, 11000)))
        self.assertEqual(a["retracement"], b["retracement"])


class CausalityTests(unittest.TestCase):
    def test_actual_pivots_confirm_then_lag_then_break(self):
        got = pd.DataFrame(wave.build_lagged_elliott_wave12_features(pattern_frame()))
        self.assertEqual(events(got), [26])
        self.assertEqual(got.loc[26, "lagged_elliott_origin_index"], 6)
        self.assertEqual(got.loc[26, "lagged_elliott_wave1_index"], 14)
        self.assertEqual(got.loc[26, "lagged_elliott_wave2_index"], 22)
        self.assertEqual(got.loc[26, "lagged_elliott_wave2_confirmed_at"], 25)
        self.assertEqual(got.loc[26, "elliott_wave12_trigger_index"], 26)
        self.assertEqual(got.loc[:25, "lagged_elliott_wave12_active"].sum(), 0)

    def test_every_prefix_is_unchanged(self):
        frame = pattern_frame()
        whole = pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame))
        for length in range(1, len(frame)+1):
            prefix = pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame.iloc[:length]))
            assert_frame_equal(prefix, whole.iloc[:length], check_exact=True)

    def test_future_tail_cannot_repaint_an_emitted_event(self):
        frame = pattern_frame()
        original = pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame))
        changed = frame.copy()
        changed.loc[29:, ["open", "high", "low", "close"]] *= 4
        got = pd.DataFrame(wave.build_lagged_elliott_wave12_features(changed))
        assert_frame_equal(got.iloc[:29], original.iloc[:29], check_exact=True)

    def test_scaling_keeps_event_timing_and_identity(self):
        frame = pattern_frame()
        scaled = frame.copy()
        scaled[["open", "high", "low", "close"]] *= 100
        a = pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame))
        b = pd.DataFrame(wave.build_lagged_elliott_wave12_features(scaled))
        self.assertEqual(events(a), events(b))
        self.assertEqual(a.loc[26, "lagged_elliott_wave2_index"], b.loc[26, "lagged_elliott_wave2_index"])

    def test_ties_and_dual_centers_are_denied(self):
        high = np.full(7, 12.); low = np.full(7, 10.)
        self.assertIsNone(wave._confirmed_pivot(high, low, 6))
        high[3] = 20.; low[3] = 5.
        self.assertIsNone(wave._confirmed_pivot(high, low, 6))
        low[3] = 10.
        self.assertEqual(wave._confirmed_pivot(high, low, 6).kind, "high")

    def test_utc_timezone_and_index_are_preserved(self):
        frame = pattern_frame()
        a = pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame))
        frame["timestamp"] = frame["timestamp"].dt.tz_convert("Asia/Tehran")
        b = pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame))
        assert_frame_equal(a, b, check_exact=True)
        frame.index = ["bar"+str(i) for i in range(len(frame))]
        self.assertEqual(list(pd.DataFrame(wave.build_lagged_elliott_wave12_features(frame)).index), list(frame.index))

    def test_bad_grid_and_market_values_fail_closed(self):
        frame = pattern_frame()
        bad_grid = [frame.drop(index=10), frame.iloc[::-1], frame.drop(columns="timestamp")]
        duplicate = frame.copy(); duplicate.loc[1, "timestamp"] = duplicate.loc[0, "timestamp"]
        misaligned = frame.copy(); misaligned["timestamp"] += pd.Timedelta(seconds=1)
        for bad in [*bad_grid, duplicate, misaligned]:
            with self.assertRaises(ValueError): wave.build_lagged_elliott_wave12_features(bad)
        for col, value in (("high", 1), ("low", 1000), ("close", np.nan), ("open", np.inf), ("low", -1)):
            bad = frame.copy(); bad.loc[10, col] = value
            with self.assertRaises(ValueError): wave.build_lagged_elliott_wave12_features(bad)

    def test_empty_and_insufficient_prefix_have_no_events(self):
        for length in (0, 1, 5, 6):
            got = pd.DataFrame(wave.build_lagged_elliott_wave12_features(pattern_frame().iloc[:length]))
            self.assertEqual(got["elliott_wave12_close_breakout_event"].sum(), 0)


class StateOrderingTests(unittest.TestCase):
    def test_origin_equality_or_breach_beats_same_bar_breakout(self):
        for low in (100., 99.):
            frame = controlled_frame(); frame.loc[24, "low"] = low
            self.assertEqual(events(controlled_features(frame)), [])

    def test_unselected_historical_origin_breach_invalidates_formation(self):
        frame = controlled_frame(); frame.loc[19, "low"] = 99.
        self.assertEqual(events(controlled_features(frame)), [])

    def test_only_closed_price_crosses_trigger(self):
        frame = controlled_frame(breakout=None); frame.loc[24, "high"] = 125.
        self.assertEqual(events(controlled_features(frame)), [])
        frame.loc[24, ["open", "high", "low", "close"]] = [120., 121., 119., 120.]
        self.assertEqual(events(controlled_features(frame)), [])

    def test_preconfirmation_cross_is_not_backfilled(self):
        frame = controlled_frame(breakout=None)
        frame.loc[22:24, ["open", "high", "low", "close"]] = [120., 122., 119., 121.]
        self.assertEqual(events(controlled_features(frame)), [])

    def test_a_fresh_eligible_recross_is_allowed(self):
        frame = controlled_frame()
        frame.loc[22, ["open", "high", "low", "close"]] = [120., 122., 119., 121.]
        frame.loc[23, ["open", "high", "low", "close"]] = [118., 120., 117., 119.]
        self.assertEqual(events(controlled_features(frame)), [24])

    def test_exact_last_eligible_bar_and_expiry(self):
        self.assertEqual(events(controlled_features(controlled_frame(breakout=55))), [55])
        self.assertEqual(events(controlled_features(controlled_frame(breakout=56))), [])

    def test_weaker_same_kind_pivot_does_not_reset_pending_setup(self):
        frame = controlled_frame(breakout=26)
        frame.loc[22, "low"] = 111.
        weak = wave.ElliottPivot("low", 22, 25, 111.)
        got = controlled_features(frame, [weak])
        self.assertEqual(events(got), [26])
        self.assertEqual(got.loc[26, "lagged_elliott_wave2_index"], 20)

    def test_accepted_pivot_disarms_old_setup(self):
        frame = controlled_frame(breakout=25); frame.loc[21, "high"] = 125.
        new_high = wave.ElliottPivot("high", 21, 24, 125.)
        self.assertEqual(events(controlled_features(frame, [new_high])), [])

    def test_closed_event_precedes_same_bar_new_pivot_state(self):
        frame = controlled_frame(); frame.loc[21, "high"] = 125.
        new_high = wave.ElliottPivot("high", 21, 24, 125.)
        got = controlled_features(frame, [new_high])
        self.assertEqual(events(got), [24])
        self.assertEqual(got.loc[24, "lagged_elliott_wave1_index"], 12)

    def test_replacing_wave2_cannot_repeat_consumed_origin_high_pair(self):
        frame = controlled_frame(); frame.loc[25, "low"] = 108.
        frame.loc[30, ["open", "high", "low", "close"]] = [120., 122., 119., 121.]
        replacement = wave.ElliottPivot("low", 25, 28, 108.)
        self.assertEqual(events(controlled_features(frame, [replacement])), [24])

    def test_new_wave_identity_can_trade_without_a_global_count_cap(self):
        frame = controlled_frame()
        frame.loc[25:, ["open", "high", "low", "close"]] = [114.8, 116., 114., 115.]
        frame.loc[26, ["open", "high", "low", "close"]] = [121., 123., 120., 122.]
        frame.loc[34, "low"] = 113.
        frame.loc[38, ["open", "high", "low", "close"]] = [123., 125., 122., 124.]
        new = [wave.ElliottPivot("high", 26, 29, 123.), wave.ElliottPivot("low", 34, 37, 113.)]
        self.assertEqual(events(controlled_features(frame, new)), [24, 38])


class IntegrationTests(unittest.TestCase):
    def config(self):
        ledger = research.load_ledger(ROOT/"tests/fixtures/elliott_v9_terminal_ledger.json")
        return research._frontier_configs_to_screen(ledger)[0]

    def test_all_previous_120_mechanisms_contracts_configs_and_risk_are_exact(self):
        prior = json.loads((ROOT/"tests/fixtures/elliott_v9_prior_inventory.json").read_text())
        current = {k:v for k,v in research.FACTORY_SPECS.items() if k not in (IDENT, "factory_causal_4h_break_1h_retest_cost_breakout")}
        self.assertEqual(current, prior["factory_specs"])
        self.assertEqual(list(current), prior["factory_ids"])
        self.assertEqual([m for m in research.ALL_MECHANISMS if m not in (IDENT, "factory_causal_4h_break_1h_retest_cost_breakout")], prior["all_mechanisms"])
        self.assertEqual([c for c in research.FRONTIER_CONFIGS if c["mechanism"] not in (IDENT, "factory_causal_4h_break_1h_retest_cost_breakout")], prior["frontier_configs"])
        self.assertEqual((len(research.FACTORY_SPECS), len(research.ALL_MECHANISMS)), (95, 122))
        source = (ROOT/"nexus_composite_strategy_research.py").read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "backtest")
        self.assertEqual(hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest(), prior["backtest_function_sha256"])

    def test_fixed_prospective_contract_and_fingerprint_match(self):
        prereg = json.loads((ROOT/"research/causal_elliott_wave12_v9_preregistration.json").read_text())
        self.assertEqual(self.config(), {**prereg["candidate_config"], "fingerprint":prereg["candidate_config_fingerprint"]})
        self.assertEqual((ROOT/"research/mechanism_factory_v9.json").read_bytes(), (ROOT/"research/causal_elliott_wave12_v9_candidate_proposal.json").read_bytes())

    def test_completed_ledger_advances_to_only_elliott_without_mutation(self):
        ledger = research.load_ledger(ROOT/"tests/fixtures/elliott_v9_terminal_ledger.json")
        before = deepcopy(ledger)
        self.assertEqual([c["mechanism"] for c in research._frontier_configs_to_screen(ledger)], [IDENT])
        self.assertEqual(ledger, before)
        self.assertEqual(research.research_mode(ledger), "frontier_tournament")

    def test_every_prior_frontier_tier_precedes_elliott(self):
        terminal = research.load_ledger(ROOT/"tests/fixtures/elliott_v9_terminal_ledger.json")
        for name in research.FRONTIER_MECHANISMS:
            if name in (IDENT, "factory_causal_4h_break_1h_retest_cost_breakout"): continue
            ledger = deepcopy(terminal)
            ledger["mechanisms_evaluated"] = [n for n in ledger["mechanisms_evaluated"] if n != name]
            ledger["frontier_screened_mechanisms"] = [n for n in ledger["frontier_screened_mechanisms"] if n != name]
            self.assertEqual([c["mechanism"] for c in research._frontier_configs_to_screen(ledger)], [name])

    def test_macro_body_atr_and_missing_fields_deny_entry(self):
        minute = pattern_frame()
        frame = signal_frame(minute, pd.DataFrame(wave.build_lagged_elliott_wave12_features(minute)))
        self.assertEqual(np.flatnonzero(research.signal_for(frame, self.config())).tolist(), [26])
        for col, value in (("h4_up", 0), ("h1_vol_ok", 0), ("atr", np.nan), ("atr", 0),
                           ("elliott_wave12_close_breakout_event", 0), ("lagged_elliott_wave12_active", 0),
                           ("open", 200)):
            changed = frame.copy(); changed[col] = value
            self.assertFalse(research.signal_for(changed, self.config()).any())
        with self.assertRaises(ValueError): research.signal_for(frame.drop(columns="elliott_wave12_close_breakout_event"), self.config())

    def test_denied_strategy_gate_does_not_delay_the_consumed_price_event(self):
        minute = controlled_frame(); minute.loc[25, "low"] = 108.
        minute.loc[30, ["open", "high", "low", "close"]] = [120., 122., 119., 121.]
        got = controlled_features(minute, [wave.ElliottPivot("low", 25, 28, 108.)])
        self.assertEqual(events(got), [24])
        frame = signal_frame(minute, got); frame.loc[24, "h4_up"] = 0
        self.assertFalse(research.signal_for(frame, self.config()).any())

    def test_shared_engine_fills_next_open_and_same_bar_stop_first(self):
        frame = pd.DataFrame({"decision_at": pd.date_range("2026-01-01", periods=4, freq="15min", tz="UTC"),
                              "open": [100.,130.,130.,130.], "high": [100.,130.05,130.05,130.05],
                              "low": [100.,129.95,129.95,129.95], "close": [100.,130.,130.,130.], "atr": [1.]*4})
        signals = np.array([True,False,False,False])
        result = research.backtest(frame, signals, fee_bps=0, slip_bps=0, risk_variant=0)
        self.assertEqual(result["closed_round_trips"], 1)
        self.assertEqual(result["net_pnl_usdt"], 0)
        frame[["open","high","low","close"]] = 100.
        frame.loc[1, ["high","low"]] = [104.,98.]
        result = research.backtest(frame, signals, fee_bps=0, slip_bps=0, risk_variant=0)
        self.assertEqual(result["net_pnl_usdt"], -10.)
        self.assertIsNone(result["trade_count_limit"])

    def test_pipeline_exposes_same_helper_events_without_dropping_old_rows(self):
        n = 960
        frames = {}
        for name, interval, count in (("minute15","15min",n),("hour1","1h",n//4),("hour4","4h",n//16)):
            close = 110.+np.sin(np.arange(count)/5)
            frames[name] = pd.DataFrame({"timestamp":pd.date_range("2026-01-01",periods=count,freq=interval,tz="UTC"),
                                         "open":close-.1,"high":close+.5,"low":close-.5,"close":close,"volume":100.})
        original = frames["minute15"].copy(deep=True)
        got = research.build_features(frames)
        expected = wave.build_lagged_elliott_wave12_features(original)
        self.assertEqual(len(got), n)
        self.assertTrue({"atr","h4_up","h1_vol_ok","lagged_bullish_butterfly_event"}.issubset(got.columns))
        for name, series in expected.items():
            np.testing.assert_equal(got[name].to_numpy(), series.to_numpy())


if __name__ == "__main__":
    unittest.main()
