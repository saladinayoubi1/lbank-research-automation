"""V103 FUTURE-GATED public Bybit Spot HTTPS archival capture and offline audit.

No market endpoints are called by module import, --status, or test cases.
Only explicit --capture can perform future network GET, strictly AFTER the
entire V101 protected Nov 16-29 UTC window is over. Never uses credentials,
order APIs, futures, Live, Demo, or existing V52 research observations.

TLS verification gives transport authenticity under the host trust store,
NOT an exchange-signed market payload or a cryptographically attested log.
All stored sidecars are locally self-reported and cannot independently prove
that a collector was honest. Fail closed on spoofed/missing metadata.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102

SCHEMA="nexus.elliott-v103-future-https-transport-archive.v1"
HOST="api.bybit.com"
PORT=443
PATH="/v5/market/kline"
METHOD="GET"
TLS_PROTOCOLS=("TLSv1.2","TLSv1.3")
USER_AGENT="NEXUS-Research-V103-PublicSpot/1.0"
REQUEST_TIMEOUT_SECONDS=15
V102_PLAN_REL="docs/evidence/elliott-v102-bybit-future-intake-20261017/V102_FROZEN_REQUEST_PLAN.json"
V102_PLAN_SHA="3e994e02d3ef1af2f7ab9a9067558dfe00accca8d191d547b8fdc951a5e9a3e6"
V102_COMMIT="79d31cbae475c08bb74c4d25f17f25f1746a06e8"
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True
ELLIOTT_PROVEN=0


def now_utc_ms()->int:
    return int(datetime.now(timezone.utc).timestamp()*1000)


def freeze_contract(repo_root:Path)->dict:
    """Read locked Git-tracked plan and independent original V101 rulebook."""
    if not isinstance(repo_root,Path):
        raise ValueError("repo root Path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    pinned=v93.immutable_receipt(
        V102_PLAN_REL,V102_PLAN_SHA,V102_COMMIT,v102.SCHEMA)
    if (pinned!=v102.plan()
        or v101.prereg_sha()!=v102.PREREG_V101_SHA):
        raise ValueError("V101/V102 immutable plan or source ancestry diverged")
    if (repo_root/V102_PLAN_REL).read_bytes()!=v102.plan_bytes():
        raise ValueError("V102 working copy differs from immutably frozen plan")
    return pinned


def future_gate(now_ms:int)->None:
    if type(now_ms) is not int:
        raise ValueError("trusted UTC instant must be integer")
    _,end=v102.locked_range()
    if now_ms<end:
        raise ValueError("FUTURE_WINDOW_NOT_COMPLETE_NO_NETWORK_ALLOWED")


def target(page:v102.Page)->str:
    if type(page) is not v102.Page:
        raise ValueError("typed frozen V102 page required")
    query=urlencode(v102.request_params(page))
    return PATH+"?"+query


def filename(page:v102.Page)->str:
    v102.request_params(page)
    return page.symbol+"-"+format(page.index,"02d")


def verify_transport_claim(page:v102.Page,raw:bytes,meta:dict)->dict:
    """Strict offline metadata schema + raw byte correlation.

    NOTE: audit cannot independently reconstruct TLS handshake; the only
    observation of it is a truthful verified collector implementation.
    This check is necessary, explicitly NOT sufficient source assurance.
    """
    v102.request_params(page)
    if type(meta) is not dict:
        raise ValueError("untrusted missing capture sidecar")
    expected={
        "schema":SCHEMA,
        "method":METHOD,"host":HOST,"port":PORT,
        "path_query":target(page),
        "status":200,"tls_host_verified":True,
        "tls_ca_chain_verified":True,
        "http_redirect_followed":False,
        "http_proxy_used":False,
        "response_body_sha256":v102.sha(raw),
        "symbol":page.symbol,"page":page.index,
        "content_encoding":"identity",
    }
    for field,value in expected.items():
        if type(meta.get(field)) is not type(value) or meta[field]!=value:
            raise ValueError("missing or altered TLS/HTTP capture field: "+field)
    if meta.get("tls_version") not in TLS_PROTOCOLS:
        raise ValueError("unsupported HTTPS protocol")
    cert=meta.get("peer_leaf_certificate_sha256")
    if (type(cert) is not str or len(cert)!=64 or
        any(x not in "0123456789abcdef" for x in cert)):
        raise ValueError("no digest of verified TLS peer certificate")
    if meta.get("content_type") not in ("application/json",):
        raise ValueError("non-JSON transport content type")
    if (type(meta.get("start_utc_ms")) is not int or
        type(meta.get("end_utc_ms")) is not int or
        type(meta.get("elapsed_monotonic_ns")) is not int or
        meta["elapsed_monotonic_ns"]<0 or
        meta["start_utc_ms"]>meta["end_utc_ms"]):
        raise ValueError("missing or impossible original receipt times")
    future_gate(meta["start_utc_ms"])
    if meta["end_utc_ms"]<page.last_start_ms+v102.v99.MINUTE:
        raise ValueError("capture precedes last closed candle")
    if (type(meta.get("response_byte_count")) is not int or
        meta["response_byte_count"]!=len(raw) or
        not 0<len(raw)<=v102.MAX_RAW_PAGE_BYTES):
        raise ValueError("raw response changed since transport")
    if meta.get("cache_age_seconds") not in (None,0):
        raise ValueError("unverified nonzero cached response age")
    rows,receipt=v102.parse_page(raw,page,meta["end_utc_ms"])
    if len(rows)!=page.count or receipt["response_raw_sha256"]!=meta["response_body_sha256"]:
        raise ValueError("transport does not match physical OHLC page")
    return {
        "symbol":page.symbol,"page":page.index,
        "raw_sha256":meta["response_body_sha256"],
        "tls_peer_sha256":cert,
        "tls_protocol":meta["tls_version"],
        "utc_received_ms":meta["end_utc_ms"],
        "api_kline_validation":"STRICT_PAGE_PASS",
        "collector_metadata_self_reported":True,
        "provider_signed_source":False,
        "origin_authenticity_independently_proven":False,
    }


def transport_get(page:v102.Page)->tuple[bytes,dict]:
    """One direct CA-validated HTTPS request; NEVER retry/redirect/proxy.

    Not called during V103 work or unit tests. Requires an explicit future
    capture invocation and the V101 period to have finished.
    """
    future_gate(now_utc_ms())  # Absolutely before any socket or DNS
    route=target(page)
    context=ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    if context.verify_mode!=ssl.CERT_REQUIRED or not context.check_hostname:
        raise ValueError("TLS identity verification unexpectedly disabled")
    connection=http.client.HTTPSConnection(
        HOST,PORT,timeout=REQUEST_TIMEOUT_SECONDS,context=context)
    import time
    begun=now_utc_ms()
    monotonic_start=time.monotonic_ns()
    try:
        connection.connect()
        socket=connection.sock
        if not isinstance(socket,ssl.SSLSocket):
            raise ValueError("unverified TLS socket")
        certificate=socket.getpeercert(binary_form=True)
        tls=socket.version()
        if not certificate or tls not in TLS_PROTOCOLS:
            raise ValueError("peer TLS evidence incomplete")
        # urllib2/system HTTP proxies are never consulted: http.client
        # opens a direct TCP socket to the predeclared api.bybit.com host.
        connection.request(METHOD,route,headers={
            "Host":HOST,
            "Accept":"application/json",
            "Accept-Encoding":"identity",
            "User-Agent":USER_AGENT,
        })
        reply=connection.getresponse()
        status=reply.status
        mime=(reply.getheader("Content-Type") or "").split(";",1)[0].strip().lower()
        encoding=(reply.getheader("Content-Encoding") or "identity").strip().lower()
        age=reply.getheader("Age")
        if status!=200:
            raise ValueError("HTTP status/redirect rejected: "+str(status))
        if mime!="application/json" or encoding!="identity":
            raise ValueError("unexpected response MIME or encoding")
        if age is not None and (not age.isdigit() or int(age)>0):
            raise ValueError("unknown or stale intermediary cache")
        raw=reply.read(v102.MAX_RAW_PAGE_BYTES+1)
        finished=now_utc_ms()
        elapsed=time.monotonic_ns()-monotonic_start
        if not 0<len(raw)<=v102.MAX_RAW_PAGE_BYTES:
            raise ValueError("empty or oversized HTTP response")
        details={
            "schema":SCHEMA,"method":METHOD,"host":HOST,
            "port":PORT,"path_query":route,"status":status,
            "symbol":page.symbol,"page":page.index,
            "start_utc_ms":begun,"end_utc_ms":finished,
            "elapsed_monotonic_ns":elapsed,
            "tls_version":tls,
            "tls_host_verified":True,
            "tls_ca_chain_verified":True,
            "http_redirect_followed":False,
            "http_proxy_used":False,
            "peer_leaf_certificate_sha256":hashlib.sha256(certificate).hexdigest(),
            "content_type":mime,"content_encoding":encoding,
            "cache_age_seconds":int(age) if age is not None else None,
            "http_date":reply.getheader("Date"),
            "response_body_sha256":v102.sha(raw),
            "response_byte_count":len(raw),
            "collector_origin":"DIRECT_PYTHON_STDLIB_CA_VERIFIED_TLS",
            "origin_proven_by_signature":False,
        }
        verify_transport_claim(page,raw,details)
        return raw,details
    finally:
        connection.close()


def _filenames(page:v102.Page)->tuple[str,str]:
    name=filename(page)
    return name+".raw.json",name+".receipt.json"


def store_capture(directory:Path,page:v102.Page,raw:bytes,metadata:dict)->dict:
    """Immutable two-file archival; crash leftovers force audit abstention.

    Written *only* by explicit capture code after future_gate. The offline
    tests pass synthetic receipt timestamps; do not imply a real TLS session.
    """
    if not isinstance(directory,Path):
        raise ValueError("explicit archive Path required")
    receipt=verify_transport_claim(page,raw,metadata)
    directory.mkdir(parents=True,exist_ok=True)
    names=_filenames(page)
    if any((directory/name).exists() for name in names):
        raise ValueError("no overwrite/unsafe resume of previously captured page")
    # One write per file; audit requires both. No files can be silently
    # overridden, and interrupted writes leave a clearly incomplete archive.
    data=json.dumps(metadata,sort_keys=True,indent=2)+"\n"
    with (directory/names[0]).open("xb") as output:
        output.write(raw)
    with (directory/names[1]).open("xb") as output:
        output.write(data.encode("utf-8"))
    return receipt


def audit_directory(directory:Path)->dict:
    """Offline repeatable hash + page + metadata audit of all 42 receipts."""
    if not isinstance(directory,Path) or not directory.is_dir():
        raise ValueError("full original raw archive directory required")
    future_gate(now_utc_ms())
    all_pages=[p for sym in v101.PAIRS for p in v102.pages(sym)]
    filenames={name for p in all_pages for name in _filenames(p)}
    actual={p.name for p in directory.iterdir() if p.is_file()}
    if filenames!=actual:
        raise ValueError("missing/unexpected complete raw files or receipts")
    raw_pages={}
    links=[]
    for page in all_pages:
        raw_file,receipt_file=(directory/n for n in _filenames(page))
        if (raw_file.stat().st_size>v102.MAX_RAW_PAGE_BYTES or
            receipt_file.stat().st_size>8192):
            raise ValueError("oversized future evidence archive member")
        raw=raw_file.read_bytes()
        sidecar=receipt_file.read_bytes()
        metadata=json.loads(sidecar.decode("utf-8"),
                            object_pairs_hook=v102._unique_object)
        accepted=verify_transport_claim(page,raw,metadata)
        raw_pages[(page.symbol,page.index)]=(raw,metadata["end_utc_ms"])
        links.append({
            "page":page.index,"symbol":page.symbol,
            "raw_file":raw_file.name,"receipt_file":receipt_file.name,
            "raw_sha256":v102.sha(raw),
            "receipt_sha256":v102.sha(sidecar),
            "claimed_tls_peer_sha256":accepted["tls_peer_sha256"],
        })
    source=v102.accept_complete_future_archive(raw_pages)
    return {
        "schema":"nexus.elliott-v103-postwindow-offline-transport-audit.v1",
        "v101_sha256":v102.PREREG_V101_SHA,
        "v102_locked_plan_sha256":V102_PLAN_SHA,
        "claimed_origin":"BYBIT_V5_PUBLIC_SPOT_CA_VERIFIED_HTTPS",
        "independently_signed_by_exchange":False,
        "receipt_chain_cryptographically_authenticated":False,
        "raw_and_receipts_integrity_check":True,
        "full_v102_ohlc_integrity":source["all_original_pages_complete"],
        "all_capture_files_verified":len(links)*2,
        "pages":links,
        "source_digest_by_symbol":{
            k:v["all_physical_7field_rows_sha256"] for k,v in source["symbols"].items()},
        "market_wave_classification_executed":False,
        "candidate_trades":0,"entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"net_pnl":None,
    }


def capture_future(directory:Path,repo_root:Path)->dict:
    """Explicit opt-in FUTURE action only; 42 direct public GET, then audit."""
    future_gate(now_utc_ms())
    freeze_contract(repo_root)
    if not isinstance(directory,Path) or (
        directory.exists() and list(directory.iterdir())):
        raise ValueError("fresh empty destination required; never overwrite existing receipt")
    captures=[]
    # No retry or silent partial-data acceptance. An outage leaves a
    # partial archive for diagnosis but never proceeds to analysis.
    for symbol in v101.PAIRS:
        for page in v102.pages(symbol):
            raw,metadata=transport_get(page)
            captures.append(store_capture(directory,page,raw,metadata))
    audit=audit_directory(directory)
    if len(captures)!=42:
        raise ValueError("incomplete collection")
    return audit


def readiness(repo_root:Path)->dict:
    frozen=freeze_contract(repo_root)
    current=now_utc_ms()
    end=v102.locked_range()[1]
    return {
        "schema":SCHEMA,
        "status":"FUTURE_ALLOWED_EXPLICIT_CAPTURE_REQUIRED"
                 if current>=end else "BLOCKED_BEFORE_PREREGISTERED_WINDOW_COMPLETES",
        "utc_now_ms":current,
        "window_end_exclusive_utc":v101.WINDOW_END_EXCLUSIVE_UTC,
        "v102_source_plan_sha256":V102_PLAN_SHA,
        "pages_expected":frozen["total_pages"],
        "source_rows_expected":frozen["expected_total_1m_candles"],
        "no_network_executed":True,
        "market_data_fetched":0,
        "market_patterns_assessed":0,
        "paper_eligible":False,
        "live_enabled":False,
    }


def main()->None:
    import argparse
    parser=argparse.ArgumentParser(description="V103 Bybit public research capture")
    parser.add_argument("--mode",choices=("status","capture","audit"),default="status")
    parser.add_argument("--repo-root",type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--capture-dir",type=Path)
    cfg=parser.parse_args()
    if cfg.mode=="status":
        result=readiness(cfg.repo_root)
    else:
        if cfg.capture_dir is None:
            parser.error("--capture-dir is required outside status")
        future_gate(now_utc_ms())
        if cfg.mode=="capture":
            result=capture_future(cfg.capture_dir,cfg.repo_root)
        else:
            freeze_contract(cfg.repo_root)
            result=audit_directory(cfg.capture_dir)
    print(json.dumps(result,indent=2,sort_keys=True))


def protocol()->dict:
    """Static commit-friendly future capture security protocol, zero network."""
    start,end=v102.locked_range()
    return {
        "schema":"nexus.elliott-v103-frozen-future-transport-protocol.v1",
        "status":"CAPTURE_CODE_PREPARED_NO_FUTURE_SOURCE_COLLECTED",
        "protected_future_window_start_ms":start,
        "protected_future_window_end_exclusive_ms":end,
        "v102_locked_plan_sha256":V102_PLAN_SHA,
        "v101_locked_rulebook_sha256":v102.PREREG_V101_SHA,
        "market_source":"Bybit V5 public Spot GET /v5/market/kline",
        "request_host":HOST,"request_path":PATH,"request_method":METHOD,
        "request_count":42,"expected_source_rows":40320,
        "trusted_collection_method":"Python stdlib direct HTTPSConnection",
        "system_CA_hostname_verification":True,
        "minimum_transport_tls_version":"TLSv1.2",
        "http_proxy_usage":False,
        "redirects_automatically_followed":False,
        "authorization_headers_used":False,
        "admission_requires_complete_future_period":True,
        "partial_archives_must_abstain":True,
        "raw_http_response_preserved_unmodified":True,
        "individual_transport_metadata_sidecar_preserved":True,
        "full_raw_file_receipt_count_required":84,
        "offline_reverification":True,
        "origin_certificate_sha256_is_not_provider_data_signature":True,
        "self_reported_receipts_not_independent_crypto_attestation":True,
        "web_requests_made_during_protocol_freeze":0,
        "real_market_data_fetched":0,
        "market_candidates_evaluated":0,
        "orders":0,"pnl":None,"entry_signal":False,
        "paper_eligible":False,"live_enabled":False,
        "v52_untouched":True,
    }


def freeze_protocol(destination:Path)->dict:
    if not isinstance(destination,Path):
        raise ValueError("frozen protocol output must be a path")
    raw=(json.dumps(protocol(),sort_keys=True,indent=2)+"\n").encode()
    if destination.exists():
        if destination.read_bytes()!=raw:
            raise ValueError("immutable V103 future capture protocol modified")
    else:
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(raw)
    return {"status":"V103_PUBLIC_HTTPS_CAPTURE_FUTURE_PLAN_ONLY",
            "sha256":v102.sha(raw),"raw_future_pages_captured":0,
            "original_market_candles_accessed":0,"orders":0}


if __name__=="__main__":
    main()
