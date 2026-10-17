"""V103 synthetic offline source/HTTPS receipt attack tests; no real socket."""
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch

from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v103_tls_capture import capture_v103 as v103

MIN=60000
END=v102.locked_range()[1]
AFTER=END+7200000


def response(page):
    rows=[]
    for i in range(page.count):
        rows.append([str(page.start_ms+i*MIN),"100","105","95","101","10","1000"])
    return json.dumps({
        "retCode":0,"retMsg":"OK",
        "result":{"category":"spot","symbol":page.symbol,
                  "list":list(reversed(rows))},
        "time":AFTER
    },separators=(",",":")).encode()


def metadata(page,raw):
    return {
        "schema":v103.SCHEMA,"method":"GET","host":"api.bybit.com",
        "port":443,"path_query":v103.target(page),"status":200,
        "symbol":page.symbol,"page":page.index,
        "start_utc_ms":AFTER-60000,"end_utc_ms":AFTER,
        "elapsed_monotonic_ns":2000000,"tls_version":"TLSv1.3",
        "tls_host_verified":True,"tls_ca_chain_verified":True,
        "http_redirect_followed":False,"http_proxy_used":False,
        "peer_leaf_certificate_sha256":"a"*64,
        "content_type":"application/json","content_encoding":"identity",
        "cache_age_seconds":None,
        "http_date":"Tue, 01 Dec 2026 02:00:00 GMT",
        "response_body_sha256":v102.sha(raw),"response_byte_count":len(raw),
        "collector_origin":"DIRECT_PYTHON_STDLIB_CA_VERIFIED_TLS",
        "origin_proven_by_signature":False,
    }


def last_page():
    return v102.pages("BTCUSDT")[-1]


class SyntheticTransportEvidenceTests(unittest.TestCase):
    def test_real_future_capture_does_not_start_a_network_session_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v103,"now_utc_ms",return_value=END-1):
                with patch.object(v103.http.client,"HTTPSConnection") as net:
                    with self.assertRaisesRegex(ValueError,"NO_NETWORK"):
                        v103.capture_future(Path(tmp),Path(tmp))
                    net.assert_not_called()

    def test_predeadline_transport_get_never_calls_socket_or_dns(self):
        with patch.object(v103,"now_utc_ms",return_value=END-1):
            with patch.object(v103.http.client,"HTTPSConnection") as net:
                with self.assertRaisesRegex(ValueError,"NO_NETWORK"):
                    v103.transport_get(last_page())
                net.assert_not_called()

    def test_correct_offline_page_sidecar_is_necessary_not_source_signature(self):
        p=last_page();raw=response(p)
        verdict=v103.verify_transport_claim(p,raw,metadata(p,raw))
        self.assertEqual(verdict["api_kline_validation"],"STRICT_PAGE_PASS")
        self.assertFalse(verdict["provider_signed_source"])
        self.assertFalse(verdict["origin_authenticity_independently_proven"])
        self.assertTrue(verdict["collector_metadata_self_reported"])

    def test_direct_host_and_request_identity_not_alterable(self):
        p=last_page();raw=response(p)
        for key,value in (("host","evil.example"),("path_query","/v5/order"),
                          ("method","POST"),("port",80),("status",302),
                          ("symbol","ETHUSDT"),("page",0)):
            bad=metadata(p,raw);bad[key]=value
            with self.subTest(field=key):
                with self.assertRaisesRegex(ValueError,"capture field"):
                    v103.verify_transport_claim(p,raw,bad)

    def test_tls_security_downgrade_rejected(self):
        p=last_page();raw=response(p)
        for key,value in (("tls_host_verified",False),
                          ("tls_ca_chain_verified",False),
                          ("tls_version","TLSv1.1"),
                          ("http_proxy_used",True),
                          ("http_redirect_followed",True),
                          ("peer_leaf_certificate_sha256","spoof")):
            bad=metadata(p,raw);bad[key]=value
            with self.subTest(field=key):
                with self.assertRaises(ValueError):
                    v103.verify_transport_claim(p,raw,bad)

    def test_response_mutation_without_sidecar_update_is_detected(self):
        p=last_page();raw=response(p);met=metadata(p,raw)
        with self.assertRaisesRegex(ValueError,"capture field"):
            v103.verify_transport_claim(p,raw+b" ",met)

    def test_http_cache_or_compressed_payload_rejected(self):
        p=last_page();raw=response(p)
        for key,value in (("cache_age_seconds",12),
                          ("content_encoding","gzip"),
                          ("content_type","text/html")):
            bad=metadata(p,raw);bad[key]=value
            with self.assertRaises(ValueError):
                v103.verify_transport_claim(p,raw,bad)

    def test_receipt_before_candle_closes_rejected(self):
        p=last_page();raw=response(p);bad=metadata(p,raw)
        bad["end_utc_ms"]=p.last_start_ms
        bad["start_utc_ms"]=p.last_start_ms-MIN
        with self.assertRaisesRegex(ValueError,"NO_NETWORK"):
            v103.verify_transport_claim(p,raw,bad)

    def test_receipt_before_total_future_window_rejected(self):
        p=last_page();raw=response(p);bad=metadata(p,raw)
        bad["start_utc_ms"]=END-1
        with self.assertRaisesRegex(ValueError,"NO_NETWORK"):
            v103.verify_transport_claim(p,raw,bad)

    def test_unverified_body_rejected_even_with_plausible_tls(self):
        p=last_page();raw=response(p);bad=metadata(p,raw)
        changed=json.loads(raw)
        changed["result"]["list"][0][4]="NaN"
        mutant=json.dumps(changed,separators=(",",":")).encode()
        bad["response_body_sha256"]=v102.sha(mutant)
        bad["response_byte_count"]=len(mutant)
        with self.assertRaises(ValueError):
            v103.verify_transport_claim(p,mutant,bad)

    def test_no_overwrite_immutable_page_archive(self):
        p=last_page();raw=response(p);met=metadata(p,raw)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            receipt=v103.store_capture(directory,p,raw,met)
            self.assertEqual(receipt["raw_sha256"],v102.sha(raw))
            self.assertEqual(len(list(directory.iterdir())),2)
            with self.assertRaisesRegex(ValueError,"no overwrite"):
                v103.store_capture(directory,p,raw,met)
            self.assertEqual((directory/v103._filenames(p)[0]).read_bytes(),raw)

    def test_incomplete_single_page_archive_fails_closed(self):
        p=last_page();raw=response(p)
        with tempfile.TemporaryDirectory() as tmp:
            v103.store_capture(Path(tmp),p,raw,metadata(p,raw))
            with patch.object(v103,"now_utc_ms",return_value=AFTER):
                with self.assertRaisesRegex(ValueError,"missing/unexpected"):
                    v103.audit_directory(Path(tmp))

    def test_full_42_page_synthetic_archive_integrity_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            for symbol in v102.v101.PAIRS:
                for p in v102.pages(symbol):
                    raw=response(p)
                    v103.store_capture(directory,p,raw,metadata(p,raw))
            with patch.object(v103,"now_utc_ms",return_value=AFTER):
                with patch.object(v102,"datetime",wraps=datetime) as clock:
                    clock.now.return_value=datetime(2026,12,1,tzinfo=timezone.utc)
                    audit=v103.audit_directory(directory)
            self.assertEqual(audit["all_capture_files_verified"],84)
            self.assertEqual(len(audit["pages"]),42)
            self.assertTrue(audit["raw_and_receipts_integrity_check"])
            self.assertFalse(audit["independently_signed_by_exchange"])
            self.assertFalse(audit["receipt_chain_cryptographically_authenticated"])
            self.assertEqual(len(audit["source_digest_by_symbol"]),2)
            self.assertEqual(audit["candidate_trades"],0)
            self.assertFalse(audit["paper_eligible"])

    def test_read_only_manifest_does_not_grant_trading(self):
        self.assertTrue(v103.RESEARCH_ONLY)
        self.assertTrue(v103.V52_UNCHANGED)
        self.assertFalse(v103.ENTRY_SIGNAL)
        self.assertFalse(v103.LIVE_ENABLED)
        self.assertFalse(v103.PAPER_ELIGIBLE)
        self.assertIsNone(v103.ORDER_ADAPTER)
        self.assertEqual(v103.ELLIOTT_PROVEN,0)

    def test_direct_future_https_mock_observes_tls_validation_not_authentication(self):
        """Entire network is mocked; proves wiring, not actual Bybit TLS."""
        p=last_page();raw=response(p)
        observed={}
        class MockSocket:
            def getpeercert(self,binary_form=False):
                self_binary=binary_form
                if not self_binary:
                    raise AssertionError("binary DER certificate expected")
                return b"synthetic-fake-TLS-cert"
            def version(self):
                return "TLSv1.3"
        class MockContext:
            verify_mode=v103.ssl.CERT_REQUIRED
            check_hostname=True
            minimum_version=v103.ssl.TLSVersion.TLSv1_2
        class MockReply:
            status=200
            def getheader(self,name):
                return {"Content-Type":"application/json",
                        "Content-Encoding":"identity",
                        "Age":"0","Date":"synthetic date"}.get(name)
            def read(self,size):
                self_read=size
                if self_read!=v102.MAX_RAW_PAGE_BYTES+1:
                    raise AssertionError("must enforce bounded response read")
                return raw
        class MockConnection:
            def __init__(self,host,port,timeout,context):
                self.sock=MockSocket()
                observed["destination"]=(host,port,timeout)
                self.context=context
            def connect(self):
                observed["connected"]=True
            def request(self,method,route,headers):
                observed["request"]=(method,route,headers)
            def getresponse(self):
                return MockReply()
            def close(self):
                observed["closed"]=True
        with patch.object(v103,"now_utc_ms",side_effect=[AFTER-5000,AFTER-3000,AFTER]):
            with patch.object(v103.ssl,"create_default_context",return_value=MockContext()):
                with patch.object(v103.ssl,"SSLSocket",MockSocket):
                    with patch.object(v103.http.client,"HTTPSConnection",MockConnection):
                        data,claim=v103.transport_get(p)
        self.assertEqual(data,raw)
        self.assertEqual(observed["destination"][:2],("api.bybit.com",443))
        self.assertEqual(observed["request"][0],"GET")
        self.assertEqual(observed["request"][1],v103.target(p))
        self.assertNotIn("Authorization",observed["request"][2])
        self.assertTrue(observed["connected"])
        self.assertTrue(observed["closed"])
        self.assertTrue(claim["tls_ca_chain_verified"])
        self.assertFalse(claim["origin_proven_by_signature"])
        self.assertEqual(claim["response_body_sha256"],v102.sha(raw))

    def test_archived_receipt_tamper_is_rejected_even_if_raw_is_unchanged(self):
        p=last_page();raw=response(p)
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            v103.store_capture(directory,p,raw,metadata(p,raw))
            receipt_path=directory/v103._filenames(p)[1]
            altered=json.loads(receipt_path.read_text())
            altered["host"]="fake-exchange.example"
            receipt_path.write_text(json.dumps(altered))
            with self.assertRaisesRegex(ValueError,"capture field"):
                v103.verify_transport_claim(p,raw,json.loads(receipt_path.read_text()))

    def test_later_source_42_page_audit_blocks_before_real_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v103,"now_utc_ms",return_value=END-1):
                with self.assertRaisesRegex(ValueError,"NO_NETWORK"):
                    v103.audit_directory(Path(tmp))

    def test_verifier_rejects_fabricated_tls_cert_digest_type(self):
        p=last_page();raw=response(p);bad=metadata(p,raw)
        bad["peer_leaf_certificate_sha256"]=0
        with self.assertRaisesRegex(ValueError,"digest"):
            v103.verify_transport_claim(p,raw,bad)

    def test_verify_repository_frozen_plan_and_status_no_network(self):
        root=Path(__file__).resolve().parents[1]
        frozen=v103.freeze_contract(root)
        self.assertEqual(frozen["total_pages"],42)
        self.assertEqual(frozen["expected_total_1m_candles"],40320)
        with patch.object(v103,"now_utc_ms",return_value=END-1):
            s=v103.readiness(root)
        self.assertEqual(s["status"],
                         "BLOCKED_BEFORE_PREREGISTERED_WINDOW_COMPLETES")
        self.assertTrue(s["no_network_executed"])
        self.assertEqual(s["market_data_fetched"],0)

    def test_static_capture_protocol_freeze_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"V103_FROZEN_CAPTURE_PROTOCOL.json"
            a=v103.freeze_protocol(path)
            self.assertEqual(a,v103.freeze_protocol(path))
            self.assertEqual(a["sha256"],v102.sha(path.read_bytes()))
            data=json.loads(path.read_text())
            self.assertEqual(data["request_count"],42)
            self.assertEqual(data["full_raw_file_receipt_count_required"],84)
            self.assertTrue(data["self_reported_receipts_not_independent_crypto_attestation"])
            self.assertEqual(data["web_requests_made_during_protocol_freeze"],0)
            path.write_text("tampered")
            with self.assertRaisesRegex(ValueError,"modified"):
                v103.freeze_protocol(path)
