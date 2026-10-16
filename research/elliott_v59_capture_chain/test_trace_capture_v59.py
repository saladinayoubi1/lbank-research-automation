"""V59 chain-of-custody tests using two physical synthetic TLS archive days.

All GET sessions are mocked; no actual exchange bytes or prospective trading.
Only positive fixtures use synthetic test clock under OS-temp.
"""
from __future__ import annotations
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

import capture_tls_v58 as tls
from build_official_day_v55 import build_verified_1m_day
from prospective_v52 import ProspectiveGateError
from trace_capture_v59 import scan_tls_bound_physical_source

class _Sock:
    def getpeercert(self):return {"subject":((("commonName","public.bybit.com"),),)}
    def version(self):return "TLSv1.3"

class _Resp:
    status=200
    def __init__(self,body):
        self.body=io.BytesIO(body)
        self.size=len(body)
    def getheader(self,name):
        return str(self.size) if name=="Content-Length" else None
    def read(self,n):return self.body.read(n)

class _Conn:
    payload=b""
    def __init__(self,host,port,timeout,context):
        if host!="public.bybit.com" or port!=443:
            raise AssertionError("wrong origin")
        if not context.check_hostname or context.verify_mode!=tls.ssl.CERT_REQUIRED:
            raise AssertionError("TLS verification disabled")
        self.sock=None
        self.connected=False
    def connect(self):
        self.sock=_Sock();self.connected=True
    def request(self,method,path,headers):
        if not self.connected or method!="GET" or not path.startswith("/spot/ETHUSDT/"):
            raise AssertionError("not connected direct TLS")
    def getresponse(self):
        self.sock=None
        return _Resp(self.payload)
    def close(self):pass

class V59TwoDayPhysicalChainTests(unittest.TestCase):
    def setUp(self):
        holder=tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root=Path(holder.name)
        self.captures=[];self.minutes=[]
        self.now=pd.Timestamp("2026-10-18T00:02:00Z")
        for idx in range(2):
            day=pd.Timestamp("2026-10-16T00:00:00Z")+pd.Timedelta(days=idx)
            sym="ETHUSDT"
            first=int(day.timestamp()*1000)
            rows=["id,timestamp,price,volume,side,rpi"]
            for i in range(1440):
                rows.append(f"id{idx}_{i},{first+i*60000},{100+idx*7+i/100:.2f},1.25,Buy,0")
            payload=gzip.compress(("\n".join(rows)+"\n").encode("utf8"))
            _Conn.payload=payload
            raw_dir=self.root/f"captured-{idx}"
            with patch.object(tls.http.client,"HTTPSConnection",_Conn),patch.object(tls,"_utc_now",return_value=self.now):
                capture=tls.capture_completed_spot_day_tls(sym,day,raw_dir,fixture_mode=True)
            self.assertEqual(capture["status"],"SYNTHETIC_TRANSPORT_TEST_ONLY")
            data_dir=self.root/f"minute-{idx}"
            built=build_verified_1m_day(sym,day,Path(capture["archive_path"]),data_dir,
                declared_source_url=capture["actual_request_url"],
                fixture_mode=True,observed_utc=self.now)
            self.assertEqual(built["status"],"SYNTHETIC_TEST_ONLY")
            self.captures.append(raw_dir/"SOURCE_TLS_RECEIPT.json")
            self.minutes.append(data_dir/"SOURCE_INTAKE_RECEIPT.json")
    def scan(self,*,tls_receipts=None,minute_receipts=None,fixture_mode=True,observed_utc=None):
        return scan_tls_bound_physical_source(
            "ETHUSDT",
            self.captures if tls_receipts is None else tls_receipts,
            self.minutes if minute_receipts is None else minute_receipts,
            decision_close_utc="2026-10-18T00:00:00Z",
            fixture_mode=fixture_mode,
            observed_utc=(self.now if fixture_mode and observed_utc is None else observed_utc))
    def corrupt_capture(self,day,field,value):
        p=self.captures[day]
        info=json.loads(p.read_text(encoding="utf8"))
        info[field]=value
        p.write_text(json.dumps(info),encoding="utf8")
    def corrupt_minute(self,day,field,value):
        p=self.minutes[day]
        info=json.loads(p.read_text(encoding="utf8"))
        info[field]=value
        p.write_text(json.dumps(info),encoding="utf8")
    def test_complete_two_day_source_chain_remains_only_research(self):
        r=self.scan()
        self.assertEqual(r.complete_verified_source_days,2)
        self.assertEqual(r.scanner.physical_independently_verified_days,2)
        self.assertEqual(r.scanner.scan.physical_source_trades,2880)
        self.assertEqual(r.scanner.scan.parent_geometry_candidates,0)
        self.assertEqual(len(r.physical_raw_archive_hashes),2)
        self.assertTrue(r.source_tls_capture_claim_consistent)
        self.assertFalse(r.external_exchange_signature_verified)
        self.assertFalse(r.independently_authenticated_offline_origin)
        self.assertFalse(r.trade_entry_enabled or r.paper_eligible or r.live_enabled)
        self.assertIsNone(r.new_pnl)
    def test_early_source_utc_decision_not_admitted(self):
        with self.assertRaisesRegex(ProspectiveGateError,"unobserved"):
            self.scan(observed_utc="2026-10-17T23:59:00Z")
    def test_missing_tls_capture_receipt(self):
        with self.assertRaisesRegex(ProspectiveGateError,"missing, extra"):
            self.scan(tls_receipts=self.captures[:1])
    def test_swapped_capture_days(self):
        with self.assertRaisesRegex(ProspectiveGateError,"source URL"):
            self.scan(tls_receipts=self.captures[::-1])
    def test_altered_http_status(self):
        self.corrupt_capture(0,"http_status",302)
        with self.assertRaisesRegex(ProspectiveGateError,"unverified or redirected"):
            self.scan()
    def test_tls_hostname_claim_off(self):
        self.corrupt_capture(1,"tls_system_trust_hostname_verification",False)
        with self.assertRaisesRegex(ProspectiveGateError,"unverified or redirected"):
            self.scan()
    def test_tls_weak_version(self):
        self.corrupt_capture(0,"tls_version","TLSv1.0")
        with self.assertRaisesRegex(ProspectiveGateError,"unverified or redirected"):
            self.scan()
    def test_source_body_changed(self):
        p=Path(json.loads(self.captures[1].read_text(encoding="utf8"))["archive_path"])
        with p.open("ab") as f:f.write(b"AFTER-CAPTURE")
        with self.assertRaisesRegex(ProspectiveGateError,"original captured archive bytes changed"):
            self.scan()
    def test_source_length_claim_wrong(self):
        self.corrupt_capture(0,"compressed_bytes",100)
        with self.assertRaisesRegex(ProspectiveGateError,"byte length differs"):
            self.scan()
    def test_raw_source_path_substitution_rejected(self):
        info=json.loads(self.captures[0].read_text(encoding="utf8"))
        self.corrupt_minute(0,"raw_path",info["archive_path"]+"-other")
        with self.assertRaisesRegex(ProspectiveGateError,"did not consume captured"):
            self.scan()
    def test_sha_disagreement_between_capture_and_minutes(self):
        self.corrupt_minute(1,"raw_sha256","0"*64)
        with self.assertRaisesRegex(ProspectiveGateError,"archive SHA mismatch"):
            self.scan()
    def test_minute_source_changed_rejected(self):
        p=Path(json.loads(self.minutes[1].read_text(encoding="utf8"))["parquet_path"])
        with p.open("ab") as f:f.write(b"TAMPERED")
        with self.assertRaisesRegex(ProspectiveGateError,"changed after verification"):
            self.scan()
    def test_production_mode_rejects_synthetic_proof(self):
        # Clock bypass is separately prohibited in production. Simulate only
        # the observed wall clock here to reach and test fixture rejection.
        from datetime import datetime,timezone
        with patch("trace_capture_v59.datetime") as clock:
            clock.now.return_value=datetime(2026,10,20,tzinfo=timezone.utc)
            with self.assertRaisesRegex(ProspectiveGateError,"origin flags inconsistent"):
                self.scan(fixture_mode=False)
    def test_real_clock_override_denied_even_with_fake_capture(self):
        with self.assertRaisesRegex(ProspectiveGateError,"clock injection forbidden"):
            self.scan(fixture_mode=False,observed_utc=self.now)
    def test_historical_capture_timestamp_forged(self):
        self.corrupt_capture(0,"captured_utc","2026-10-16T23:00:00Z")
        with self.assertRaisesRegex(ProspectiveGateError,"impossible"):
            self.scan()
    def test_invalid_url_rejected(self):
        self.corrupt_capture(0,"actual_request_host","another.exchange")
        with self.assertRaisesRegex(ProspectiveGateError,"source URL"):
            self.scan()
    def test_rejected_fake_v58_schema(self):
        self.corrupt_capture(0,"schema","unverified-declaration")
        with self.assertRaisesRegex(ProspectiveGateError,"expected V58"):
            self.scan()

if __name__=="__main__":unittest.main()
