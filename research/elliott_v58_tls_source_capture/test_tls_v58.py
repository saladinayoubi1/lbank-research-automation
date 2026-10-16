"""V58 direct-TLS archive capture tests, 100% mocked network, synthetic data.

No actual HTTP requests or future Bybit archive observations are made.
"""
import gzip
import io
import json
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from prospective_v52 import ProspectiveGateError
import capture_tls_v58 as mod

class FakeTLS:
    def __init__(self,valid=True,tls="TLSv1.3"):
        self.valid=valid
        self.tls=tls
    def getpeercert(self):
        return {"subject":((("commonName","public.bybit.com"),),)} if self.valid else {}
    def version(self):
        return self.tls

class FakeHTTPResponse:
    def __init__(self,body,status=200,length=None,broken=False):
        self.status=status
        self.body=io.BytesIO(body)
        self.length=len(body) if length is None else length
        self.broken=broken
    def getheader(self,key):
        return str(self.length) if key=="Content-Length" and self.length is not None else None
    def read(self,n):
        if self.broken:raise ConnectionResetError("synthetic transport interruption")
        return self.body.read(n)

class FakeHTTPSConnection:
    instances=[]
    response=None
    fake_tls=None
    def __init__(self,host,port,timeout,context):
        self.host=host;self.port=port;self.context=context
        self.sock=FakeHTTPSConnection.fake_tls or FakeTLS()
        self.requested=None
        FakeHTTPSConnection.instances.append(self)
    def request(self,verb,path,headers):
        self.requested=(verb,path,headers)
    def getresponse(self):
        return FakeHTTPSConnection.response
    def close(self):
        pass

class V58VerifiedTransportTests(unittest.TestCase):
    def setUp(self):
        holder=tempfile.TemporaryDirectory();self.addCleanup(holder.cleanup)
        self.root=Path(holder.name)
        self.target=self.root/"download-day"
        self.day="2026-10-16T00:00:00Z"
        self.frozen_now=pd.Timestamp("2026-10-17T00:01:00Z")
        rows=["id,timestamp,price,volume,side,rpi"]
        start=int(pd.Timestamp(self.day).timestamp()*1000)
        rows.extend(f"id{i},{start+i*60000},{100+i/10:.1f},1.25,Buy,0" for i in range(1440))
        self.original=("\n".join(rows)+"\n").encode("utf8")
        self.compressed=gzip.compress(self.original)
        FakeHTTPSConnection.instances=[]
        FakeHTTPSConnection.response=FakeHTTPResponse(self.compressed)
        FakeHTTPSConnection.fake_tls=None
        self.patchers=[
          patch.object(mod.http.client,"HTTPSConnection",FakeHTTPSConnection),
          patch.object(mod,"_utc_now",return_value=self.frozen_now),
        ]
        for item in self.patchers:
            item.start();self.addCleanup(item.stop)
    def build(self,**kwargs):
        return mod.capture_completed_spot_day_tls(
              "BTCUSDT",self.day,self.target,fixture_mode=True,**kwargs)
    def staging(self):
        return tuple(self.root.glob(".nexus-tls-capture-*"))
    def test_successful_verified_tls_fixture_capture(self):
        r=self.build()
        archive=self.target/"BTCUSDT_2026-10-16.csv.gz"
        self.assertTrue(archive.is_file())
        self.assertEqual(archive.read_bytes(),self.compressed)
        self.assertEqual(r["sha256"],hashlib.sha256(self.compressed).hexdigest())
        self.assertTrue(r["gzip_crc_verified"])
        self.assertFalse(r["remote_origin_tls_verified"])
        self.assertTrue(r["fixture_mode"])
        self.assertEqual(r["status"],"SYNTHETIC_TRANSPORT_TEST_ONLY")
        self.assertEqual(r["actual_request_url"],
            "https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-16.csv.gz")
        self.assertFalse(r["entry_signal"] or r["paper_eligible"] or r["live_enabled"])
        self.assertEqual(len(FakeHTTPSConnection.instances),1)
        conn=FakeHTTPSConnection.instances[0]
        self.assertEqual((conn.host,conn.port),("public.bybit.com",443))
        self.assertEqual(conn.requested[0:2],("GET","/spot/BTCUSDT/BTCUSDT_2026-10-16.csv.gz"))
        self.assertTrue(conn.context.check_hostname)
        self.assertEqual(conn.context.verify_mode,mod.ssl.CERT_REQUIRED)
        self.assertTrue((self.target/"SOURCE_TLS_RECEIPT.json").is_file())
        self.assertFalse(self.staging())
    def test_source_day_incomplete_blocks_before_https_request(self):
        self.frozen_now=pd.Timestamp("2026-10-16T23:59:00Z")
        with patch.object(mod,"_utc_now",return_value=self.frozen_now):
            with self.assertRaisesRegex(ProspectiveGateError,"not fully complete"):
                self.build()
        self.assertFalse(FakeHTTPSConnection.instances)
    def test_redirect_rejected_not_followed(self):
        FakeHTTPSConnection.response=FakeHTTPResponse(b"",status=302)
        with self.assertRaisesRegex(ProspectiveGateError,"HTTP 302"):
            self.build()
        self.assertFalse(self.target.exists())
        self.assertFalse(self.staging())
    def test_403_denied_without_side_effects(self):
        FakeHTTPSConnection.response=FakeHTTPResponse(b"",status=403)
        with self.assertRaisesRegex(ProspectiveGateError,"HTTP 403"):
            self.build()
        self.assertFalse(self.target.exists())
    def test_missing_peer_certificate_rejected(self):
        FakeHTTPSConnection.fake_tls=FakeTLS(valid=False)
        with self.assertRaisesRegex(ProspectiveGateError,"TLS certificate missing"):
            self.build()
        self.assertFalse(self.target.exists())
    def test_weak_tls_version_rejected(self):
        FakeHTTPSConnection.fake_tls=FakeTLS(tls="TLSv1.0")
        with self.assertRaisesRegex(ProspectiveGateError,"unsupported peer TLS"):
            self.build()
        self.assertFalse(self.target.exists())
    def test_truncated_content_length_rejected(self):
        FakeHTTPSConnection.response=FakeHTTPResponse(self.compressed,length=len(self.compressed)+100)
        with self.assertRaisesRegex(ProspectiveGateError,"truncated response"):
            self.build()
        self.assertFalse(self.target.exists())
        self.assertFalse(self.staging())
    def test_invalid_gzip_rejected_no_source_publication(self):
        FakeHTTPSConnection.response=FakeHTTPResponse(b"x"*256)
        with self.assertRaisesRegex(ProspectiveGateError,"not a gzip"):
            self.build()
        self.assertFalse(self.target.exists())
    def test_invalid_csv_header_rejected(self):
        payload=gzip.compress(b"wrong,field,header\n"+b"".join(f"bad-{k:08d},wrong,{k*17},not-real\n".encode("ascii") for k in range(200)))
        FakeHTTPSConnection.response=FakeHTTPResponse(payload)
        with self.assertRaisesRegex(ProspectiveGateError,"CSV header unexpected"):
            self.build()
        self.assertFalse(self.target.exists())
    def test_content_length_limit_rejected(self):
        FakeHTTPSConnection.response=FakeHTTPResponse(self.compressed,length=mod.MAX_COMPRESSED_BYTES+1)
        with self.assertRaisesRegex(ProspectiveGateError,"too large"):
            self.build()
        self.assertFalse(self.target.exists())
    def test_network_interrupt_cleans_stage(self):
        FakeHTTPSConnection.response=FakeHTTPResponse(self.compressed,broken=True)
        with self.assertRaisesRegex(ProspectiveGateError,"secure source transfer"):
            self.build()
        self.assertFalse(self.target.exists())
        self.assertFalse(self.staging())
    def test_no_overwrite_of_existing_published_evidence(self):
        self.build()
        old=(self.target/"SOURCE_TLS_RECEIPT.json").read_bytes()
        with self.assertRaisesRegex(ProspectiveGateError,"already exists"):
            self.build()
        self.assertEqual((self.target/"SOURCE_TLS_RECEIPT.json").read_bytes(),old)
    def test_fixture_cannot_write_outside_os_temp(self):
        bad=Path(tempfile.gettempdir()).resolve().parent/"nexus-eliot-v58-forbidden"
        self.assertFalse(bad.exists())
        with self.assertRaisesRegex(ProspectiveGateError,"OS temp"):
            mod.capture_completed_spot_day_tls("BTCUSDT",self.day,bad,fixture_mode=True)
        self.assertFalse(bad.exists())
    def test_historical_day_rejected(self):
        with self.assertRaisesRegex(ProspectiveGateError,"out-of-window"):
            mod.capture_completed_spot_day_tls(
                 "BTCUSDT","2026-10-08T00:00:00Z",self.target,fixture_mode=True)
        self.assertFalse(FakeHTTPSConnection.instances)

if __name__=="__main__":
    unittest.main()
