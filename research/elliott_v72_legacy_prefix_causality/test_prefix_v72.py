"""V72 source-prefix anti-lookahead regressions, no orders or P/L."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from audit_prefix_v72 import (
    five_swing_prefix_check,_field_equal,hashfile,
    PREFIX_HISTORY_BARS,ARCHIVE_FEATURE_SUFFIX_BARS,
    RESEARCH_ONLY,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED
)

def sample(n=1050):
    t=pd.date_range("2024-01-01T00:15:00Z",periods=n,freq="15min")
    drift=100+np.arange(n)*0.02
    return pd.DataFrame({"timestamp":t,"open":drift,
        "high":drift+1,"low":drift-1,"close":drift+0.4})

def causal_builder(frame):
    a=frame["close"].shift(1).fillna(0).copy()
    z=pd.Series(np.zeros(len(frame),dtype=bool))
    inactive=pd.Series(np.full(len(frame),np.nan))
    return {"lagged":a,"lagged_elliott5_active":z,
            "elliott5_close_breakout_event":z,
            "lagged_elliott5_confirmed_at":inactive}

class V72HistoricalPrefixTests(unittest.TestCase):
    def test_clean_causal_builder_no_future_leak(self):
        result=five_swing_prefix_check(sample(),PREFIX_HISTORY_BARS,causal_builder)
        self.assertFalse(result["asof_event"])
        self.assertTrue(result["original_and_mutated_future_unchanged"])
    def test_last_bar_leak_is_detected(self):
        def leaky(frame):
            result=causal_builder(frame)
            result["lagged"]=pd.Series(np.full(len(frame),float(frame.close.iat[-1])))
            return result
        with self.assertRaisesRegex(ValueError,"FUTURE_UNMODIFIED_SUFFIX_CHANGED_PAST_FEATURE"):
            five_swing_prefix_check(sample(),PREFIX_HISTORY_BARS,leaky)
    def test_future_mutation_only_leak_is_detected(self):
        past=sample()
        def test_sensitive(frame):
            v=causal_builder(frame)
            if frame.high.max()>140:
                v["lagged"]=pd.Series(np.ones(len(frame)))
            return v
        with self.assertRaisesRegex(ValueError,"FUTURE_TAMPERED_SUFFIX_CHANGED_PAST_FEATURE"):
            five_swing_prefix_check(past,PREFIX_HISTORY_BARS,test_sensitive)
    def test_unnatural_future_event_requires_past_confirmation(self):
        def forged(frame):
            result=causal_builder(frame)
            j=PREFIX_HISTORY_BARS-1
            result["elliott5_close_breakout_event"].iat[j]=True
            result["lagged_elliott5_confirmed_at"].iat[j]=j
            return result
        with self.assertRaisesRegex(ValueError,"EVENT_NOT_STRICTLY_PREVIOUSLY"):
            five_swing_prefix_check(sample(),PREFIX_HISTORY_BARS,forged)
    def test_too_short_prefix_denied(self):
        with self.assertRaisesRegex(ValueError,"INVALID_PREFIX"):
            five_swing_prefix_check(sample(1000),990,causal_builder)
    def test_wrong_fields_are_not_considered_equal(self):
        self.assertFalse(_field_equal({"a":pd.Series([1.0])},{"b":pd.Series([1.0])}))
        self.assertFalse(_field_equal({"a":pd.Series([1.0])},{"a":pd.Series([2.0])}))
    def test_physical_digest_sensitive_to_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/"raw";p.write_bytes(b"v72-original")
            a=hashfile(p);p.write_bytes(b"v72-corrupted")
            self.assertNotEqual(a,hashfile(p))
    def test_no_execution_flags(self):
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)
        self.assertEqual(ARCHIVE_FEATURE_SUFFIX_BARS,12)
if __name__=="__main__":unittest.main()
