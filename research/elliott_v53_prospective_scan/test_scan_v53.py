"""V53 daily source-verified prospective research-only scanner regressions."""
import hashlib
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import numpy as np
import pandas as pd
from prospective_v52 import VerifiedDay,ProspectiveGateError
from scan_verified_v53 import scan_verified_complete_days,ENTRY_SIGNAL,PAPER_ELIGIBLE,LIVE_ENABLED

class V53ProspectiveScannerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.days=[]
        for i in range(3):
            d=pd.Timestamp("2026-10-16T00:00:00Z")+pd.Timedelta(days=i)
            idx=np.arange(1440,dtype=float)
            price=100.0+i*14.4+idx*.01
            df=pd.DataFrame({"timestamp":pd.date_range(d,periods=1440,freq="min",tz="UTC"),
                "open":price,"high":price+.1,"low":price-.1,"close":price,
                "volume":np.full(1440,1.0),"trade_count":np.ones(1440,dtype=np.int64)})
            fn=self.root/f"ETHUSDT-{i}.parquet";df.to_parquet(fn,index=False)
            h=hashlib.sha256(fn.read_bytes()).hexdigest()
            receipt=VerifiedDay("ETHUSDT",d.date().isoformat(),1440,1440,7200,1440,"a"*64,h)
            self.days.append((receipt,fn))
    def scan(self,sources=None,decision="2026-10-18T00:00:00Z",symbol="ETHUSDT"):
        return scan_verified_complete_days(symbol,self.days[:2] if sources is None else sources,
                                           decision_close_utc=decision)
    def test_complete_synthetic_days_research_only(self):
        x=self.scan()
        self.assertEqual(x.verified_days,2)
        self.assertEqual(x.physical_source_trades,2880)
        self.assertEqual(x.parent_geometry_candidates,0)
        self.assertFalse(x.entry_signal or x.paper_eligible or x.live_enabled)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)
    def test_daily_asof_third_day(self):
        x=self.scan(sources=self.days,decision="2026-10-19T00:00:00Z")
        self.assertEqual(x.verified_days,3)
        self.assertEqual(x.decision_close_utc,"2026-10-19T00:00:00+00:00")
    def test_scoring_embargo_oct16(self):
        with self.assertRaisesRegex(ProspectiveGateError,"outside delayed"):
            self.scan(decision="2026-10-16T12:00:00Z")
    def test_score_not_at_midnight_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"complete UTC day boundary"):
            self.scan(decision="2026-10-18T00:30:00Z")
    def test_missing_day_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"missing duplicated"):
            self.scan(sources=self.days[:1])
    def test_extra_future_archive_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"missing duplicated"):
            self.scan(sources=self.days)
    def test_historical_archive_rejected(self):
        p,f=self.days[0]
        changed=replace(p,day_utc="2026-10-08")
        with self.assertRaisesRegex(ProspectiveGateError,"missing verified ordered"):
            self.scan(sources=[(changed,f),self.days[1]])
    def test_wrong_symbol_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"unsupported"):
            self.scan(symbol="LBank")
    def test_wrong_day_symbol_rejected(self):
        p,f=self.days[0]
        with self.assertRaisesRegex(ProspectiveGateError,"missing verified ordered"):
            self.scan(sources=[(replace(p,symbol="BTCUSDT"),f),self.days[1]])
    def test_changed_parquet_bytes_rejected(self):
        proof,path=self.days[0]
        with path.open("ab") as fh:fh.write(b"changed")
        with self.assertRaisesRegex(ProspectiveGateError,"absent or modified"):
            self.scan()
    def test_wrong_minute_grid_rejected_even_with_new_hash(self):
        proof,path=self.days[0]
        df=pd.read_parquet(path)
        df.loc[5,"timestamp"]=df.loc[5,"timestamp"]+pd.Timedelta(seconds=2)
        df.to_parquet(path,index=False)
        amended=replace(proof,minute_parquet_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ProspectiveGateError,"wrong UTC day grid"):
            self.scan(sources=[(amended,path),self.days[1]])
    def test_naive_minute_timestamps_rejected(self):
        proof,path=self.days[0]
        df=pd.read_parquet(path)
        df["timestamp"]=df["timestamp"].dt.tz_localize(None)
        df.to_parquet(path,index=False)
        amended=replace(proof,minute_parquet_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ProspectiveGateError,"timezone"):
            self.scan(sources=[(amended,path),self.days[1]])
    def test_missing_raw_source_sha_rejected(self):
        p,f=self.days[0]
        with self.assertRaisesRegex(ProspectiveGateError,"original trade archive SHA"):
            self.scan(sources=[(replace(p,official_gzip_sha256=""),f),self.days[1]])
    def test_incomplete_independent_oracle_rejected(self):
        p,f=self.days[0]
        with self.assertRaisesRegex(ProspectiveGateError,"incomplete independent"):
            self.scan(sources=[(replace(p,ohlcv_checks=6000),f),self.days[1]])
    def test_end_exclusive(self):
        with self.assertRaisesRegex(ProspectiveGateError,"outside delayed"):
            self.scan(decision="2026-11-16T00:00:00Z")
    def test_no_spurious_pivots_uptrend(self):
        x=self.scan()
        self.assertEqual(x.nine_parent_group_count,0)
        self.assertEqual(x.bounded_child_candidates,0)

if __name__=="__main__":unittest.main()
