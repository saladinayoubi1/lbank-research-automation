"""Clock-volume causality and additive factory integration; no market backtest."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

import nexus_composite_strategy_research as research
import nexus_mechanism_factory as factory
from nexus_causal_slot_volume_features import (
    FEATURE_COLUMNS, build_lagged_utc_slot_volume_features,
)

ROOT = Path(__file__).resolve().parents[1]
IDENT = "factory_utc_slot_volume_breakout"


def inputs(n=1000):
    times = pd.Series(pd.date_range("2026-09-01", periods=n, freq="15min", tz="UTC"))
    slot = np.arange(n) % 96
    day = np.arange(n) // 96
    volume = pd.Series(10.0 + slot * 0.25 + day * 0.2)
    return times, volume


class SlotVolumeFeatureTests(unittest.TestCase):
    def test_time_indexed_scalar_reference_and_warmup(self):
        times, volume = inputs()
        actual = build_lagged_utc_slot_volume_features(times, volume)
        indexed = pd.Series(volume.to_numpy(), index=pd.DatetimeIndex(times))
        self.assertTrue(actual.iloc[:673].isna().all().all())
        for i in (673, 731, 900, 999):
            event = times.iloc[i] - pd.Timedelta(minutes=15)
            prior = np.array([indexed.loc[event - pd.Timedelta(days=k)] for k in range(1, 8)])
            expected = [prior.mean(), indexed.loc[event] / prior.mean(),
                        prior.std(ddof=0) / prior.mean()]
            np.testing.assert_allclose(actual.iloc[i].to_numpy(), expected, rtol=1e-13)

    def test_current_and_future_volume_cannot_change_context(self):
        times, volume = inputs()
        one = build_lagged_utc_slot_volume_features(times, volume)
        changed = volume.copy()
        changed.iloc[780:] *= np.linspace(3.0, 9.0, len(changed) - 780)
        two = build_lagged_utc_slot_volume_features(times, changed)
        pd.testing.assert_frame_equal(one.iloc[:781], two.iloc[:781])
        self.assertNotEqual(one.iloc[781, 1], two.iloc[781, 1])

    def test_event_is_lagged_and_excluded_from_its_baseline(self):
        times, volume = inputs()
        before = build_lagged_utc_slot_volume_features(times, volume)
        changed = volume.copy()
        changed.iloc[780] *= 3.0
        after = build_lagged_utc_slot_volume_features(times, changed)
        np.testing.assert_allclose(before.iloc[780], after.iloc[780])
        self.assertAlmostEqual(before.iloc[781, 0], after.iloc[781, 0])
        self.assertAlmostEqual(before.iloc[781, 2], after.iloc[781, 2])
        self.assertAlmostEqual(after.iloc[781, 1], before.iloc[781, 1] * 3.0)

    def test_same_clock_history_is_distinct_from_contiguous_relative_volume(self):
        times, volume = inputs()
        changed = volume.copy()
        changed.iloc[900 - 1 - 7 * 96] *= 2.0
        old_local = volume / volume.shift(1).rolling(20, min_periods=20).mean()
        new_local = changed / changed.shift(1).rolling(20, min_periods=20).mean()
        self.assertEqual(old_local.shift(1).iloc[900], new_local.shift(1).iloc[900])
        one = build_lagged_utc_slot_volume_features(times, volume)
        two = build_lagged_utc_slot_volume_features(times, changed)
        self.assertNotEqual(one.iloc[900, 1], two.iloc[900, 1])

    def test_volume_units_do_not_change_ratio_or_dispersion(self):
        times, volume = inputs()
        one = build_lagged_utc_slot_volume_features(times, volume)
        two = build_lagged_utc_slot_volume_features(times, volume * 7.0)
        np.testing.assert_allclose(one.iloc[:, 1:], two.iloc[:, 1:], equal_nan=True)

    def test_zero_volume_and_short_history_are_unavailable(self):
        times, volume = inputs()
        zero = build_lagged_utc_slot_volume_features(times, volume * 0.0)
        self.assertTrue(zero.iloc[:, 1:].isna().all().all())
        short = build_lagged_utc_slot_volume_features(times.iloc[:100], volume.iloc[:100])
        self.assertTrue(short.isna().all().all())
        empty = build_lagged_utc_slot_volume_features(times.iloc[:0], volume.iloc[:0])
        self.assertEqual(tuple(empty.columns), FEATURE_COLUMNS)
        self.assertTrue(empty.empty)

    def test_equivalent_timezones_and_dst_map_to_the_same_utc_slots(self):
        times = pd.Series(pd.date_range("2026-10-25", periods=1100, freq="15min", tz="UTC"))
        volume = inputs(1100)[1]
        expected = build_lagged_utc_slot_volume_features(times, volume)
        for zone in ("Asia/Tehran", "Europe/London", "America/New_York"):
            with self.subTest(zone=zone):
                actual = build_lagged_utc_slot_volume_features(times.dt.tz_convert(zone), volume)
                pd.testing.assert_frame_equal(expected, actual)

    def test_bad_grids_volumes_and_indices_fail_closed(self):
        times, volume = inputs()
        variants = []
        gap = times.copy(); gap.iloc[500:] += pd.Timedelta(minutes=15); variants.append(gap)
        duplicate = times.copy(); duplicate.iloc[500] = duplicate.iloc[499]; variants.append(duplicate)
        variants.extend((times.iloc[::-1], times + pd.Timedelta(seconds=1), times.dt.tz_localize(None)))
        for bad in variants:
            with self.subTest(kind=str(bad.dtype)):
                with self.assertRaises(ValueError):
                    build_lagged_utc_slot_volume_features(bad, volume)
        for value in (-1.0, np.inf, np.nan):
            bad = volume.copy(); bad.iloc[400] = value
            with self.subTest(volume=value), self.assertRaises(ValueError):
                build_lagged_utc_slot_volume_features(times, bad)
        with self.assertRaises(ValueError):
            build_lagged_utc_slot_volume_features(times, volume.set_axis(np.arange(len(volume)) + 1))


class SlotVolumeFactoryTests(unittest.TestCase):
    def test_all_previous_specs_order_and_configs_are_preserved(self):
        prior = json.loads((ROOT/"tests/fixtures/utc_slot_v7_prior_generations.json").read_text())
        self.assertEqual({k:research.FACTORY_SPECS[k] for k in prior["factory_specs"]}, prior["factory_specs"])
        earlier = [m for m in research.ALL_MECHANISMS if m not in (IDENT, "factory_causal_bullish_butterfly", "factory_causal_elliott_wave12_breakout", "factory_causal_4h_break_1h_retest_cost_breakout")]
        self.assertEqual(earlier, prior["all_mechanisms"])
        old_configs = [c for c in research.FRONTIER_CONFIGS if c["mechanism"] not in (IDENT, "factory_causal_bullish_butterfly", "factory_causal_elliott_wave12_breakout", "factory_causal_4h_break_1h_retest_cost_breakout")]
        self.assertEqual(old_configs, prior["frontier_configs"])
        self.assertEqual(set(research.SLOT_VOLUME_EXTENSION_SPECS), {IDENT})
        self.assertEqual(len(research.FACTORY_SPECS), 95)

    def test_terminal_ledger_routes_only_the_new_candidate(self):
        ledger = json.loads((ROOT/"tests/fixtures/utc_slot_v7_terminal_ledger.json").read_text())
        before = deepcopy(ledger)
        choices = research._frontier_configs_to_screen(ledger)
        self.assertEqual([c["mechanism"] for c in choices], [IDENT])
        self.assertEqual(ledger, before)
        self.assertNotIn(IDENT, ledger["mechanisms_evaluated"])
        self.assertNotIn(IDENT, ledger["frontier_screened_mechanisms"])

    def test_every_previous_frontier_contract_precedes_the_v7_tier(self):
        terminal = json.loads((ROOT/"tests/fixtures/utc_slot_v7_terminal_ledger.json").read_text())
        for mechanism in research.FRONTIER_MECHANISMS:
            if mechanism in (IDENT, "factory_causal_bullish_butterfly", "factory_causal_elliott_wave12_breakout", "factory_causal_4h_break_1h_retest_cost_breakout"):
                continue
            with self.subTest(mechanism=mechanism):
                ledger = deepcopy(terminal)
                ledger["mechanisms_evaluated"] = [
                    name for name in ledger["mechanisms_evaluated"] if name != mechanism
                ]
                ledger["frontier_screened_mechanisms"] = [
                    name for name in ledger["frontier_screened_mechanisms"] if name != mechanism
                ]
                choices = research._frontier_configs_to_screen(ledger)
                self.assertEqual([row["mechanism"] for row in choices], [mechanism])

    def test_confirmed_signal_and_unavailable_history_denial(self):
        specs = research.SLOT_VOLUME_EXTENSION_SPECS
        frame = pd.DataFrame({
            "h4_up":[1,1,1,1,1], "h1_vol_ok":[1,1,1,1,1],
            "lagged_utc_slot_volume_ratio_7d":[1.6,np.nan,1.6,1.6,1.6],
            "lagged_utc_slot_volume_cv_7d":[0.2,0.2,0.9,0.2,0.2],
            "close":[102.0,102.0,102.0,100.0,102.0], "prior_hi":[101.0]*5,
            "open":[100.0]*5, "close_location":[0.8,0.8,0.8,0.8,0.6],
        })
        actual = factory.factory_signal(frame, IDENT, specs=specs,
            expected_contract_digest=specs[IDENT]["contract_digest"])
        self.assertEqual(actual.tolist(), [True,False,False,False,False])
        with self.assertRaises(factory.MechanismFactoryError):
            factory.factory_signal(frame, IDENT, specs=specs, expected_contract_digest="0"*64)

    def test_contract_rejects_authority_and_unreviewed_features(self):
        raw = json.loads((ROOT/"research/mechanism_factory_v7.json").read_text())
        self.assertTrue(raw["no_minimum_trade_count_gate"])
        self.assertFalse(raw["auto_demo_promotion"])
        self.assertFalse(raw["live_trading_authority"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"contract.json"
            variants = []
            live = deepcopy(raw); live["live_trading_authority"] = True; variants.append(live)
            unknown = deepcopy(raw)
            unknown["candidates"][0]["context"][2]["field"] = "future_volume"
            variants.append(unknown)
            for value in variants:
                path.write_text(json.dumps(value))
                with self.assertRaises(factory.MechanismFactoryError):
                    factory.load_factory_contract(path)

    def test_feature_helper_is_wired_into_closed_candle_pipeline(self):
        times, volume = inputs(1104)
        close = 100.0 + np.arange(len(times)) * 0.001
        minute = pd.DataFrame({"timestamp":times,"open":close-0.001,"high":close+0.05,
            "low":close-0.05,"close":close,"volume":volume})
        indexed = minute.set_index("timestamp")
        agg = {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
        frames = {"minute15":minute,
            "hour1":indexed.resample("1h").agg(agg).reset_index(),
            "hour4":indexed.resample("4h").agg(agg).reset_index()}
        features = research.build_features(frames)
        expected = build_lagged_utc_slot_volume_features(times, volume)
        for column in FEATURE_COLUMNS:
            np.testing.assert_allclose(features[column], expected[column], equal_nan=True)


if __name__ == "__main__":
    unittest.main()

