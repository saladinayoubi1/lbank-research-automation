"""Synthetic full-day public Bybit Spot Oct22 cache reuse only after fixed live WS 4h audit."""
from __future__ import annotations
import gzip,hashlib,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from research.nexus_mr40_bybit_archive_bridge_v1 import rollup,epoch,STEP4
from research.nexus_mr40_bybit_forward_shadow_v1 import (
    reuse_oct22_only_if_archive_ws_parity_proven,EXPECTED_BRIDGE,
    EXPECTED_OCT22_WS_SHA)
from research.nexus_mr40_oct22_tick_vs_ws_reconcile_v1 import (
    reconcile,LAST_BRIDGE_BAR,URL,DAY_BEGIN)
from research.nexus_mr40_independent_closed_signal_v1 import canon

WS=["81677.3","81761.2","80927.9","81488.6","2951.920267"]


def synthetic_full_day():
    """7200 distinct public-style last sales: 1440 full minute bins and 6 full 4h bins.

    High-entropy trade IDs create a >100 KB compressed fixture for the real
    source size gate. Fixed bar #4 matches preselected actual WS OHLCV.
    """
    out=["id,timestamp,price,volume,side,rpi"]
    for minute in range(1440):
        bar=minute//240
        for sub in range(5):
            idx=minute*5+sub
            when=DAY_BEGIN+minute*60000+sub*1000
            price="82000" if bar!=4 else "81500"
            if bar==4:
                if minute==960 and sub==0:price="81677.3"
                if minute==960 and sub==1:price="81761.2"
                if minute==960 and sub==2:price="80927.9"
                if minute==1199 and sub==4:price="81488.6"
            volume="0.1"
            if minute==1199 and sub==4:volume="2832.020267"
            identity=hashlib.sha256(("TRADE-"+str(idx)).encode()).hexdigest()
            out.append(",".join((identity,str(when),price,volume,"buy","0")))
    return gzip.compress(("\n".join(out)+"\n").encode(),mtime=0)


def make_audit(raw):
    rows,meta=rollup(gzip.decompress(raw),"2026-10-22")
    assert len(rows)==6 and meta["minutes_verified"]==1440
    cross=reconcile(rows,{"ohlcv":WS},LAST_BRIDGE_BAR)
    assert cross["source_same_venue_reconciliation_pass"]
    report={
        "schema":"nexus.mr40.oct22_spot_tick_ws_reconciliation.results.v1",
        "bridge_digest":EXPECTED_BRIDGE,
        "prior_spot_WS_capture_sha256":EXPECTED_OCT22_WS_SHA,
        "native_confirm_verified_live_source":True,
        "source_validation":meta,
        "source_4h_candles":rows,
        "source_reconciliation":cross,
        "official_trade_archive":{
            "url":URL,
            "received_utc":"2026-10-23T03:00:00+00:00",
            "gz_size_bytes":len(raw),
            "gz_sha256":hashlib.sha256(raw).hexdigest(),
            "csv_sha256":hashlib.sha256(gzip.decompress(raw)).hexdigest(),
            "last_modified_header":None,
        },
        "orders_sent":0,"promote":False,
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    return report


class TestOct22SourceParityReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=synthetic_full_day()
        cls.audit=make_audit(cls.data)
        assert len(cls.data)>100000

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Simulate an eligible *future* offline audit date; actual Oct22 UTC
        # has not ended, so the production source must still fail closed.
        clock=patch("research.nexus_mr40_bybit_forward_shadow_v1.time.time",
                    return_value=epoch("2026-10-24")/1000+1000)
        clock.start()
        self.addCleanup(clock.stop)
        self.dir=Path(self.tmp.name)
        self.cache=self.dir/"Bybit_BTCUSDT_Spot_2026-10-22.csv.gz"
        self.audit_file=self.dir/"oct22_verified_source_audit.json"
        self.cache.write_bytes(self.data)
        self.write_audit(self.audit)

    def write_audit(self,body):
        self.audit_file.write_text(json.dumps(body,ensure_ascii=False,sort_keys=True)+"\n",encoding="utf8")

    def test_reuse_real_rollup_and_recomputed_spot_vs_ws_gate_without_network(self):
        old_sha=hashlib.sha256(self.cache.read_bytes()).hexdigest()
        with patch("research.nexus_mr40_bybit_forward_shadow_v1.time.time",return_value=epoch("2026-10-24")/1000+1000),patch(
            "research.nexus_mr40_bybit_forward_shadow_v1.urllib.request.urlopen",
            side_effect=AssertionError("NEVER download cached Oct22")):
            rows,metadata=reuse_oct22_only_if_archive_ws_parity_proven(self.cache,self.audit_file)
        self.assertEqual(len(rows),6)
        self.assertEqual(rows[4][1:6],WS)
        self.assertTrue(metadata["oct22_reused_without_re_download"])
        self.assertTrue(metadata["oct22_no_local_file_overwrite"])
        self.assertEqual(metadata["minutes_verified"],1440)
        self.assertEqual(hashlib.sha256(self.cache.read_bytes()).hexdigest(),old_sha)

    def test_missing_independent_audit_always_fails_closed(self):
        self.audit_file.unlink()
        with self.assertRaisesRegex(ValueError,"both_required"):
            reuse_oct22_only_if_archive_ws_parity_proven(self.cache,self.audit_file)

    def test_existing_archive_without_matching_sha_refused(self):
        self.cache.write_bytes(self.data+b"unauthorized_modified_public_archive")
        with self.assertRaisesRegex(ValueError,"gzip_sha_or_size_changed"):
            reuse_oct22_only_if_archive_ws_parity_proven(self.cache,self.audit_file)

    def test_modified_audit_cannot_claim_live_ws_success_without_digest(self):
        altered=dict(self.audit)
        altered["source_reconciliation"]=dict(self.audit["source_reconciliation"])
        altered["source_reconciliation"]["source_same_venue_reconciliation_pass"]=False
        self.write_audit(altered)
        with self.assertRaisesRegex(ValueError,"audit_digest_changed"):
            reuse_oct22_only_if_archive_ws_parity_proven(self.cache,self.audit_file)

    def test_even_self_consistent_report_denial_of_ws_parity_refuses(self):
        altered=dict(self.audit)
        altered["source_reconciliation"]=dict(self.audit["source_reconciliation"])
        altered["source_reconciliation"]["source_same_venue_reconciliation_pass"]=False
        altered.pop("digest")
        altered["digest"]=hashlib.sha256(canon(altered)).hexdigest()
        self.write_audit(altered)
        with self.assertRaisesRegex(ValueError,"parity_not_proven"):
            reuse_oct22_only_if_archive_ws_parity_proven(self.cache,self.audit_file)

    def test_audit_utc_receipt_cannot_be_spoofed_into_future(self):
        altered=dict(self.audit)
        altered["official_trade_archive"]=dict(self.audit["official_trade_archive"])
        altered["official_trade_archive"]["received_utc"]="2026-10-21T03:00:00+00:00"
        altered.pop("digest")
        altered["digest"]=hashlib.sha256(canon(altered)).hexdigest()
        self.write_audit(altered)
        with self.assertRaisesRegex(ValueError,"invalid_oct22_daily_archive_observation_clock"):
            reuse_oct22_only_if_archive_ws_parity_proven(self.cache,self.audit_file)

    def test_source_report_must_match_recomputed_full_day_rows(self):
        altered=dict(self.audit)
        altered["source_4h_candles"]=[x.copy() for x in self.audit["source_4h_candles"]]
        altered["source_4h_candles"][4][4]="81480"
        altered.pop("digest")
        altered["digest"]=hashlib.sha256(canon(altered)).hexdigest()
        self.write_audit(altered)
        with self.assertRaisesRegex(ValueError,"source_parity_changed"):
            reuse_oct22_only_if_archive_ws_parity_proven(self.cache,self.audit_file)


if __name__=="__main__":
    unittest.main()
