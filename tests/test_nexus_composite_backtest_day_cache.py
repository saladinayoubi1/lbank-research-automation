"""Frozen scalar-reference regression for calendar-day backtest optimization."""
import json
from pathlib import Path
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from nexus_composite_strategy_research import _decision_day_keys, backtest


def loss_pause_frame(mode):
    dates = pd.date_range("2025-01-31 20:00:00", periods=48, freq="15min", tz="UTC")
    if mode == "tehran":
        dates = dates.tz_convert("Asia/Tehran")
    elif mode == "naive":
        dates = dates.tz_localize(None)
    elif mode == "strings":
        dates = [value.isoformat() for value in dates]
    elif mode == "mixed_objects":
        dates = pd.Series([
            value if i % 2 == 0 else value.tz_convert("Asia/Tehran")
            for i, value in enumerate(dates)
        ], dtype=object)
    prices = np.full(48, 100.0)
    prices[[2, 10, 18, 26, 34, 42]] = 10.0
    frame = pd.DataFrame({
        "decision_at": dates, "open": prices, "high": prices + .2,
        "low": prices - .05, "close": prices, "atr": np.ones(48),
    })
    signals = np.zeros(48, dtype=bool)
    signals[[0, 8, 16, 24, 32, 40]] = True
    return frame, signals


class CalendarDayBacktestRegression(unittest.TestCase):
    def test_all_metrics_match_frozen_original_scalar_backtest(self):
        fixture = json.loads((Path(__file__).parent / "fixtures" /
                              "nexus_backtest_scalar_day_floor_v1.json").read_text())
        self.assertEqual(fixture["reference_source_sha"],
                         "8899ec6bec4927fc39795f2867be91e2431178c6")
        self.assertEqual(len(fixture["cases"]), 20)
        for case in fixture["cases"]:
            with self.subTest(mode=case["timestamp_mode"], risk=case["risk_variant"],
                              fee=case["fee_bps"]):
                frame, signals = loss_pause_frame(case["timestamp_mode"])
                actual = backtest(frame, signals, fee_bps=case["fee_bps"],
                                  slip_bps=case["slippage_bps"], risk_variant=case["risk_variant"])
                self.assertEqual(actual, case["expected"])
                self.assertTrue(actual["halted_on_drawdown"])

    def test_timezone_and_dst_days_equal_scalar_calendar_days(self):
        dates = pd.date_range("2025-11-01 20:00:00", periods=64, freq="15min", tz="UTC")
        inputs = [pd.Series(dates), pd.Series(dates.tz_convert("America/New_York")),
                  pd.Series(dates.tz_convert("Asia/Tehran")), pd.Series(dates.tz_localize(None)),
                  pd.Series([value.isoformat() for value in dates]),
                  pd.Series([value if i % 2 else value.tz_convert("Asia/Tehran")
                             for i, value in enumerate(dates)], dtype=object)]
        for i, values in enumerate(inputs):
            with self.subTest(timestamp_form=i):
                expected = [pd.Timestamp(value).floor("D") for value in values]
                self.assertEqual(list(_decision_day_keys(values)), expected)

    def test_canonical_datetime_path_never_calls_scalar_timestamp_floor(self):
        frame, signals = loss_pause_frame("utc")
        with mock.patch.object(pd.Timestamp, "floor", side_effect=AssertionError("scalar floor")):
            result = backtest(frame, signals, fee_bps=10., slip_bps=5., risk_variant=0)
        self.assertEqual(result["closed_round_trips"], 2)

    def test_empty_frame_retains_zero_trade_result_without_timestamp_column(self):
        result = backtest(pd.DataFrame(), np.array([], dtype=bool),
                          fee_bps=10., slip_bps=5., risk_variant=0)
        self.assertEqual(result["closed_round_trips"], 0)
        self.assertEqual(result["net_pnl_usdt"], 0.)
        self.assertEqual(result["net_return_pct"], 0.)
        self.assertEqual(result["max_drawdown_pct"], 0.)
        self.assertFalse(result["halted_on_drawdown"])


if __name__ == "__main__":
    unittest.main()
