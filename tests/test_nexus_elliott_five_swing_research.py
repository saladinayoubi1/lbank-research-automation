from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import types
import unittest

import numpy as np
import pandas as pd

import nexus_backtest_observer as observer
import nexus_composite_strategy_research as engine
import nexus_elliott_five_swing_research as candidate
from test_nexus_causal_elliott_five_swing_features import bars
from test_nexus_causal_macro_retest_features import aggregate, minute_fixture, signal_frame

ROOT = Path(__file__).resolve().parents[1]


def canonical_frames(pad=.5):
    n, start = 1008, 256
    close = 80 + np.arange(n) * .02
    minute = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
                           "open": close - .05, "high": close + 2, "low": close - 2,
                           "close": close, "volume": 1.})
    shape = bars(pad=pad)
    minute.loc[start:start + len(shape) - 1, ["open", "high", "low", "close"]] = shape[["open", "high", "low", "close"]].to_numpy()
    return aggregate(minute)


def hand_frame(reason):
    n = 70 if reason == "time_64_bars" else 5
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
                          "open": 100., "high": 100.5, "low": 99.5, "close": 100.1,
                          "previous_close": 99.9, "atr": 1., "h4_up": 1., "h1_vol_ok": 1.,
                          "lagged_elliott5_active": 1., "elliott5_close_breakout_event": 0.,
                          "elliott5_cost_feasible": 1., "lagged_elliott5_wave1_high": 110.,
                          "lagged_elliott5_origin_low": 90.})
    frame["decision_at"] = frame.timestamp + pd.Timedelta(minutes=15)
    frame.loc[0, "elliott5_close_breakout_event"] = 1
    if reason == "target": frame.loc[2, "high"] = 104.
    elif reason == "stop": frame.loc[2, ["high", "low"]] = [104., 98.]
    elif reason == "stop_open_gap": frame.loc[2, ["open", "high", "low", "close"]] = [95., 96., 94., 95.]
    return frame


class AdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = canonical_frames()
        cls.full = candidate.build_elliott_research_features(cls.frames)

    def test_frozen_config_inventory_and_research_authority(self):
        config = candidate.candidate_config()
        self.assertEqual(engine.digest(config), candidate.PARAMETERS["candidate_config_fingerprint"])
        self.assertEqual(engine.digest(candidate.PARAMETERS["conditions"]), config["contract_digest"])
        inventory = {"factory_specs": engine.FACTORY_SPECS, "all_mechanisms": list(engine.ALL_MECHANISMS),
                     "frontier_configs": list(engine.FRONTIER_CONFIGS)}
        self.assertEqual(engine.digest(inventory), candidate.PARAMETERS["prior_full_inventory_semantic_digest"])
        self.assertEqual((len(engine.FACTORY_SPECS), len(engine.ALL_MECHANISMS), len(engine.FRONTIER_CONFIGS)), (95, 122, 111))
        self.assertNotIn(config["mechanism"], engine.ALL_MECHANISMS)
        config["risk_variant"] = 1
        self.assertEqual(candidate.candidate_config()["risk_variant"], 0)
        self.assertTrue(candidate.RESEARCH_ONLY)
        self.assertFalse(candidate.LIVE_ENABLED)
        self.assertFalse(candidate.FACTORY_REGISTERED)

    def test_exact_old_features_inputs_and_open_to_close_adapter(self):
        before = deepcopy(self.frames)
        old = engine.build_features(deepcopy(self.frames))
        pd.testing.assert_frame_equal(old, self.full[old.columns])
        for tf in self.frames:
            pd.testing.assert_frame_equal(self.frames[tf], before[tf])
        self.assertEqual(self.full.loc[316, "decision_at"], self.frames["minute15"].loc[316, "timestamp"] + pd.Timedelta(minutes=15))
        self.assertEqual(self.full.loc[316, "lagged_elliott5_confirmed_at"], 313)
        self.assertFalse(self.full.lagged_elliott5_active.iloc[:314].any())
        self.assertEqual(np.flatnonzero(candidate.candidate_signal_for(self.full)).tolist(), [316])
        self.assertEqual(self.full.loc[316, "elliott5_decision_atr"], self.full.loc[316, "atr"])

    def test_changed_future_three_timeframe_tail_keeps_previous_decisions(self):
        minute = self.frames["minute15"].copy()
        minute.loc[317:, ["open", "high", "low", "close"]] *= 4
        changed = candidate.build_elliott_research_features(aggregate(minute))
        pd.testing.assert_frame_equal(self.full.iloc[:317], changed.iloc[:317])

    def test_body_context_cost_atr_and_missing_fields_fail_closed(self):
        for name, value in (("h4_up", 0), ("h1_vol_ok", 0), ("lagged_elliott5_active", 0),
                            ("elliott5_close_breakout_event", 0), ("elliott5_cost_feasible", 0),
                            ("atr", np.nan), ("atr", 0), ("atr", np.inf), ("open", 120),
                            ("close", np.inf), ("previous_close", np.nan)):
            frame = self.full.copy()
            frame.loc[316, name] = bool(value) if frame[name].dtype == bool else value
            with self.subTest(name=name, value=value):
                self.assertFalse(candidate.candidate_signal_for(frame).any())
        with self.assertRaises(ValueError):
            candidate.candidate_signal_for(self.full.drop(columns="elliott5_cost_feasible"))

    def test_unreviewed_configuration_or_costs_cannot_enter(self):
        for value in (1, False):
            config = candidate.candidate_config(); config["risk_variant"] = value
            with self.assertRaises(ValueError): candidate.candidate_signal_for(self.full, config)
        config = candidate.candidate_config(); config["extra"] = True
        with self.assertRaises(ValueError): candidate.candidate_signal_for(self.full, config)
        with self.assertRaises(ValueError): candidate.backtest_elliott_candidate(self.full, fee_bps=0, slip_bps=0)

    def test_cost_denial_is_a_recorded_price_event_without_a_trade(self):
        frame = candidate.build_elliott_research_features(canonical_frames(pad=.1))
        self.assertEqual(np.flatnonzero(frame.elliott5_close_breakout_event).tolist(), [316])
        self.assertFalse(candidate.candidate_signal_for(frame).any())
        result = candidate.backtest_elliott_candidate(frame, fee_bps=25, slip_bps=15)
        self.assertEqual(result["metrics"]["closed_round_trips"], 0)
        self.assertEqual(result["price_events"][0]["admission"], "signal_denied")
        self.assertIn("elliott5_cost_feasible", result["price_events"][0]["denial_fields"])

    def test_actual_fill_uses_next_open_gap_and_keeps_decision_identity(self):
        frame = self.full.copy()
        frame.loc[317, ["open", "high", "low", "close"]] = [140., 145., 139., 141.]
        result = candidate.backtest_elliott_candidate(frame, fee_bps=25, slip_bps=15)
        trade = result["trades"][0]
        self.assertEqual(trade["decision"]["bar_index"], 316)
        self.assertEqual(trade["fill"]["bar_index"], 317)
        self.assertEqual(trade["entry_reference"], 140)
        self.assertAlmostEqual(trade["entry_slipped"], 140.21)
        self.assertEqual(trade["decision"]["decision_at"], trade["fill"]["open_at"])
        setup = trade["decision"]["setup"]
        self.assertEqual((setup["lagged_elliott5_origin_index"], setup["lagged_elliott5_wave1_index"], setup["lagged_elliott5_wave2_index"]), (262, 302, 310))
        self.assertEqual(setup["lagged_elliott5_confirmed_at"], 313)
        self.assertEqual(result["price_events"][0]["cost_inputs"]["close"], 116)
        self.assertEqual(result["price_events"][0]["cost_inputs"]["span"], 16)

    def test_original_metrics_are_identical_under_both_frozen_profiles(self):
        before = self.full.copy(deep=True)
        for fee, slip in ((10, 5), (25, 15)):
            observed = candidate.backtest_elliott_candidate(self.full, fee_bps=fee, slip_bps=slip)
            original = engine.backtest(self.full, candidate.candidate_signal_for(self.full), fee_bps=fee, slip_bps=slip, risk_variant=0)
            self.assertEqual(json.dumps(original, sort_keys=True), json.dumps(observed["metrics"], sort_keys=True))
            self.assertEqual(len(observed["trades"]), original["closed_round_trips"])
            json.dumps(observed, allow_nan=False)
        pd.testing.assert_frame_equal(self.full, before)
        self.assertIsNone(sys.gettrace())

    def test_actual_entry_stop_rejection_cannot_claim_a_fill(self):
        frame = self.full.copy()
        frame.loc[317, ["open", "high", "low", "close"]] = [1., 2., .5, 1.5]
        result = candidate.backtest_elliott_candidate(frame, fee_bps=25, slip_bps=15)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["entry_attempts"][0]["disposition"], "invalid_stop_or_target")
        self.assertIsNone(result["unfilled_pending_decision"])

    def test_fold_offset_retains_global_pivot_and_fill_indices(self):
        frame = self.full.iloc[307:330].reset_index(drop=True)
        result = candidate.backtest_elliott_candidate(frame, fee_bps=10, slip_bps=5, index_offset=307)
        trade = result["trades"][0]
        self.assertEqual(trade["decision"]["bar_index"], 316)
        self.assertEqual(trade["fill"]["bar_index"], 317)
        self.assertEqual(trade["decision"]["setup"]["lagged_elliott5_origin_index"], 262)

    def test_macro_events_cannot_be_confused_with_explicit_elliott_profile(self):
        frame = self.full.copy(); frame.loc[10, "macro_retest_close_breakout_event"] = 1
        result = candidate.backtest_elliott_candidate(frame, fee_bps=10, slip_bps=5)
        self.assertEqual([e["bar_index"] for e in result["price_events"]], [316])
        self.assertNotIn("lagged_macro_break_high", result["trades"][0]["decision"]["setup"])

    def test_malformed_raw_grid_and_existing_feature_collision_rejected(self):
        frames = deepcopy(self.frames)
        frames["minute15"].loc[20, "timestamp"] = frames["minute15"].loc[19, "timestamp"]
        with self.assertRaises(ValueError): candidate.build_elliott_research_features(frames)
        frames = deepcopy(self.frames); frames["minute15"]["elliott5_cost_feasible"] = 1
        with self.assertRaises(ValueError): candidate.build_elliott_research_features(frames)


class ObservationCompatibilityTests(unittest.TestCase):
    def test_hand_fills_fees_all_exit_reasons_and_unchanged_metrics(self):
        for fee, slip in ((10, 5), (25, 15)):
            for reason in ("target", "stop", "stop_open_gap", "time_64_bars", "terminal_liquidation"):
                frame = hand_frame(reason)
                result = candidate.backtest_elliott_candidate(frame, fee_bps=fee, slip_bps=slip)
                trade = result["trades"][0]
                entry = 100 * (1 + slip / 10000)
                stop, target = entry - 1.5, entry + 3
                reference = {"target": target, "stop": stop, "stop_open_gap": 95.,
                             "time_64_bars": 100.1, "terminal_liquidation": 100.1}[reason]
                quantity = min(1000 / (entry * (1 + fee / 10000)), 10 / 1.5)
                exit_price = reference * (1 - slip / 10000)
                entry_fee, exit_fee = quantity * entry * fee / 10000, quantity * exit_price * fee / 10000
                net = quantity * (exit_price - entry) - entry_fee - exit_fee
                self.assertEqual(trade["exit_reason"], reason)
                self.assertEqual((trade["decision"]["bar_index"], trade["fill"]["bar_index"]), (0, 1))
                for name, value in (("entry_slipped", entry), ("quantity", quantity), ("stop", stop),
                                    ("target", target), ("exit_slipped", exit_price), ("entry_fee", entry_fee),
                                    ("exit_fee", exit_fee), ("net_pnl", net)):
                    self.assertAlmostEqual(trade[name], value, places=9)
                self.assertAlmostEqual(result["metrics"]["net_pnl_usdt"], net, places=7)
                self.assertEqual(result["metrics"], engine.backtest(frame, candidate.candidate_signal_for(frame), fee_bps=fee, slip_bps=slip, risk_variant=0))

    def test_default_macro_observer_matches_frozen_old_output_exactly(self):
        previous = (ROOT / "tests/fixtures/elliott_five_swing_previous_observer.py").read_bytes()
        self.assertEqual(hashlib.sha256(previous).hexdigest(), "ee7bc94002658178e7d140fd5e1d1745d40c5a5e955b688f509076f87ff74ad3")
        old = types.ModuleType("frozen_previous_observer")
        old.__file__ = str(ROOT / "nexus_backtest_observer.py")
        exec(compile(previous, str(ROOT / "tests/fixtures/elliott_five_swing_previous_observer.py"), "exec"), old.__dict__)
        frame = signal_frame(minute_fixture())
        config = next(c for c in engine.FRONTIER_CONFIGS if c["mechanism"] == "factory_causal_4h_break_1h_retest_cost_breakout")
        signals = engine.signal_for(frame, config)
        for fee, slip in ((10, 5), (25, 15)):
            kwargs = dict(fee_bps=fee, slip_bps=slip, risk_variant=0)
            before = old.observe_backtest(engine.backtest, frame, signals, **kwargs)
            after = observer.observe_backtest(engine.backtest, frame, signals, **kwargs)
            self.assertEqual(json.dumps(before, sort_keys=True), json.dumps(after, sort_keys=True))

    def test_unsupported_profile_or_missing_elliott_event_cannot_trace(self):
        frame = hand_frame("target"); signals = candidate.candidate_signal_for(frame)
        with self.assertRaises(ValueError):
            observer.observe_backtest(engine.backtest, frame, signals, fee_bps=10, slip_bps=5, risk_variant=0, event_profile="unknown")
        with self.assertRaises(ValueError):
            observer.observe_backtest(engine.backtest, frame.drop(columns="elliott5_close_breakout_event"), signals,
                                      fee_bps=10, slip_bps=5, risk_variant=0, event_profile="elliott_five_swing")
        self.assertIsNone(sys.gettrace())


if __name__ == "__main__":
    unittest.main()
