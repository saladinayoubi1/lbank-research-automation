"""V74 complete legacy engine source-prefix future-leak regression cases.

All market frames here are SYNTHETIC. Actual Bybit physical historical
evidence is tested in the separately run, SHA-bound V74 replay receipt.
"""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from composite_prefix_v74 import (
    evaluate_at, closed_prefix, compare_prefix, digest,
    RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED,
)

def frame(minutes,n):
    grid=pd.date_range("2024-01-01T00:00:00Z",periods=n,freq=f"{minutes}min")
    price=100+np.arange(n)*0.005
    return pd.DataFrame({"timestamp":grid,"open":price,"high":price+1,
        "low":price-1,"close":price+0.2,"volume":np.full(n,50.)})

def corpus():
    return {"minute15":frame(15,3000),"hour1":frame(60,780),
            "hour4":frame(240,220)}

def decision(c):
    return c["minute15"]["timestamp"].iat[2800]+pd.Timedelta(minutes=15)

def basic_builder(frames):
    f=frames["minute15"]
    h=frames["hour1"]
    q=frames["hour4"]
    return pd.DataFrame({
        "decision_at":pd.to_datetime(f["timestamp"],utc=True)+pd.Timedelta(minutes=15),
        "lagged_close":f["close"].shift(1),
        "previous_hour":np.full(len(f),float(h["close"].iat[10])),
        "previous_four_hour":np.full(len(f),float(q["close"].iat[10])),
    })

class V74CompleteCompositePrefixTests(unittest.TestCase):
    def test_synthetic_causal_engine_unmodified_by_future(self):
        data=corpus()
        result=evaluate_at(data,decision(data),basic_builder)
        self.assertTrue(result["all_earlier_feature_cells_unchanged"])
        self.assertEqual(result["columns"],4)
    def test_deliberate_last_future_15m_price_leak_rejected(self):
        def dishonest(frames):
            x=basic_builder(frames)
            x["leaky"]=float(frames["minute15"]["close"].iat[-1])
            return x
        c=corpus()
        with self.assertRaisesRegex(ValueError,"COMPOSITE_FUTURE_LEAK_APPENDED"):
            evaluate_at(c,decision(c),dishonest)
    def test_future_high_only_malicious_feature_rejected(self):
        def dishonest(frames):
            x=basic_builder(frames)
            if float(frames["minute15"]["high"].max())>180:
                x["lagged_close"]=999.0
            return x
        c=corpus()
        with self.assertRaisesRegex(ValueError,"COMPOSITE_FUTURE_LEAK_MUTATED"):
            evaluate_at(c,decision(c),dishonest)
    def test_future_four_hour_bar_leak_rejected(self):
        def dishonest(frames):
            x=basic_builder(frames)
            x["leaky"]=float(frames["hour4"]["close"].iat[-1])
            return x
        c=corpus()
        with self.assertRaisesRegex(ValueError,"COMPOSITE_FUTURE_LEAK_APPENDED"):
            evaluate_at(c,decision(c),dishonest)
    def test_last_parent_open_plus_duration_not_future(self):
        c=corpus()
        t=decision(c)
        for tf,minutes in (("minute15",15),("hour1",60),("hour4",240)):
            base,_,_=closed_prefix(c[tf],t,tf)
            self.assertLessEqual(base["timestamp"].iat[-1]+pd.Timedelta(minutes=minutes),t)
    def test_discontinuous_source_fails_closed(self):
        c=corpus()
        c["hour1"]=c["hour1"].drop(index=35).reset_index(drop=True)
        with self.assertRaisesRegex(ValueError,"SOURCE_TIME_GRID_BROKEN"):
            evaluate_at(c,decision(c),basic_builder)
    def test_naive_decision_rejected(self):
        c=corpus()
        with self.assertRaisesRegex(ValueError,"DECISION_NOT_UTC_AWARE"):
            evaluate_at(c,decision(c).tz_localize(None),basic_builder)
    def test_altered_sha_bytes_detectable(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"original"
            path.write_bytes(b"original")
            h=digest(path)
            path.write_bytes(b"tampered")
            self.assertNotEqual(h,digest(path))
    def test_no_trade_or_demo_authority(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)

if __name__=="__main__":
    unittest.main()
