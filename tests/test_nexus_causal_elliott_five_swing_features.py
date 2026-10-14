"""Synthetic closed bars, no market replay or recursive Elliott claim."""
import unittest

import numpy as np
import pandas as pd

import nexus_causal_elliott_five_swing_features as candidate


def bars(n=100, *, pad=.1, breakout=True):
    turns = {0: 103, 6: 100, 14: 106, 22: 103, 30: 112, 38: 108, 46: 115, 54: 107}
    if breakout:
        turns.update({60: 116, n - 1: 116 + (n - 61) * .2})
        close = np.interp(np.arange(n), list(turns), list(turns.values()))
    else:
        close = np.interp(np.arange(n), list(turns), list(turns.values()))
        close[55:] = np.minimum(107 + np.arange(1, n - 54) * .2, 114)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01 00:15", periods=n, freq="15min", tz="UTC"),
        "open": close - .05, "high": close + pad, "low": close - pad, "close": close,
    })


def features(frame, diagnostics=None):
    return candidate.build_lagged_elliott_five_swing_features(frame, diagnostics=diagnostics)


class ClosedOHLCTests(unittest.TestCase):
    def test_expected_confirmations_and_first_fresh_break(self):
        trace = []
        out = features(bars(), trace)
        accepted = [(d["pivot_index"], d["decision_index"]) for d in trace if d["action"] == "pivot_accepted"]
        self.assertEqual(accepted[:7], [(i, i + 3) for i in (6, 14, 22, 30, 38, 46, 54)])
        self.assertFalse(out["lagged_elliott5_active"].iloc[:58].any())
        self.assertTrue(out["lagged_elliott5_active"].iloc[58:61].all())
        self.assertEqual(out["elliott5_close_breakout_event"].to_numpy().nonzero()[0].tolist(), [60])
        self.assertEqual(out["lagged_elliott5_origin_index"].iloc[60], 6)
        self.assertEqual(out["lagged_elliott5_wave1_index"].iloc[60], 46)
        self.assertEqual(out["lagged_elliott5_wave2_index"].iloc[60], 54)
        self.assertEqual(out["lagged_elliott5_confirmed_at"].iloc[60], 57)

    def test_every_prefix_matches_full_outputs(self):
        frame = bars(n=75)
        full = features(frame)
        for stop in range(1, len(frame) + 1):
            prefix = features(frame.iloc[:stop])
            for name in full:
                pd.testing.assert_series_equal(prefix[name], full[name].iloc[:stop])

    def test_future_valid_tail_does_not_change_previous_decisions(self):
        frame = bars()
        changed = frame.copy()
        changed.loc[61:, ["open", "high", "low", "close"]] *= 3
        before, after = features(frame), features(changed)
        for name in before:
            pd.testing.assert_series_equal(before[name].iloc[:61], after[name].iloc[:61])

    def test_confirmation_bar_cannot_emit_backdated_signal(self):
        frame = bars()
        frame.loc[57:60, "close"] = [116, 117, 118, 119]
        frame.loc[57:60, "open"] = frame.loc[57:60, "close"] - .05
        frame.loc[57:60, "high"] = frame.loc[57:60, "close"] + .1
        frame.loc[57:60, "low"] = frame.loc[57:60, "close"] - .1
        out = features(frame.iloc[:61])
        self.assertFalse(out["elliott5_close_breakout_event"].any())
        self.assertFalse(out["lagged_elliott5_active"].iloc[57])
        self.assertTrue(out["lagged_elliott5_active"].iloc[58])

    def test_wick_alone_is_not_a_close_breakout(self):
        frame = bars()
        frame.loc[59, "high"] = 117
        out = features(frame)
        self.assertFalse(out["elliott5_close_breakout_event"].iloc[59])
        self.assertTrue(out["elliott5_close_breakout_event"].iloc[60])

    def test_first_bar_after_confirmation_can_emit(self):
        frame = bars()
        frame.loc[58:60, "close"] = [116, 117, 118]
        frame.loc[58:60, "open"] = frame.loc[58:60, "close"] - .05
        frame.loc[58:60, "high"] = frame.loc[58:60, "close"] + .1
        frame.loc[58:60, "low"] = frame.loc[58:60, "close"] - .1
        out = features(frame.iloc[:61])
        self.assertEqual(out["elliott5_close_breakout_event"].to_numpy().nonzero()[0].tolist(), [58])

    def test_more_extreme_same_kind_correction_changes_only_future_state(self):
        frame = bars()
        values = [108, 109, 110, 110, 110, 110, 109, 108, 107.5, 106.5, 108, 109, 110, 116]
        frame.loc[55:68, "close"] = values
        frame.loc[55:68, "open"] = frame.loc[55:68, "close"] - .05
        frame.loc[55:68, "high"] = frame.loc[55:68, "close"] + .1
        frame.loc[55:68, "low"] = frame.loc[55:68, "close"] - .1
        out = features(frame.iloc[:69])
        self.assertTrue(out["elliott5_invalidated"].iloc[64])
        self.assertFalse(out["lagged_elliott5_active"].iloc[67])
        self.assertTrue(out["elliott5_close_breakout_event"].iloc[68])
        self.assertEqual(out["lagged_elliott5_wave2_index"].iloc[68], 64)
        self.assertEqual(out["lagged_elliott5_confirmed_at"].iloc[68], 67)

    def test_weaker_same_kind_low_does_not_replace_or_disarm(self):
        frame = bars()
        values = [108, 109, 110, 110, 110, 110, 109.5, 109, 108, 107.5, 109, 110, 111, 116]
        frame.loc[55:68, "close"] = values
        frame.loc[55:68, "open"] = frame.loc[55:68, "close"] - .05
        frame.loc[55:68, "high"] = frame.loc[55:68, "close"] + .1
        frame.loc[55:68, "low"] = frame.loc[55:68, "close"] - .1
        trace = []
        out = features(frame.iloc[:69], trace)
        self.assertTrue(out["elliott5_close_breakout_event"].iloc[68])
        self.assertEqual(out["lagged_elliott5_wave2_index"].iloc[68], 54)
        self.assertNotIn(64, [d["pivot_index"] for d in trace if d["action"] == "pivot_accepted"])

    def test_new_accepted_high_disarms_previous_shape_for_future_bars(self):
        frame = bars()
        values = [108, 109, 110, 111, 112, 112.5, 113, 112, 111, 110, 116]
        frame.loc[56:66, "close"] = values
        frame.loc[56:66, "open"] = frame.loc[56:66, "close"] - .05
        frame.loc[56:66, "high"] = frame.loc[56:66, "close"] + .1
        frame.loc[56:66, "low"] = frame.loc[56:66, "close"] - .1
        out = features(frame.iloc[:67])
        self.assertTrue(out["lagged_elliott5_active"].iloc[65])
        self.assertFalse(out["lagged_elliott5_active"].iloc[66])
        self.assertFalse(out["elliott5_close_breakout_event"].any())

    def test_origin_touch_wins_over_same_bar_breakout(self):
        frame = bars()
        frame.loc[60, "low"] = frame.loc[6, "low"]
        trace = []
        out = features(frame, trace)
        self.assertTrue(out["lagged_elliott5_active"].iloc[60])
        self.assertTrue(out["elliott5_invalidated"].iloc[60])
        self.assertFalse(out["elliott5_close_breakout_event"].any())
        self.assertEqual([d["reason"] for d in trace if d["action"] == "invalidated"], ["origin_breach"])

    def test_new_raw_correction_low_disarms_before_confirmation(self):
        frame = bars()
        frame.loc[59, "low"] = 106.8
        trace = []
        out = features(frame, trace)
        self.assertTrue(out["elliott5_invalidated"].iloc[59])
        self.assertFalse(out["lagged_elliott5_active"].iloc[60])
        self.assertFalse(out["elliott5_close_breakout_event"].any())
        self.assertEqual([d["reason"] for d in trace if d["action"] == "invalidated"], ["correction_low_breach"])

    def test_expiry_is_after_the_fixed_thirty_two_bar_age(self):
        out = features(bars(breakout=False))
        self.assertTrue(out["lagged_elliott5_active"].iloc[89])
        self.assertFalse(out["elliott5_expired"].iloc[89])
        self.assertTrue(out["elliott5_expired"].iloc[90])
        self.assertFalse(out["lagged_elliott5_active"].iloc[91])
        self.assertFalse(out["elliott5_close_breakout_event"].any())

    def test_tied_pivot_extremum_is_rejected(self):
        frame = bars()
        frame.loc[45, "high"] = frame.loc[46, "high"]
        out = features(frame)
        self.assertFalse(out["lagged_elliott5_active"].any())

    def test_dual_extremum_cannot_supply_a_pivot(self):
        frame = bars()
        frame.loc[46, "low"] = 105
        trace = []
        out = features(frame, trace)
        self.assertFalse(out["lagged_elliott5_active"].any())
        self.assertNotIn(46, [d["pivot_index"] for d in trace if d["action"] == "pivot_accepted"])

    def assert_raw_path_rejected(self, index, high, low, expected):
        frame = bars()
        frame.loc[index, ["high", "low"]] = [high, low]
        trace = []
        out = features(frame, trace)
        self.assertFalse(out["elliott5_close_breakout_event"].any())
        accepted = [d["pivot_index"] for d in trace if d["action"] == "pivot_accepted"]
        self.assertEqual(accepted[:7], [6, 14, 22, 30, 38, 46, 54])
        self.assertNotIn(index, accepted)
        self.assertEqual([d["reason"] for d in trace if d["action"] == "path_rejected"], [expected])
        self.assertTrue(out["elliott5_path_rejected"].iloc[57])

    def test_origin_breach_hidden_in_unselected_outside_bar(self):
        self.assert_raw_path_rejected(18, 120, 99, "origin_path_breach")

    def test_second_low_must_bound_the_whole_observed_path(self):
        self.assert_raw_path_rejected(18, 120, 102.5, "second_low_not_path_minimum")

    def test_nonpivot_fourth_path_overlap_is_rejected(self):
        self.assert_raw_path_rejected(42, 125, 105, "fourth_path_overlap")

    def test_parent_correction_must_bound_the_whole_observed_path(self):
        self.assert_raw_path_rejected(50, 118, 106, "correction_low_not_path_minimum")

    def test_selected_peak_must_be_actual_observed_path_maximum(self):
        self.assert_raw_path_rejected(10, 108, 100.2, "swing_high_not_path_maximum")

    def test_cost_denial_still_consumes_identity_before_later_recross(self):
        frame = bars()
        values = [116, 116, 116, 113, 112, 110, 106.5, 109, 110, 111, 116, 117]
        frame.loc[60:71, "close"] = values
        frame.loc[60:71, "open"] = frame.loc[60:71, "close"] - .05
        frame.loc[60:71, "high"] = frame.loc[60:71, "close"] + .1
        frame.loc[60:71, "low"] = frame.loc[60:71, "close"] - .1
        trace = []
        out = features(frame.iloc[:72], trace)
        self.assertEqual(out["elliott5_close_breakout_event"].to_numpy().nonzero()[0].tolist(), [60])
        self.assertFalse(out["elliott5_cost_feasible"].iloc[60])
        self.assertTrue(any(d["action"] == "consumed_identity" and d["identity"] == [6, 46] for d in trace))
        self.assertFalse(out["lagged_elliott5_active"].iloc[70])

    def test_cost_screen_uses_previous_atr_and_fixed_existing_stress_rates(self):
        frame = bars(pad=.5)
        # A large current range must not leak into the decision ATR.
        frame.loc[60, "high"] = 120
        trace = []
        out = features(frame, trace)
        event = next(d for d in trace if d["action"] == "price_event_consumed")
        screen = event["cost_screen"]
        self.assertAlmostEqual(out["elliott5_decision_atr"].iloc[60], 1)
        self.assertAlmostEqual(screen["span"], 16)
        self.assertEqual((screen["fee"], screen["slip"]), (.0025, .0015))
        self.assertTrue(out["elliott5_cost_feasible"].iloc[60])
        self.assertGreater(out["elliott5_target_net"].iloc[60], 0)

    def test_timezone_aware_offsets_match_utc(self):
        frame = bars()
        offset = frame.copy()
        offset["timestamp"] = offset["timestamp"].dt.tz_convert("Asia/Tehran")
        first, second = features(frame), features(offset)
        for name in first:
            pd.testing.assert_series_equal(first[name], second[name])

    def test_naive_nat_duplicate_gap_and_unaligned_timestamps_rejected(self):
        frame = bars()
        variants = []
        naive = frame.copy(); naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
        variants.append(naive)
        for index, value in ((10, pd.NaT), (10, frame.loc[9, "timestamp"]),
                             (10, frame.loc[10, "timestamp"] + pd.Timedelta(minutes=1))):
            changed = frame.copy(); changed.loc[index, "timestamp"] = value
            variants.append(changed)
        variants.append(frame.drop(index=10))
        variants.append(frame.iloc[::-1])
        for changed in variants:
            with self.subTest(timestamp=str(changed["timestamp"].iloc[10])):
                with self.assertRaises(ValueError):
                    features(changed)

    def test_invalid_ohlc_or_missing_column_rejected(self):
        frame = bars()
        for column, value in (("close", np.nan), ("high", np.inf), ("low", 0),
                              ("high", 1), ("low", 200), ("open", "invalid")):
            changed = frame.copy()
            if isinstance(value, str):
                changed[column] = changed[column].astype(object)
            changed.loc[10, column] = value
            with self.subTest(column=column, value=value):
                with self.assertRaises(ValueError):
                    features(changed)
        with self.assertRaises(ValueError):
            features(frame.drop(columns="high"))

    def test_empty_input_and_nondefault_index_preserved(self):
        frame = bars()
        self.assertTrue(all(len(series) == 0 for series in features(frame.iloc[:0]).values()))
        frame.index = pd.Index(np.arange(100) * 7, name="row")
        out = features(frame)
        self.assertEqual(out["elliott5_trigger_index"].loc[420], 60)
        self.assertTrue(all(series.index.equals(frame.index) for series in out.values()))

    def test_research_only_boundary_and_input_unchanged(self):
        frame = bars()
        before = frame.copy(deep=True)
        features(frame)
        pd.testing.assert_frame_equal(before, frame)
        self.assertTrue(candidate.RESEARCH_ONLY)
        self.assertFalse(candidate.EXECUTION_INTEGRATED)
        self.assertFalse(candidate.COMPLETE_ELLIOTT_COUNT)


if __name__ == "__main__":
    unittest.main()
