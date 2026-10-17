"""V104 adversarial source-agreement tests; synthetic future data ONLY."""
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from research.elliott_v104_independent_challenger import challenger_v104 as v104
from research.elliott_v103_tls_capture import capture_v103 as v103
from research.elliott_v102_bybit_intake import intake_v102 as v102

FUTURE_END=v104.fixed_window()[1]
STAMP=FUTURE_END+3_600_000
MINUTE=60_000


def example(spec):
    rows=[]
    for i in range(spec["count"]):
        rows.append([str(spec["first"]+i*MINUTE),
                     "100","106","95","101","10","1000"])
    return json.dumps({
        "retCode":0,"retMsg":"OK",
        "result":{"category":"spot","symbol":spec["symbol"],
                  "list":list(reversed(rows))},
        "time":STAMP},separators=(",",":")).encode()


def envelope(spec,raw):
    page=v102.pages(spec["symbol"])[spec["index"]]
    return {
        "schema":v103.SCHEMA,
        "method":"GET","host":"api.bybit.com","port":443,
        "path_query":v103.target(page),"status":200,
        "symbol":spec["symbol"],"page":spec["index"],
        "start_utc_ms":STAMP-1000,"end_utc_ms":STAMP,
        "elapsed_monotonic_ns":1000000,
        "tls_version":"TLSv1.3","tls_host_verified":True,
        "tls_ca_chain_verified":True,
        "http_redirect_followed":False,"http_proxy_used":False,
        "peer_leaf_certificate_sha256":"a"*64,
        "content_type":"application/json","content_encoding":"identity",
        "cache_age_seconds":None,
        "response_body_sha256":v104._digest(raw),
        "response_byte_count":len(raw),
        "collector_origin":"DIRECT_PYTHON_STDLIB_CA_VERIFIED_TLS",
        "origin_proven_by_signature":False,
    }


def sidecar(meta):
    return (json.dumps(meta,sort_keys=True,indent=2)+"\n").encode()


class V104IndependentArchiveTests(unittest.TestCase):
    def setup_spec(self):
        return v104.descriptors()[-1]

    def test_single_page_synthetic_source_passes_without_certification(self):
        spec=self.setup_spec()
        raw=example(spec)
        item=v104.validate_independent_page(spec,raw,sidecar(envelope(spec,raw)))
        self.assertEqual(item["count"],160)
        self.assertFalse(item["source_signature_verified"])
        self.assertFalse(item["independent_tls_handshake_observed"])
        self.assertEqual(item["raw_sha256"],v104._digest(raw))

    def test_fixed_future_universe_and_independent_42_pages(self):
        specs=v104.descriptors()
        self.assertEqual(len(specs),42)
        self.assertEqual([x["count"] for x in specs[:21]], [1000]*20+[160])
        self.assertEqual(specs[-1]["last"]+MINUTE,FUTURE_END)
        self.assertEqual(set(x["symbol"] for x in specs),set(v104.SYMBOLS))
        self.assertEqual(v104.frozen_protocol()["data_fetched_during_v104"],0)

    def test_malicious_bearer_or_host_route_substitution_fails(self):
        spec=self.setup_spec()
        raw=example(spec)
        for field,value in (("host","localhost"),("path_query","/v5/order/create"),
                            ("tls_host_verified",False),("http_proxy_used",True),
                            ("response_byte_count",1),("status",403),
                            ("content_encoding","gzip")):
            meta=envelope(spec,raw)
            meta[field]=value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    v104.validate_independent_page(spec,raw,sidecar(meta))

    def test_duplicate_source_json_key_fails(self):
        spec=self.setup_spec()
        raw=example(spec)
        raw=raw.replace(b'"retCode":0,',b'"retCode":0,"retCode":0,',1)
        meta=envelope(spec,raw)
        with self.assertRaisesRegex(ValueError,"DUPLICATE_JSON_KEY"):
            v104.validate_independent_page(spec,raw,sidecar(meta))

    def test_duplicate_receipt_json_key_fails(self):
        spec=self.setup_spec()
        raw=example(spec)
        meta=sidecar(envelope(spec,raw)).replace(b'"host": "api.bybit.com",',
              b'"host": "api.bybit.com", "host":"evil.example",',1)
        with self.assertRaisesRegex(ValueError,"DUPLICATE_JSON_KEY"):
            v104.validate_independent_page(spec,raw,meta)

    def test_single_modified_OHLC_row_refused_even_with_recomputed_hash(self):
        spec=self.setup_spec()
        payload=json.loads(example(spec))
        payload["result"]["list"][1][2]="0"
        raw=json.dumps(payload,separators=(",",":")).encode()
        with self.assertRaisesRegex(ValueError,"INVALID_OHLC"):
            v104.validate_independent_page(spec,raw,sidecar(envelope(spec,raw)))

    def test_shuffled_reverse_order_refused(self):
        spec=self.setup_spec()
        payload=json.loads(example(spec))
        rows=payload["result"]["list"]
        rows[0],rows[1]=rows[1],rows[0]
        raw=json.dumps(payload,separators=(",",":")).encode()
        with self.assertRaisesRegex(ValueError,"WRONG_ORDER"):
            v104.validate_independent_page(spec,raw,sidecar(envelope(spec,raw)))

    def test_wrong_symbol_refused(self):
        spec=self.setup_spec()
        payload=json.loads(example(spec))
        payload["result"]["symbol"]="BTCUSDT"
        raw=json.dumps(payload,separators=(",",":")).encode()
        with self.assertRaisesRegex(ValueError,"SYMBOL_MISMATCH"):
            v104.validate_independent_page(spec,raw,sidecar(envelope(spec,raw)))

    def test_recomputed_raw_with_old_receipt_hash_refused(self):
        spec=self.setup_spec()
        raw=example(spec)
        meta=envelope(spec,raw)
        with self.assertRaisesRegex(ValueError,"SIDE_CAR_CONTRADICTS"):
            v104.validate_independent_page(spec,raw+b" ",sidecar(meta))

    def test_incomplete_archive_predeadline_fails_without_opening_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(v104,"datetime",wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,10,17,tzinfo=timezone.utc)
                with self.assertRaisesRegex(ValueError,"NO_SOURCE_IO"):
                    v104.audit_archive_independent(Path(tmp))

    def test_foreign_or_missing_archive_members_fail_after_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/"foreign.txt").write_text("untrusted")
            with patch.object(v104,"datetime",wraps=datetime) as clock:
                clock.now.return_value=datetime(2026,12,1,tzinfo=timezone.utc)
                with self.assertRaisesRegex(ValueError,"MISSING_OR_EXTRA"):
                    v104.audit_archive_independent(path)

    def test_frozen_protocol_is_immutable_and_no_source_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"V104_PROTOCOL.json"
            one=v104.freeze_protocol(dest)
            self.assertEqual(one,v104.freeze_protocol(dest))
            self.assertEqual(one["sha256"],v104._digest(dest.read_bytes()))
            self.assertEqual(one["real_source_rows"],0)
            dest.write_text("{}")
            with self.assertRaisesRegex(ValueError,"IMMUTABLE"):
                v104.freeze_protocol(dest)

    def test_oversold_primary_source_signature_refused(self):
        independent={"schema":v104.SCHEMA,"page_count":42,
                     "raw_plus_sidecar_files":84}
        primary={"schema":"nexus.elliott-v103-postwindow-offline-transport-audit.v1",
                 "all_capture_files_verified":84,
                 "independently_signed_by_exchange":True}
        with self.assertRaisesRegex(ValueError,"OVERSOLD"):
            v104.compare_with_primary(independent,primary)

    def test_source_claims_never_certify_trading_or_elliott(self):
        self.assertTrue(v104.RESEARCH_ONLY)
        self.assertTrue(v104.PRIOR_HOLDOUT_UNCHANGED)
        self.assertFalse(v104.MARKET_EVALUATION_ENABLED)
        self.assertFalse(v104.CHALLENGER_TRADE_ENABLED)
        self.assertFalse(v104.PAPER_ELIGIBLE)
        self.assertFalse(v104.LIVE_ENABLED)

    def test_second_source_parser_with_first_agree_on_fake_complete_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for spec in v104.descriptors():
                raw=example(spec)
                stem=spec["stem"]
                (folder/(stem+".raw.json")).write_bytes(raw)
                (folder/(stem+".receipt.json")).write_bytes(
                    sidecar(envelope(spec,raw)))
            with patch.object(v104,"datetime",wraps=datetime) as clock_v104:
                clock_v104.now.return_value=datetime(2026,12,1,tzinfo=timezone.utc)
                secondary=v104.audit_archive_independent(folder)
            with patch.object(v103,"now_utc_ms",return_value=STAMP):
                with patch.object(v102,"datetime",wraps=datetime) as clock_v102:
                    clock_v102.now.return_value=datetime(2026,12,1,tzinfo=timezone.utc)
                    primary=v103.audit_directory(folder)
            comparison=v104.compare_with_primary(secondary,primary)
            self.assertTrue(comparison["independent_parsers_agree_on_full_1m_candles"])
            self.assertTrue(comparison["independent_parsers_agree_on_raw_and_sidecar_bytes"])
            self.assertEqual(secondary["page_count"],42)
            self.assertEqual(secondary["raw_plus_sidecar_files"],84)
            self.assertFalse(comparison["bybit_cryptographic_source_authenticity_proven"])
            self.assertEqual(comparison["orders"],0)
            primary["source_digest_by_symbol"]["ETHUSDT"]="0"*64
            with self.assertRaisesRegex(ValueError,"DIFFERENT_RAW_MARKET"):
                v104.compare_with_primary(secondary,primary)

    def test_forged_raw_plus_forged_receipt_can_agree_without_real_authenticity(self):
        spec=self.setup_spec()
        payload=json.loads(example(spec))
        payload["result"]["list"][0][4]="102"
        forged=json.dumps(payload,separators=(",",":")).encode()
        copied_sidecar=sidecar(envelope(spec,forged))
        challenger=v104.validate_independent_page(spec,forged,copied_sidecar)
        self.assertEqual(challenger["count"],160)
        self.assertFalse(challenger["source_signature_verified"])
        self.assertFalse(challenger["independent_tls_handshake_observed"])

    def test_duplicate_locked_query_key_is_rejected(self):
        spec=self.setup_spec()
        raw=example(spec)
        meta=envelope(spec,raw)
        meta["path_query"]+="&symbol=BTCUSDT"
        with self.assertRaisesRegex(ValueError,"QUERY_MISMATCH"):
            v104.validate_independent_page(spec,raw,sidecar(meta))

    def test_sidecar_vendor_signature_overclaim_is_rejected(self):
        spec=self.setup_spec()
        raw=example(spec)
        meta=envelope(spec,raw)
        meta["origin_proven_by_signature"]=True
        with self.assertRaisesRegex(ValueError,"origin_proven_by_signature"):
            v104.validate_independent_page(spec,raw,sidecar(meta))
