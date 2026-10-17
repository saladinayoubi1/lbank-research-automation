"""V55 offline importer tests; all future-day positive fixtures are synthetic."""
from __future__ import annotations
import csv
import gzip
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from prospective_v52 import ProspectiveGateError,verify_official_day_source
from build_official_day_v55 import build_verified_1m_day,RESEARCH_ONLY,LIVE_ENABLED,ENTRY_SIGNAL,PAPER_ELIGIBLE

class V55OfflineOfficialIntakeTests(unittest.TestCase):
    def setUp(self):
        holder=tempfile.TemporaryDirectory();self.addCleanup(holder.cleanup)
        self.root=Path(holder.name)
        self.archive=self.root/"ETHUSDT_2026-10-19.csv.gz"
        self.out=self.root/"fresh-evidence"
        self.url="https://public.bybit.com/spot/ETHUSDT/ETHUSDT_2026-10-19.csv.gz"
        self.rows=[
          [f"id{i}",str(1792368000000+i*60000),f"{100+i/100:.2f}","1.25","Buy","0"]
          for i in range(1440)
        ]
        # Compute timestamp from UTC timestamp, avoiding platform/local clock assumptions.
        import pandas as pd
        start=int(pd.Timestamp("2026-10-19T00:00:00Z").timestamp()*1000)
        for i,item in enumerate(self.rows):item[1]=str(start+i*60000)
        self.save()
    def save(self):
        with gzip.open(self.archive,"wt",encoding="utf8",newline="") as fp:
            writer=csv.writer(fp)
            writer.writerow(["id","timestamp","price","volume","side","rpi"])
            writer.writerows(self.rows)
    def build(self,**kw):
        arguments={"declared_source_url":self.url,
                   "fixture_mode":True,"observed_utc":"2026-10-20T00:00:01Z"}
        arguments.update(kw)
        return build_verified_1m_day("ETHUSDT","2026-10-19T00:00:00Z",
                                      self.archive,self.out,**arguments)
    def test_complete_future_day_fixture_and_independent_oracle(self):
        result=self.build()
        self.assertEqual(result["status"],"SYNTHETIC_TEST_ONLY")
        self.assertTrue(result["fixture_mode"])
        self.assertFalse(result["source_url_is_proven_by_download"])
        self.assertFalse(result["entry_signal"] or result["live_enabled"] or result["paper_eligible"])
        self.assertTrue(RESEARCH_ONLY)
        self.assertFalse(ENTRY_SIGNAL or LIVE_ENABLED or PAPER_ELIGIBLE)
        proof=result["independent_v52_result"]
        self.assertEqual((proof["source_trades"],proof["exact_candles"],
                          proof["ohlcv_checks"],proof["count_checks"]),
                         (1440,1440,7200,1440))
        self.assertTrue((self.out/"SOURCE_INTAKE_RECEIPT.json").is_file())
    def test_closed_day_required(self):
        with self.assertRaisesRegex(ProspectiveGateError,"not yet complete"):
            self.build(observed_utc="2026-10-19T23:59:59Z")
        self.assertFalse(self.out.exists())
    def test_history_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"historical"):
            build_verified_1m_day("ETHUSDT","2026-10-08T00:00:00Z",self.archive,self.out,
                 declared_source_url=self.url,fixture_mode=True,observed_utc="2026-10-20T00:01:00Z")
    def test_source_url_must_match_official_public_spot_exactly(self):
        with self.assertRaisesRegex(ProspectiveGateError,"URL"):
            self.build(declared_source_url="https://example.org/ETHUSDT_2026-10-19.csv.gz")
    def test_clock_override_denied_in_real_mode(self):
        with self.assertRaisesRegex(ProspectiveGateError,"clock overrides forbidden"):
            self.build(fixture_mode=False)
        self.assertFalse(self.out.exists())
    def test_missing_minute_no_synthetic_forward_fill(self):
        self.rows.pop(14);self.save()
        with self.assertRaisesRegex(ProspectiveGateError,"missing trade-bearing minute"):
            self.build()
        self.assertFalse(self.out.exists())
    def test_non_monotone_raw_trade_order_rejected(self):
        self.rows[14],self.rows[15]=self.rows[15],self.rows[14]
        self.save()
        with self.assertRaisesRegex(ProspectiveGateError,"timestamp"):
            self.build()
    def test_zero_or_negative_source_price_rejected(self):
        self.rows[45][2]="0";self.save()
        with self.assertRaisesRegex(ProspectiveGateError,"price"):
            self.build()
    def test_real_source_archive_wrong_filename_rejected(self):
        other=self.root/"ETHUSDT_2026-10-18.csv.gz"
        self.archive.rename(other);self.archive=other
        with self.assertRaisesRegex(ProspectiveGateError,"wrong exact"):
            self.build()
    def test_no_duplicate_output_mutation(self):
        before=self.build()
        manifest=(self.out/"SOURCE_INTAKE_RECEIPT.json").read_bytes()
        with self.assertRaisesRegex(ProspectiveGateError,"refuse existing"):
            self.build()
        self.assertEqual((self.out/"SOURCE_INTAKE_RECEIPT.json").read_bytes(),manifest)
    def test_altered_raw_after_proof_is_rejected_independently(self):
        proof=self.build()
        with self.archive.open("ab") as inp:inp.write(b"x")
        with self.assertRaisesRegex(ProspectiveGateError,"SHA mismatch"):
            verify_official_day_source("ETHUSDT","2026-10-19T00:00:00Z",
               self.archive,proof["raw_sha256"],
               proof["parquet_path"],proof["parquet_sha256"],
               observed_utc="2026-10-20T00:00:01Z")
    def test_no_fixture_writes_outside_os_temp(self):
        forbidden=Path(r"E:\NEXUS-QA\elliott-v55-fixture-outside-temp-should-not-exist")
        self.assertFalse(forbidden.exists())
        with self.assertRaisesRegex(ProspectiveGateError,"OS temp"):
            build_verified_1m_day("ETHUSDT","2026-10-19T00:00:00Z",
                self.archive,forbidden,declared_source_url=self.url,
                fixture_mode=True,observed_utc="2026-10-20T00:00:01Z")
        self.assertFalse(forbidden.exists())

if __name__=="__main__":unittest.main()
