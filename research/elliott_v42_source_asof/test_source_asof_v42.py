"""Offline source-as-of V42 regression tests. No network or trading."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
from source_asof_v42 import completed_1m_prefix,SourceGateError
from nested_elliott_v40 import check_nested_structure

class SourceAsOfV42Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"source.parquet"
        t=pd.date_range("2026-10-13T00:00:00Z",periods=30,freq="min")
        self.df=pd.DataFrame({"timestamp":t,"open":np.arange(30,dtype=float)+100,
          "high":np.arange(30,dtype=float)+101,
          "low":np.arange(30,dtype=float)+99,
          "close":np.arange(30,dtype=float)+100.5,
          "volume":np.ones(30),
          "trade_count":np.full(30,5,dtype=np.int64)})
        self.save()
    def save(self):
        self.df.to_parquet(self.path,index=False)
        self.sha=hashlib.sha256(self.path.read_bytes()).hexdigest()
    def call(self,close="2026-10-13T00:20:00Z",sha=None,**kwargs):
        return completed_1m_prefix(self.path,sha or self.sha,close,**kwargs)
    def test_asof_truncates_future_source_tail(self):
        prefix=self.call()
        self.assertEqual(len(prefix),20)
        self.assertEqual(str(prefix.timestamp.iat[-1]),"2026-10-13 00:19:00+00:00")
    def test_complete_final_source_bar(self):
        self.assertEqual(len(self.call(close="2026-10-13T00:30:00Z")),30)
    def test_millisecond_parquet_timezone_precision(self):
        self.df["timestamp"]=self.df["timestamp"].dt.as_unit("ms")
        self.save()
        self.assertEqual(len(self.call()),20)
    def test_sha_pin_enforced(self):
        with self.assertRaisesRegex(SourceGateError,"hash mismatch"):
            self.call(sha="0"*64)
    def test_missing_minutes_fail_closed(self):
        self.df=self.df.drop(index=7).reset_index(drop=True);self.save()
        with self.assertRaisesRegex(SourceGateError,"missing"):
            self.call()
    def test_duplicate_minutes_fail_closed(self):
        self.df.loc[7,"timestamp"]=self.df.loc[6,"timestamp"];self.save()
        with self.assertRaisesRegex(SourceGateError,"duplicated|chronology"):
            self.call()
    def test_no_future_decision(self):
        with self.assertRaisesRegex(SourceGateError,"outside"):
            self.call(close="2026-10-13T00:31:00Z")
    def test_naive_decision_rejected(self):
        with self.assertRaisesRegex(SourceGateError,"naive"):
            self.call(close="2026-10-13T00:20:00")
    def test_naive_source_rejected(self):
        self.df["timestamp"]=self.df["timestamp"].dt.tz_localize(None);self.save()
        with self.assertRaisesRegex(SourceGateError,"timezone"):
            self.call()
    def test_unaligned_decision(self):
        with self.assertRaisesRegex(SourceGateError,"aligned"):
            self.call(close="2026-10-13T00:20:30Z")
    def test_start_rebind_rejected(self):
        with self.assertRaisesRegex(SourceGateError,"start mismatch"):
            self.call(expected_start_utc="2026-10-12T00:00:00Z")
    def test_inconsistent_ohlc_rejected(self):
        self.df.loc[5,"high"]=self.df.loc[5,"close"]-2;self.save()
        with self.assertRaisesRegex(SourceGateError,"OHLC"):
            self.call()
    def test_nan_volume_rejected(self):
        self.df.loc[5,"volume"]=np.nan;self.save()
        with self.assertRaisesRegex(SourceGateError,"finite"):
            self.call()
    def test_invalid_trade_count_rejected(self):
        self.df.loc[5,"trade_count"]=0;self.save()
        with self.assertRaisesRegex(SourceGateError,"counts"):
            self.call()
    def test_missing_source_file_rejected(self):
        self.path.unlink()
        with self.assertRaisesRegex(SourceGateError,"missing"):
            self.call()
    def test_no_witness_is_not_valid_elliott(self):
        prefix=self.call()
        verdict=check_nested_structure(prefix,(),(),decision_close_utc="2026-10-13T00:20:00Z")
        self.assertFalse(verdict.source_bound)
        self.assertFalse(verdict.paper_eligible)
        self.assertFalse(verdict.entry_signal)
        self.assertEqual(verdict.reason,"PARENT_OR_ABC_OR_LEGS_MISSING")

if __name__=="__main__":
    unittest.main()
