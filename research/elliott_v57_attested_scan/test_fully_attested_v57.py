"""V57 scanner source attestation from physical V55 receipt + raw trades.

Synthetic daily sources are explicitly marked OS-temp fixture evidence.
They MUST NEVER be counted as real future market results or orders.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd

from prospective_v52 import ProspectiveGateError
from build_official_day_v55 import build_verified_1m_day
from fully_attested_v57 import (
    scan_only_fully_oracled_receipts,
    ENTRY_SIGNAL,LIVE_ENABLED,PAPER_ELIGIBLE,
)

class V57PhysicalRawReattestationTests(unittest.TestCase):
    def setUp(self):
        holder=tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root=Path(holder.name)
        self.receipts=[]
        self.raw=[]
        for offset in range(2):
            day=pd.Timestamp("2026-10-16T00:00:00Z")+pd.Timedelta(days=offset)
            name=f"ETHUSDT_{day.date()}.csv.gz"
            path=self.root/name
            with gzip.open(path,"wt",encoding="utf8",newline="") as fh:
                writer=csv.writer(fh)
                writer.writerow(["id","timestamp","price","volume","side","rpi"])
                for k in range(1440):
                    t=int((day+pd.Timedelta(minutes=k)).timestamp()*1000)
                    writer.writerow([f"{offset}-{k}",str(t),f"{100+k*.01+offset*10:.2f}",
                                     "1.25","Buy","0"])
            out=self.root/f"evidence-{offset}"
            result=build_verified_1m_day(
                "ETHUSDT",day,path,out,
                declared_source_url=f"https://public.bybit.com/spot/ETHUSDT/{name}",
                fixture_mode=True,observed_utc="2026-10-18T00:01:00Z",
            )
            self.assertEqual(result["status"],"SYNTHETIC_TEST_ONLY")
            self.receipts.append(out/"SOURCE_INTAKE_RECEIPT.json")
            self.raw.append(path)
    def run_scan(self,receipts=None,clock="2026-10-18T00:01:00Z",fixture=True):
        return scan_only_fully_oracled_receipts(
            "ETHUSDT",self.receipts if receipts is None else receipts,
            decision_close_utc="2026-10-18T00:00:00Z",
            fixture_mode=fixture,observed_utc=clock if fixture else None)
    def test_two_days_physically_reverified_from_receipt(self):
        result=self.run_scan()
        self.assertTrue(result.fixture_mode)
        self.assertFalse(result.source_remote_origin_authenticated)
        self.assertEqual(result.physical_independently_verified_days,2)
        self.assertEqual(result.scan.verified_days,2)
        self.assertEqual(result.scan.physical_source_trades,2880)
        self.assertEqual(result.scan.parent_geometry_candidates,0)
        self.assertFalse(result.entry_signal or result.paper_eligible or result.live_enabled)
        self.assertFalse(ENTRY_SIGNAL or PAPER_ELIGIBLE or LIVE_ENABLED)
    def test_forged_source_trades_count_in_receipt_rejected(self):
        data=json.loads(self.receipts[1].read_text(encoding="utf8"))
        data["independent_v52_result"]["source_trades"]+=5
        self.receipts[1].write_text(json.dumps(data),encoding="utf8")
        with self.assertRaisesRegex(ProspectiveGateError,"claim differs"):
            self.run_scan()
    def test_raw_archive_changed_after_v55_receipt_rejected(self):
        with self.raw[1].open("ab") as fh:fh.write(b"POST-RECEIPT ALTERATION")
        with self.assertRaisesRegex(ProspectiveGateError,"SHA mismatch"):
            self.run_scan()
    def test_minute_parquet_changed_after_v55_receipt_rejected(self):
        info=json.loads(self.receipts[0].read_text(encoding="utf8"))
        with Path(info["parquet_path"]).open("ab") as f:f.write(b"POST-RECEIPT ALTERATION")
        with self.assertRaisesRegex(ProspectiveGateError,"SHA mismatch"):
            self.run_scan()
    def test_declared_old_unscored_receipt_rejected(self):
        data=json.loads(self.receipts[0].read_text(encoding="utf8"))
        data["declared_source_url"]="https://public.bybit.com/spot/ETHUSDT/ETHUSDT_2026-10-08.csv.gz"
        self.receipts[0].write_text(json.dumps(data),encoding="utf8")
        with self.assertRaisesRegex(ProspectiveGateError,"URL"):
            self.run_scan()
    def test_fixture_falsely_claiming_real_source_rejected(self):
        data=json.loads(self.receipts[1].read_text(encoding="utf8"))
        data["fixture_mode"]=False
        data["status"]="PASS_OFFLINE_INDEPENDENT_1M_SOURCE_ONLY"
        self.receipts[1].write_text(json.dumps(data),encoding="utf8")
        with self.assertRaisesRegex(ProspectiveGateError,"fixture"):
            self.run_scan()
    def test_synthetic_cannot_enter_real_execution(self):
        # Independently push the apparent wall clock past the full day so the
        # source status guard, not the earlier future-time guard, is tested.
        from datetime import datetime,timezone
        with patch("fully_attested_v57.datetime") as fake_time:
            fake_time.now.return_value=datetime(2026,10,20,tzinfo=timezone.utc)
            with self.assertRaisesRegex(ProspectiveGateError,"fixture"):
                self.run_scan(fixture=False)
    def test_cannot_score_before_actual_decision_time(self):
        with self.assertRaisesRegex(ProspectiveGateError,"not yet actually observable"):
            self.run_scan(clock="2026-10-17T23:59:59Z")
    def test_future_or_duplicate_source_receipts_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"complete chronological"):
            self.run_scan(receipts=[self.receipts[0]]+[self.receipts[1]]*2)
    def test_receipt_swapped_days_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"URL"):
            self.run_scan(receipts=self.receipts[::-1])
    def test_fake_source_receipt_schema_rejected(self):
        item=json.loads(self.receipts[0].read_text(encoding="utf8"))
        item["schema"]="nexus.elliott-v55-source-intake-v1"
        self.receipts[0].write_text(json.dumps(item),encoding="utf8")
        with self.assertRaisesRegex(ProspectiveGateError,"non-transactional"):
            self.run_scan()

if __name__=="__main__":
    unittest.main()
