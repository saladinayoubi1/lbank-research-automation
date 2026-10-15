"""Synthetic independent whole-archive higher-timeframe as-of QA unit tests."""
import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

SRC=Path(__file__).resolve().parents[1]/"docs"/"evidence"/"elliott-v14-asof-qa-20261015"
sys.path.insert(0,str(SRC))

from full_history_asof_qa import (
    FIELDS, independent_full_values, original_engine_asof, discrepancies,
)
from independent_higher_timeframe_qa import (
    independently_aggregate, validate_frame,
)
import nexus_composite_strategy_research as engine


def synthetic():
    n=2048
    timestamp=pd.date_range("2024-01-01",periods=n,freq="15min",tz="UTC")
    # Deterministic smooth but nonconstant path; no price-signal test.
    x=np.arange(n,dtype=float)
    mid=100+0.004*x+2*np.sin(x/31)+np.sin(x/8)/3
    f=pd.DataFrame({
        "timestamp":timestamp,"open":mid,"high":mid+0.5+(x%4)*0.01,
        "low":mid-0.6,"close":mid+0.1*np.sin(x/7),"volume":50+(x%11),
    })
    validate_frame(f,"minute15")
    h=independently_aggregate(f,"h")
    q=independently_aggregate(f,"4h")
    return f,h,q


class FullHigherTimeframeAsOfTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.f,cls.h,cls.q=synthetic()

    def test_engine_and_independent_all_decision_bars(self):
        reference=independent_full_values(self.f,self.h,self.q)
        actual=original_engine_asof(self.f,self.h,self.q,engine)
        report=discrepancies(actual,reference)
        self.assertEqual(set(report),set(FIELDS))
        self.assertEqual(sum(x["compared"] for x in report.values()),8192)
        self.assertEqual(sum(x["mismatches"] for x in report.values()),0)

    def test_exact_1h_visibility_boundary(self):
        vals=independent_full_values(self.f,self.h,self.q)
        # First hourly bar OPEN 00:00 -> CLOSE 01:00, 15m decisions
        # 00:15,00:30,00:45 cannot see it; 01:00 can.
        self.assertTrue(all(np.isnan(vals["h1_vol_ok"][i]) for i in range(3)))
        self.assertTrue(np.isfinite(vals["h1_vol_ok"][3]))

    def test_exact_4h_visibility_boundary(self):
        vals=independent_full_values(self.f,self.h,self.q)
        self.assertTrue(all(np.isnan(vals["h4_up"][i]) for i in range(15)))
        self.assertTrue(np.isfinite(vals["h4_up"][15]))

    def test_future_tail_mutation_cannot_rewrite_past(self):
        original=independent_full_values(self.f,self.h,self.q)
        hour=self.h.copy()
        four=self.q.copy()
        # Only alter final source bars, whose closes cannot be visible
        # before their actual UTC close timestamps.
        hour.loc[hour.index[-1],"high"] += 80
        four.loc[four.index[-1],"close"] += 50
        changed=independent_full_values(self.f,hour,four)
        h_end=self.h.timestamp.iloc[-1]+pd.Timedelta(hours=1)
        q_end=self.q.timestamp.iloc[-1]+pd.Timedelta(hours=4)
        decision=self.f.timestamp+pd.Timedelta(minutes=15)
        for key in ("h1_vol_ok","h1_compression"):
            visible_before=(decision<h_end).to_numpy()
            self.assertTrue(np.array_equal(original[key][visible_before],
                                           changed[key][visible_before],
                                           equal_nan=True))
        for key in ("h4_up","h4_range"):
            visible_before=(decision<q_end).to_numpy()
            self.assertTrue(np.array_equal(original[key][visible_before],
                                           changed[key][visible_before],
                                           equal_nan=True))

    def test_discrepancy_detector_identifies_corruption(self):
        a=independent_full_values(self.f,self.h,self.q)
        b={k:v.copy() for k,v in a.items()}
        b["h4_up"][500]=1.0-b["h4_up"][500]
        report=discrepancies(a,b)
        self.assertEqual(report["h4_up"]["mismatches"],1)
        self.assertEqual(report["h4_up"]["first_mismatch"],500)

    def test_incomplete_utc_grid_rejected(self):
        broken=self.f.drop(index=[100]).reset_index(drop=True)
        with self.assertRaisesRegex(AssertionError,"grid"):
            validate_frame(broken,"minute15")

    def test_invalid_ohlcv_rejected(self):
        broken=self.f.copy()
        broken.loc[100,"low"]=broken.loc[100,"high"]+10
        with self.assertRaisesRegex(AssertionError,"OHLCV"):
            validate_frame(broken,"minute15")


if __name__=="__main__":
    unittest.main()
