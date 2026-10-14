from copy import deepcopy
from pathlib import Path
import ast
import hashlib
import json
import sys
import unittest

import numpy as np
import pandas as pd

import nexus_causal_macro_retest_features as macro
import nexus_composite_strategy_research as research
import nexus_mechanism_factory as factory
from nexus_backtest_observer import observe_backtest

ROOT = Path(__file__).resolve().parents[1]
IDENT = "factory_causal_4h_break_1h_retest_cost_breakout"


def minute_fixture(n=160, trigger=116, retest_hour=1):
    frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
                          "open": 96., "high": 100., "low": 90., "close": 96., "volume": 1.})
    frame.loc[96:111, ["open", "high", "low", "close"]] = [96., 106., 95., 96.]
    frame.loc[111, "close"] = 105.
    frame.loc[112:, ["open", "high", "low", "close"]] = [101.8, 102.3, 100.5, 101.8]
    first = 112 + 4 * (retest_hour - 1)
    for j, values in enumerate(([101., 102., 99.5, 101.2], [101.2, 102.1, 101., 101.4],
                                [101.4, 102.2, 101., 101.6], [101.6, 102.3, 101.1, 101.8])):
        frame.loc[first+j, ["open", "high", "low", "close"]] = values
    if trigger is not None:
        frame.loc[trigger, ["open", "high", "low", "close"]] = [101.8, 103.5, 101., 103.]
    return frame


def aggregate(minute):
    result = {"minute15": minute.copy()}
    for name, width in (("hour1", 4), ("hour4", 16)):
        rows = []
        for start in range(0, len(minute) - width + 1, width):
            group = minute.iloc[start:start+width]
            rows.append({"timestamp": group.iloc[0].timestamp, "open": group.iloc[0].open,
                         "high": group.high.max(), "low": group.low.min(),
                         "close": group.iloc[-1].close, "volume": group.volume.sum()})
        result[name] = pd.DataFrame(rows, columns=minute.columns)
    return result


def features(minute, diagnostics=None):
    return pd.DataFrame(macro.build_lagged_macro_retest_features(aggregate(minute), diagnostics=diagnostics))


def signal_frame(minute):
    frame = pd.concat([minute.reset_index(drop=True), features(minute).reset_index(drop=True)], axis=1)
    frame["decision_at"] = frame.timestamp + pd.Timedelta(minutes=15)
    frame["atr"] = (frame.high-frame.low).shift(1).rolling(14).mean()
    frame["previous_close"] = frame.close.shift(1)
    frame["h4_up"] = frame["h1_vol_ok"] = 1.
    return frame


def events(frame):
    return np.flatnonzero(frame.macro_retest_close_breakout_event.to_numpy()).tolist()


def config():
    return next(c for c in research.FRONTIER_CONFIGS if c["mechanism"] == IDENT)


class LifecycleTests(unittest.TestCase):
    def test_hand_band_and_exact_lagged_timing(self):
        audit = []
        f = features(minute_fixture(), audit)
        self.assertEqual(events(f), [116])
        self.assertEqual(f.loc[116, ["lagged_macro_break_high", "lagged_macro_break_low",
                                     "lagged_macro_retest_trigger_high"]].tolist(), [100., 90., 102.3])
        self.assertEqual(f.loc[111:115, "lagged_macro_retest_active"].tolist(), [0.]*5)
        self.assertEqual(f.loc[116, "lagged_macro_retest_active"], 1)
        self.assertEqual([r["decision_at"] for r in audit[:3]],
                         ["2026-01-02T04:00:00+00:00", "2026-01-02T05:00:00+00:00", "2026-01-02T05:15:00+00:00"])
        self.assertEqual([r["kind"] for r in audit[:3]], ["macro_accepted", "retest_accepted", "price_event"])

    def test_every_three_timeframe_prefix_matches_full_output(self):
        full = aggregate(minute_fixture()); expected = pd.DataFrame(macro.build_lagged_macro_retest_features(full))
        for n in range(1, len(full["minute15"])+1):
            now = full["minute15"].iloc[n-1].timestamp + pd.Timedelta(minutes=15)
            prefix = {"minute15": full["minute15"].iloc[:n]}
            for tf, hours in (("hour1", 1), ("hour4", 4)):
                prefix[tf] = full[tf].loc[full[tf].timestamp + pd.Timedelta(hours=hours) <= now]
            actual = pd.DataFrame(macro.build_lagged_macro_retest_features(prefix))
            pd.testing.assert_frame_equal(actual, expected.iloc[:n])

    def test_future_tail_mutations_all_timeframes_do_not_change_past(self):
        original = aggregate(minute_fixture()); changed = deepcopy(original)
        boundary = original["minute15"].iloc[116].timestamp + pd.Timedelta(minutes=15)
        for tf, hours in (("minute15", .25), ("hour1", 1), ("hour4", 4)):
            future = changed[tf].timestamp + pd.Timedelta(hours=hours) > boundary
            changed[tf].loc[future, ["open", "high", "low", "close", "volume"]] = [500., 510., 490., 505., 1000.]
        a, b = (pd.DataFrame(macro.build_lagged_macro_retest_features(x)).iloc[:117] for x in (original, changed))
        pd.testing.assert_frame_equal(a, b)

    def test_partial_higher_bars_and_overlapping_displacement_hour_cannot_arm(self):
        full = aggregate(minute_fixture())
        # The displacement hour itself touches H and closes bullishly; OPEN<tau.
        full["minute15"] = full["minute15"].iloc[:115]
        f = pd.DataFrame(macro.build_lagged_macro_retest_features(full))
        self.assertFalse(f.lagged_macro_retest_active.any())
        self.assertFalse(f.macro_retest_close_breakout_event.any())

    def test_cold_start_cannot_retroactively_arm_missing_interval_path(self):
        full = aggregate(minute_fixture()); full["minute15"] = full["minute15"].iloc[112:]
        self.assertFalse(pd.DataFrame(macro.build_lagged_macro_retest_features(full)).macro_retest_close_breakout_event.any())

    def test_invalidation_during_wait_beats_later_retest(self):
        for column, value in (("low", 90.), ("close", 100.)):
            minute = minute_fixture(); minute.loc[112, column] = value
            self.assertEqual(events(features(minute)), [])

    def test_same_bar_low_equality_beats_ready_price_cross(self):
        minute = minute_fixture(); minute.loc[116, "low"] = 90.
        f = features(minute)
        self.assertEqual(f.loc[116, "lagged_macro_retest_active"], 1)
        self.assertEqual(events(f), [])

    def test_first_nonbullish_touch_is_decisive(self):
        minute = minute_fixture(); minute.loc[112, ["open", "high"]] = [102., 102.2]
        minute.loc[116:119, ["open", "high", "low", "close"]] = [101., 103.5, 99.5, 102.]
        minute.loc[120, ["open", "high", "low", "close"]] = [102., 104.5, 101., 104.]
        audit = []; f = features(minute, audit)
        self.assertEqual(events(f), [])
        self.assertEqual(sum(r["kind"] == "first_touch_denied" for r in audit), 1)
        self.assertFalse(any(r["kind"] == "retest_accepted" for r in audit))

    def test_no_touch_never_arms_even_with_later_price_increase(self):
        minute = minute_fixture(); minute.loc[112, "low"] = 100.5
        self.assertEqual(events(features(minute)), [])

    def test_retest_deadline_exact_six_hours_allowed_after_deadline_denied(self):
        self.assertEqual(events(features(minute_fixture(trigger=136, retest_hour=6))), [136])
        self.assertEqual(events(features(minute_fixture(trigger=140, retest_hour=7))), [])

    def test_ready_bar_eight_allowed_bar_nine_expired(self):
        self.assertEqual(events(features(minute_fixture(trigger=123))), [123])
        self.assertEqual(events(features(minute_fixture(trigger=124))), [])

    def test_intrabar_high_and_equal_close_are_not_cross_events(self):
        minute = minute_fixture(trigger=118)
        minute.loc[116, ["high", "close"]] = [104., 102.3]
        minute.loc[117, ["open", "high", "close"]] = [102.3, 104., 102.3]
        self.assertEqual(events(features(minute)), [118])

    def test_identity_consumed_when_body_or_regime_denies(self):
        for denial in ("body", "regime"):
            minute = minute_fixture(); minute.loc[118, ["open", "high", "low", "close"]] = [101.8, 104., 101., 103.]
            if denial == "body": minute.loc[116, ["open", "high"]] = [103.2, 103.5]
            f = signal_frame(minute)
            if denial == "regime": f.loc[116, "h4_up"] = 0
            self.assertEqual(events(f), [116])
            self.assertFalse(research.signal_for(f, config()).any())

    def test_cost_denial_consumes_price_event(self):
        minute = minute_fixture()
        # Narrow the preceding 14 actual ranges so the fixed stress target net fails.
        minute.loc[102:115, ["open", "high", "low", "close"]] = [101.8, 101.9, 101.7, 101.8]
        minute.loc[111, ["open", "high", "low", "close"]] = [101.8, 102., 101.7, 101.9]
        minute.loc[112, ["open", "high", "low", "close"]] = [99.9, 100.1, 99.8, 100.05]
        minute.loc[113:115, ["open", "high", "low", "close"]] = [100.05, 100.2, 100.02, 100.1]
        minute.loc[116, ["open", "high", "low", "close"]] = [100.1, 100.4, 100.02, 100.3]
        # Macro close must stay above H; first H1 is bullish and touches H.
        f = signal_frame(minute)
        self.assertEqual(events(f), [116])
        self.assertEqual(f.loc[116, "macro_retest_stress_cost_feasible"], 0)
        self.assertFalse(research.signal_for(f, config()).any())

    def test_old_price_event_precedes_same_close_new_macro(self):
        minute = minute_fixture(trigger=127, retest_hour=3)
        minute.loc[120:123, "high"] = 107.
        minute.loc[127, ["open", "high", "low", "close"]] = [107., 109., 106.5, 108.]
        minute.loc[128:, ["open", "high", "low", "close"]] = [107., 108., 106.5, 107.]
        audit = []; f = features(minute, audit)
        self.assertEqual(events(f), [127])
        same = [r for r in audit if r["decision_index"] == 127]
        self.assertEqual([r["kind"] for r in same], ["price_event", "macro_accepted"])
        self.assertEqual([r["macro_identity"]["h4_index"] for r in same], [6, 7])
        self.assertEqual(f.loc[128, "lagged_macro_retest_active"], 0)

    def test_second_macro_identity_can_emit_without_global_cap(self):
        minute = minute_fixture(n=192)
        minute.loc[127, ["open", "high", "low", "close"]] = [105., 110., 104., 109.]
        minute.loc[128:, ["open", "high", "low", "close"]] = [108., 109., 107., 108.]
        minute.loc[128, ["open", "high", "low", "close"]] = [107., 108., 105.5, 107.2]
        minute.loc[131, "close"] = 108.
        minute.loc[132, ["open", "high", "low", "close"]] = [108., 110.5, 107., 110.]
        self.assertEqual(events(features(minute)), [116, 132])

    def test_strict_three_grid_and_ohlcv_validation(self):
        for tf in ("minute15", "hour1", "hour4"):
            for defect in ("missing", "duplicate", "unordered", "misaligned", "nan", "zero", "high", "volume"):
                data = aggregate(minute_fixture()); f = data[tf]
                if defect == "missing": data[tf] = f.drop(index=1)
                elif defect == "duplicate": f.loc[1, "timestamp"] = f.loc[0, "timestamp"]
                elif defect == "unordered": data[tf] = f.iloc[::-1]
                elif defect == "misaligned": f["timestamp"] += pd.Timedelta(minutes=1)
                elif defect == "nan": f.loc[1, "close"] = np.nan
                elif defect == "zero": f.loc[1, "low"] = 0
                elif defect == "high": f.loc[1, "high"] = 1
                elif defect == "volume": f.loc[1, "volume"] = -1
                with self.subTest(tf=tf, defect=defect), self.assertRaises(ValueError):
                    macro.build_lagged_macro_retest_features(data)
        with self.assertRaises(ValueError): macro.build_lagged_macro_retest_features({})

    def test_original_nonrange_index_and_inputs_preserved(self):
        data = aggregate(minute_fixture()); data["minute15"].index += 500
        before = deepcopy(data)
        f = pd.DataFrame(macro.build_lagged_macro_retest_features(data))
        self.assertEqual(f.index.tolist(), data["minute15"].index.tolist())
        self.assertEqual(f.index[f.macro_retest_close_breakout_event == 1].tolist(), [616])
        for tf in data: pd.testing.assert_frame_equal(data[tf], before[tf])


class CostTests(unittest.TestCase):
    def test_hand_stress_math_and_exact_flat_roundtrip_identity(self):
        result = macro.stress_cost_screen(100., 1., 10.)
        self.assertTrue(result["feasible"])
        for name, expected in (("entry", 100.15), ("stop", 98.65), ("target", 103.15),
                               ("exit", 102.995275), ("flat_cost", .8), ("target_net", 2.3374118125)):
            self.assertAlmostEqual(result[name], expected, places=10)
        self.assertAlmostEqual(100*(1+.0015)*(1+.0025)-100*(1-.0015)*(1-.0025), result["flat_cost"])

    def test_strict_span_boundary_stop_and_net_denials(self):
        for args, reason in (((100., 1., .8), "span_not_above_flat_cost"),
                             ((100., 100., 10.), "nonpositive_stop"),
                             ((100., .1, 10.), "nonpositive_target_net")):
            result = macro.stress_cost_screen(*args)
            self.assertFalse(result["feasible"]); self.assertEqual(result["denial_reason"], reason)
        self.assertTrue(macro.stress_cost_screen(100., 1., np.nextafter(.8, np.inf))["feasible"])

    def test_invalid_and_overflow_inputs_fail_closed(self):
        for values in ((np.nan, 1., 10.), (np.inf, 1., 10.), (0., 1., 10.),
                       (100., 0., 10.), (100., -1., 10.), (100., 1., 0.), (1e308, 1e308, 1e308)):
            self.assertFalse(macro.stress_cost_screen(*values)["feasible"])

    def test_fixed_stress_gate_same_under_both_simulation_profiles_and_no_future_open(self):
        minute = minute_fixture(); before = features(minute)
        changed = minute.copy(); changed.loc[117, ["open", "high", "low", "close"]] = [200., 201., 199., 200.]
        after = features(changed)
        pd.testing.assert_frame_equal(before.iloc[:117], after.iloc[:117])
        self.assertEqual(macro.PARAMETERS["cost_gate_uses_stress_profile_for_both_simulation_profiles"], True)


class IntegrationTests(unittest.TestCase):
    def test_all_94_prior_contracts_121_ids_110_configs_are_exact(self):
        prior = json.loads((ROOT/"tests/fixtures/macro_retest_v10_prior_inventory.json").read_text())
        current = {"factory_specs": {k:v for k,v in research.FACTORY_SPECS.items() if k != IDENT},
                   "all_mechanisms": [m for m in research.ALL_MECHANISMS if m != IDENT],
                   "frontier_configs": [c for c in research.FRONTIER_CONFIGS if c["mechanism"] != IDENT]}
        self.assertEqual(current, prior)
        self.assertEqual(research.digest(current), macro.PARAMETERS["prior_inventory_semantic_digest"])
        self.assertEqual((len(research.FACTORY_SPECS), len(research.ALL_MECHANISMS), len(research.FRONTIER_CONFIGS)), (95, 122, 111))
        source = (ROOT/"nexus_composite_strategy_research.py").read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "backtest")
        self.assertEqual(hashlib.sha256(ast.get_source_segment(source, node).encode()).hexdigest(), macro.PARAMETERS["shared_backtest_function_sha256"])

    def test_frozen_contract_config_and_single_new_tier(self):
        ledger = research.load_ledger(ROOT/"tests/fixtures/macro_retest_v10_terminal_ledger.json"); before = deepcopy(ledger)
        self.assertEqual(research._frontier_configs_to_screen(ledger), [{**macro.PARAMETERS["candidate_config"], "fingerprint": macro.PARAMETERS["candidate_config_fingerprint"]}])
        self.assertEqual(ledger, before)
        self.assertEqual((ROOT/"research/mechanism_factory_v10.json").read_bytes(), (ROOT/"research/causal_macro_break_retest_v10_candidate_proposal.json").read_bytes())
        self.assertEqual(set(research.MACRO_RETEST_EXTENSION_MECHANISMS), {IDENT})
        prior = json.loads((ROOT/"tests/fixtures/macro_retest_v10_prior_approved_fields.json").read_text())
        self.assertEqual(set(factory.CONTEXT_FIELDS) - set(prior["CONTEXT_FIELDS"]), {"lagged_macro_retest_active"})
        self.assertEqual(set(factory.ENTRY_FIELDS) - set(prior["ENTRY_FIELDS"]), {"macro_retest_close_breakout_event", "macro_retest_stress_cost_feasible"})
        self.assertTrue(set(prior["CONTEXT_FIELDS"]) <= factory.CONTEXT_FIELDS)
        self.assertTrue(set(prior["ENTRY_FIELDS"]) <= factory.ENTRY_FIELDS)

    def test_every_previous_frontier_tier_precedes_macro(self):
        terminal = research.load_ledger(ROOT/"tests/fixtures/macro_retest_v10_terminal_ledger.json")
        for name in research.FRONTIER_MECHANISMS:
            if name == IDENT: continue
            ledger = deepcopy(terminal)
            ledger["mechanisms_evaluated"] = [n for n in ledger["mechanisms_evaluated"] if n != name]
            ledger["frontier_screened_mechanisms"] = [n for n in ledger["frontier_screened_mechanisms"] if n != name]
            self.assertEqual([c["mechanism"] for c in research._frontier_configs_to_screen(ledger)], [name])

    def test_body_context_cost_atr_and_missing_fields_deny_entry(self):
        f = signal_frame(minute_fixture()); self.assertEqual(np.flatnonzero(research.signal_for(f, config())).tolist(), [116])
        for col, value in (("h4_up", 0), ("h1_vol_ok", 0), ("atr", np.nan), ("atr", 0),
                           ("macro_retest_close_breakout_event", 0), ("lagged_macro_retest_active", 0),
                           ("macro_retest_stress_cost_feasible", 0), ("open", 200)):
            changed = f.copy(); changed[col] = value
            self.assertFalse(research.signal_for(changed, config()).any())
        with self.assertRaises(ValueError): research.signal_for(f.drop(columns="macro_retest_stress_cost_feasible"), config())

    def test_feature_engine_preserves_all_old_columns_on_source_bound_fixture(self):
        # Compare the actual old and new feature builders on identical synthetic
        # canonical inputs; source text of the old module is frozen separately.
        import types
        old_path = ROOT/"tests/fixtures/macro_retest_v10_previous_engine.py"
        old_bytes = old_path.read_bytes()
        self.assertEqual(hashlib.sha256(old_bytes).hexdigest(), "15bece0ef68256a625532651d10e11f6c32444040f9c9d720ffcc5e29685afeb")
        old = types.ModuleType("v10_previous_engine")
        # The frozen old module resolves contracts relative to its original
        # repository root. Execute its bytes with that same logical location.
        old.__file__ = str(ROOT/"nexus_composite_strategy_research.py")
        exec(compile(old_bytes, str(old_path), "exec"), old.__dict__)
        minute = minute_fixture(n=1008)
        a = old.build_features(deepcopy(aggregate(minute)))
        b = research.build_features(deepcopy(aggregate(minute)))
        pd.testing.assert_frame_equal(a, b[a.columns])
        pd.testing.assert_series_equal(b.atr, (b.high-b.low).shift(1).rolling(14).mean(), check_names=False)


class ObserverTests(unittest.TestCase):
    def hand(self, exit_kind):
        n = 70 if exit_kind == "time_64_bars" else 5
        frame = pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC"),
                              "open": 100., "high": 100.5, "low": 99.5, "close": 100., "atr": 1.})
        frame["decision_at"] = frame.timestamp + pd.Timedelta(minutes=15)
        if exit_kind == "target": frame.loc[2, "high"] = 104.
        elif exit_kind == "stop": frame.loc[2, ["high", "low"]] = [104., 98.]
        elif exit_kind == "stop_open_gap": frame.loc[2, ["open", "high", "low", "close"]] = [95., 96., 94., 95.]
        signals = np.zeros(n, dtype=bool); signals[0] = True
        return frame, signals

    def test_hand_actual_fills_costs_reasons_and_byte_identical_metrics_both_profiles(self):
        for fee, slip in ((10., 5.), (25., 15.)):
            for reason in ("target", "stop", "stop_open_gap", "time_64_bars", "terminal_liquidation"):
                frame, signals = self.hand(reason); before = frame.copy(deep=True); original_signals = signals.copy()
                kwargs = dict(fee_bps=fee, slip_bps=slip, risk_variant=0)
                plain = research.backtest(frame, signals, **kwargs)
                observed = observe_backtest(research.backtest, frame, signals, **kwargs)
                self.assertEqual(json.dumps(plain, sort_keys=True), json.dumps(observed["metrics"], sort_keys=True))
                self.assertEqual(len(observed["trades"]), 1)
                trade = observed["trades"][0]; self.assertEqual(trade["exit_reason"], reason)
                self.assertEqual(trade["decision"]["bar_index"], 0); self.assertEqual(trade["fill"]["bar_index"], 1)
                self.assertEqual(trade["decision"]["decision_at"], trade["fill"]["open_at"])
                entry = 100*(1+slip/10000); stop = entry-1.5; target = entry+3.
                reference = {"target": target, "stop": stop, "stop_open_gap": 95., "time_64_bars": 100., "terminal_liquidation": 100.}[reason]
                qty = min(1000/(entry*(1+fee/10000)), 10/1.5)
                slipped_exit = reference*(1-slip/10000)
                net = qty*(slipped_exit-entry)-qty*entry*fee/10000-qty*slipped_exit*fee/10000
                for field, expected in (("entry_reference", 100.), ("entry_slipped", entry), ("quantity", qty),
                                        ("stop", stop), ("target", target), ("exit_reference", reference),
                                        ("exit_slipped", slipped_exit), ("net_pnl", net)):
                    self.assertAlmostEqual(trade[field], expected, places=9)
                self.assertAlmostEqual(plain["net_pnl_usdt"], net, places=7)
                pd.testing.assert_frame_equal(frame, before); np.testing.assert_array_equal(signals, original_signals)
                self.assertIsNone(sys.gettrace()); json.dumps(observed, allow_nan=False)

    def test_macro_identity_and_cost_denial_observed_without_execution_change(self):
        f = signal_frame(minute_fixture()); f.loc[116, "h4_up"] = 0
        signals = research.signal_for(f, config())
        observed = observe_backtest(research.backtest, f, signals, fee_bps=25, slip_bps=15, risk_variant=0, index_offset=1000)
        self.assertEqual(observed["metrics"], research.backtest(f, signals, fee_bps=25, slip_bps=15, risk_variant=0))
        event = observed["price_events"][0]
        self.assertEqual(event["bar_index"], 1116); self.assertEqual(event["admission"], "signal_denied")
        self.assertEqual(event["denial_fields"], ["h4_up"])
        self.assertEqual(event["setup"]["lagged_macro_h4_index"], 6)
        self.assertEqual(event["cost_inputs"]["screen_fee_bps"], 25)

    def test_real_macro_fill_captures_original_decision_identity_and_next_open_gap(self):
        f = signal_frame(minute_fixture()); f.loc[117, ["open", "high", "low", "close"]] = [110., 112., 105., 111.]
        signals = research.signal_for(f, config())
        observed = observe_backtest(research.backtest, f, signals, fee_bps=25, slip_bps=15, risk_variant=0)
        trade = observed["trades"][0]
        self.assertEqual(trade["decision"]["bar_index"], 116); self.assertEqual(trade["fill"]["bar_index"], 117)
        self.assertEqual(trade["entry_reference"], 110.)
        self.assertEqual(trade["decision"]["setup"]["lagged_macro_break_high"], 100.)
        self.assertEqual(observed["price_events"][0]["admission"], "scheduled_next_open")
        self.assertEqual(observed["metrics"], research.backtest(f, signals, fee_bps=25, slip_bps=15, risk_variant=0))

    def test_existing_trace_and_unbound_code_fail_closed(self):
        frame, signals = self.hand("target")
        trace = lambda frame, event, arg: None
        try:
            sys.settrace(trace)
            with self.assertRaises(ValueError): observe_backtest(research.backtest, frame, signals, fee_bps=10, slip_bps=5, risk_variant=0)
            self.assertIs(sys.gettrace(), trace)
        finally: sys.settrace(None)
        with self.assertRaises((ValueError, StopIteration)):
            observe_backtest(lambda *a, **k: {}, frame, signals, fee_bps=10, slip_bps=5, risk_variant=0)

    def test_exception_restores_trace_and_does_not_mask_engine_error(self):
        frame, signals = self.hand("target")
        with self.assertRaises(research.CompositeResearchError):
            observe_backtest(research.backtest, frame, signals[:-1], fee_bps=10, slip_bps=5, risk_variant=0)
        self.assertIsNone(sys.gettrace())

    def test_multiple_trips_and_zero_activity_capture_complete_counts(self):
        frame, signals = self.hand("target"); signals[3] = True
        observed = observe_backtest(research.backtest, frame, signals, fee_bps=10, slip_bps=5, risk_variant=0)
        self.assertEqual(len(observed["trades"]), 2)
        self.assertEqual(observed["metrics"], research.backtest(frame, signals, fee_bps=10, slip_bps=5, risk_variant=0))
        signals[:] = False
        self.assertEqual(observe_backtest(research.backtest, frame, signals, fee_bps=10, slip_bps=5, risk_variant=0)["trades"], [])

    def test_rejected_actual_entry_stop_is_recorded_without_stale_pending_identity(self):
        frame, signals = self.hand("target"); frame.loc[0, "atr"] = 100.
        observed = observe_backtest(research.backtest, frame, signals, fee_bps=25, slip_bps=15, risk_variant=0)
        self.assertEqual(observed["metrics"], research.backtest(frame, signals, fee_bps=25, slip_bps=15, risk_variant=0))
        self.assertEqual(observed["trades"], [])
        self.assertEqual(observed["entry_attempts"][0]["disposition"], "invalid_stop_or_target")
        self.assertIsNone(observed["unfilled_pending_decision"])


if __name__ == "__main__":
    unittest.main()
