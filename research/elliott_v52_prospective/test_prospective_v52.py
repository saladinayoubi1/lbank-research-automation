"""V52 prospective holdout embargo and independent official 1m source tests."""
import csv
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import gzip
import hashlib
import unittest
import numpy as np
import pandas as pd

from prospective_v52 import (
    SOURCE_START,SCORE_START,SCORE_END,RESEARCH_ONLY,ENTRY_SIGNAL,
    PAPER_ELIGIBLE,LIVE_ENABLED,ProspectiveGateError,
    read_frozen_protocol,validate_scoring_event_time,verify_official_day_source,
)

class V52ProspectiveGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.raw=self.path/"ETHUSDT_2026-10-19.csv.gz"
        self.parq=self.path/"eth_usdt_1m.parquet"
        self.rows=[]
        date=pd.Timestamp("2026-10-19T00:00:00Z")
        for i in range(1440):
            stamp=int((date+pd.Timedelta(minutes=i)).timestamp()*1000)
            px=f"{100+i/100:.2f}"
            self.rows.append([f"id{i}",str(stamp),px,"1.25","Buy","0"])
        self.save_raw()
        self.write_parq()
    def save_raw(self):
        with gzip.open(self.raw,"wt",encoding="utf8",newline="") as f:
            w=csv.writer(f);w.writerow(["id","timestamp","price","volume","side","rpi"])
            w.writerows(self.rows)
    def write_parq(self):
        dt=pd.date_range("2026-10-19",periods=1440,freq="min",tz="UTC")
        price=np.array([100+i/100 for i in range(1440)],dtype=float)
        self.frame=pd.DataFrame({"timestamp":dt,"open":price,"high":price,
          "low":price,"close":price,"volume":np.full(1440,1.25),
          "trade_count":np.ones(1440,dtype=np.int64)})
        self.save_parq()
    def save_parq(self):
        self.frame.to_parquet(self.parq,index=False)
    def verify(self,now="2026-10-20T00:00:01Z",day="2026-10-19T00:00:00Z",**kwargs):
        rawhash=hashlib.sha256(self.raw.read_bytes()).hexdigest()
        parqhash=hashlib.sha256(self.parq.read_bytes()).hexdigest()
        return verify_official_day_source("ETHUSDT",day,self.raw,rawhash,self.parq,parqhash,
                                         observed_utc=now,**kwargs)
    def test_frozen_scoring_boundaries(self):
        spec=read_frozen_protocol()
        self.assertEqual(str(SOURCE_START),"2026-10-16 00:00:00+00:00")
        self.assertEqual(str(SCORE_START),"2026-10-18 00:00:00+00:00")
        self.assertEqual(str(SCORE_END),"2026-11-16 00:00:00+00:00")
        self.assertEqual(spec["wave_protocol"]["frozen_child_segments"],[5,3,5,3,5,5,3,5])
        self.assertTrue(RESEARCH_ONLY);self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)
    def test_hash_pin_rejects_changed_protocol_bytes(self):
        import prospective_v52 as mod
        from unittest.mock import patch
        altered=self.path/"altered-protocol.json"
        altered.write_bytes(mod.PROTOCOL_PATH.read_bytes()+b"\\n")
        with patch.object(mod,"PROTOCOL_PATH",altered):
            with self.assertRaisesRegex(ProspectiveGateError,"SHA256 changed"):
                mod.read_frozen_protocol()
    def test_historical_market_event_embargo(self):
        with self.assertRaisesRegex(ProspectiveGateError,"outside delayed"):
            validate_scoring_event_time("2026-10-16T12:00:00Z",
               first_parent_confirmed_close_utc="2026-10-16T11:45:00Z")
    def test_boundary_event_is_eligible_for_qa_only(self):
        x=validate_scoring_event_time("2026-10-18T00:00:00Z",
               first_parent_confirmed_close_utc="2026-10-17T23:45:00Z")
        self.assertEqual(x,SCORE_START)
    def test_future_parent_confirmation_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"future parent"):
            validate_scoring_event_time("2026-10-18T00:00:00Z",
               first_parent_confirmed_close_utc="2026-10-18T00:15:00Z")
    def test_end_exclusive(self):
        with self.assertRaisesRegex(ProspectiveGateError,"outside"):
            validate_scoring_event_time("2026-11-16T00:00:00Z",
                first_parent_confirmed_close_utc="2026-11-15T23:45:00Z")
    def test_naive_decision_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"timezone"):
            validate_scoring_event_time("2026-10-20T12:00:00",
                first_parent_confirmed_close_utc="2026-10-20T11:00:00Z")
    def test_synthetic_complete_day_accepted_without_trade_auth(self):
        item=self.verify()
        self.assertEqual(item.source_trades,1440)
        self.assertEqual(item.exact_candles,1440)
        self.assertEqual(item.ohlcv_checks,7200)
        self.assertEqual(item.count_checks,1440)
        self.assertFalse(item.entry_signal or item.paper_eligible)
    def test_day_not_yet_complete_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"not yet past"):
            self.verify(now="2026-10-19T23:59:00Z")
    def test_pre_window_archive_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"historical"):
            self.verify(day="2026-10-15T00:00:00Z")
    def test_bad_source_hash_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"SHA mismatch"):
            verify_official_day_source("ETHUSDT","2026-10-19T00:00:00Z",
                 self.raw,"0"*64,self.parq,hashlib.sha256(self.parq.read_bytes()).hexdigest(),
                 observed_utc="2026-10-20T01:00:00Z")
    def test_gap_in_daily_trades_rejected_no_fill(self):
        self.rows.pop(100);self.save_raw()
        with self.assertRaisesRegex(ProspectiveGateError,"incomplete source minutes"):
            self.verify()
    def test_offgrid_or_tampered_minute_rejected(self):
        self.frame.loc[23,"timestamp"]=self.frame["timestamp"].iat[23]+pd.Timedelta(seconds=1)
        self.save_parq()
        with self.assertRaisesRegex(ProspectiveGateError,"minute timestamps"):
            self.verify()
    def test_trade_volume_mismatch_rejected(self):
        self.frame.loc[50,"volume"]=2.25
        self.save_parq()
        with self.assertRaisesRegex(ProspectiveGateError,"OHLCV independent mismatch"):
            self.verify()
    def test_trade_count_mismatch_rejected(self):
        self.frame.loc[51,"trade_count"]=2
        self.save_parq()
        with self.assertRaisesRegex(ProspectiveGateError,"trade count mismatch"):
            self.verify()
    def test_naive_source_rejected(self):
        self.frame["timestamp"]=self.frame["timestamp"].dt.tz_localize(None)
        self.save_parq()
        with self.assertRaisesRegex(ProspectiveGateError,"timezone"):
            self.verify()
    def test_unsupported_source_symbol_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"unsupported"):
            verify_official_day_source("LBank","2026-10-19T00:00:00Z",
                 self.raw,"0"*64,self.parq,"0"*64,
                 observed_utc="2026-10-20T00:01:00Z")

if __name__=="__main__":unittest.main()
