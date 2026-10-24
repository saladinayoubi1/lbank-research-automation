"""Synthetic-only causal Volatility-Compression Breakout v13 tests."""
from copy import deepcopy
import unittest

import numpy as np
import pandas as pd

import nexus_v13_compression_detector as detector


def example():
    htimes=pd.date_range("2026-10-13T00:00:00Z",periods=87,freq="1h")
    h=pd.DataFrame({"timestamp":htimes,"open":100.,"high":102.,
                    "low":98.,"close":100.})
    quiet=(htimes>=pd.Timestamp("2026-10-16T04:00:00Z")) & (
           htimes<=pd.Timestamp("2026-10-16T09:00:00Z"))
    h.loc[quiet,["high","low"]]=[100.5,99.5]
    h.loc[htimes>=pd.Timestamp("2026-10-16T10:00:00Z"),["high","low"]]=[105.,99.]
    mtimes=pd.date_range("2026-10-16T09:00:00Z",periods=8,freq="15min")
    m=pd.DataFrame({"timestamp":mtimes,"open":100.,"high":100.3,
                    "low":99.7,"close":100.})
    m.loc[4,["open","high","low","close"]]=[100.,101.2,99.9,101.]
    return m,h


def features(m,h,*,last=None,diagnostics=None):
    cutoff=last if last is not None else m["timestamp"].iloc[-1]+pd.Timedelta(minutes=15)
    return detector.build_v13_closed_compression_features(
        m,h,last_completed_at=cutoff,diagnostics=diagnostics)


class V13ForwardCausalitySyntheticTests(unittest.TestCase):
    def test_first_future_closed_break_correct_bar(self):
        m,h=example()
        diag=[]
        out=features(m,h,diagnostics=diag)
        self.assertEqual(np.flatnonzero(out["v13_first_close_break_event"]).tolist(),[4])
        self.assertEqual(diag[0]["action"],"first_close_break_consumed_even_if_downstream_denied")
        self.assertEqual(out.iloc[4]["v13_upper_band"],100.5)
        self.assertEqual(out.iloc[4]["v13_lower_band"],99.5)
        self.assertAlmostEqual(out.iloc[4]["v13_compression_ratio"],0.25)

    def test_finished_hour_limit_excludes_breakout_hour(self):
        m,h=example()
        out=features(m,h)
        at=out.iloc[4]
        self.assertEqual(at["v13_band_start_utc"],pd.Timestamp("2026-10-16T04:00:00Z"))
        self.assertEqual(at["v13_band_end_utc"],pd.Timestamp("2026-10-16T09:00:00Z"))
        self.assertEqual(at["v13_completed_hour_count"],82)

    def test_both_timeframe_tails_cannot_rewrite_past(self):
        m,h=example()
        baseline=features(m,h)
        mm=m.copy(deep=True);hh=h.copy(deep=True)
        mm.loc[5:,["open","high","low","close"]]*=1.4
        hh.loc[hh["timestamp"]>=pd.Timestamp("2026-10-16T10:00:00Z"),
               ["open","high","low","close"]]*=1.6
        after=features(mm,hh)
        for key in baseline:
            with self.subTest(key=key):
                a=baseline[key].iloc[:5].reset_index(drop=True)
                b=after[key].iloc[:5].reset_index(drop=True)
                pd.testing.assert_series_equal(a,b,check_names=False)

    def test_pre_cutoff_bars_never_score_even_if_price_breaks(self):
        m,h=example()
        m["timestamp"]-=pd.Timedelta(days=1)
        h["timestamp"]-=pd.Timedelta(days=1)
        out=features(m,h)
        self.assertFalse(out["v13_first_close_break_event"].any())
        self.assertFalse(out["v13_eligible"].any())

    def test_after_locked_prospective_window_never_scores(self):
        m,h=example()
        m["timestamp"]+=pd.Timedelta(days=61)
        h["timestamp"]+=pd.Timedelta(days=61)
        out=features(m,h)
        self.assertFalse(out["v13_first_close_break_event"].any())
        self.assertFalse(out["v13_eligible"].any())

    def test_no_bar_without_known_previous_close_can_break(self):
        m,h=example()
        only=m.iloc[4:5].reset_index(drop=True)
        out=features(only,h)
        self.assertFalse(out["v13_first_close_break_event"].any())

    def test_requires_preceding_completed_hour_for_true_range(self):
        m,h=example()
        cutoff=pd.Timestamp("2026-10-16T10:15:00Z")
        h=h.iloc[-54:].reset_index(drop=True)
        out=features(m.iloc[:5],h,last=cutoff)
        self.assertFalse(out["v13_first_close_break_event"].any())

    def test_no_15m_forming_candle_may_be_used(self):
        m,h=example()
        with self.assertRaisesRegex(ValueError,"unclosed"):
            features(m,h,last=pd.Timestamp("2026-10-16T10:55:00Z"))

    def test_unclosed_hour_cannot_create_earlier_band_break(self):
        m,h=example()
        h.loc[h["timestamp"]==pd.Timestamp("2026-10-16T10:00:00Z"),
              "high"]=900.
        out=features(m,h)
        self.assertEqual(out.loc[4,"v13_upper_band"],100.5)
        self.assertTrue(out.loc[4,"v13_first_close_break_event"])

    def test_gapped_hourly_fail_closed(self):
        m,h=example()
        with self.assertRaisesRegex(ValueError,"gaps"):
            features(m,h.drop(index=22).reset_index(drop=True))

    def test_gapped_15m_fail_closed(self):
        m,h=example()
        with self.assertRaisesRegex(ValueError,"gaps"):
            features(m.drop(index=2).reset_index(drop=True),h)

    def test_naive_timestamps_fail_closed(self):
        m,h=example()
        m["timestamp"]=m["timestamp"].dt.tz_localize(None)
        with self.assertRaisesRegex(ValueError,"timezone"):
            features(m,h,last=pd.Timestamp("2026-10-16T11:00:00Z"))

    def test_wrong_ohlc_fails_closed(self):
        m,h=example()
        m.loc[4,"high"]=100.1
        with self.assertRaisesRegex(ValueError,"inconsistent"):
            features(m,h)

    def test_zero_or_infinite_price_fails_closed(self):
        for value in (0.,np.inf,np.nan):
            m,h=example()
            h.loc[30,"close"]=value
            with self.subTest(value=value),self.assertRaises(ValueError):
                features(m,h)

    def test_exact_compression_threshold_and_fixed_reference(self):
        m,h=example()
        # Median 1h true ranges: 6 recent = 1.0, previous 48 = 4.0
        # Manipulate earlier ref bands to shrink denominator to 1.5;
        # a 1/1.5 ratio = 0.6666 exceeds the frozen 0.65.
        h.loc[:75,["high","low"]]=[100.75,99.25]
        out=features(m,h)
        self.assertFalse(out["v13_compressed"].iloc[4])
        self.assertFalse(out["v13_first_close_break_event"].iloc[4])

    def test_break_must_be_close_not_intrabar_high(self):
        m,h=example()
        m.loc[4,["open","high","low","close"]]=[100.,102.,99.9,100.]
        out=features(m,h)
        self.assertFalse(out["v13_first_close_break_event"].any())

    def test_no_pivot_or_old_structural_components(self):
        self.assertTrue(detector.RESEARCH_ONLY)
        self.assertFalse(detector.LIVE_ENABLED)
        self.assertFalse(detector.ORDER_EXECUTION_ENABLED)
        self.assertFalse(detector.AUTO_DEMO)
        self.assertFalse(detector.FACTORY_REGISTERED)
        self.assertEqual(detector.MARKET_EVALUATIONS,0)
        o=features(*example())
        self.assertFalse(any("spring" in c or "elliott" in c or "abc" in c for c in o.columns))


if __name__=="__main__":
    unittest.main(verbosity=2)
