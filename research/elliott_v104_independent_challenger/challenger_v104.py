"""V104 INDEPENDENT offline raw archive adversarial audit. NO network/order API.

Alternative page parser and transport-sidecar validator not reusing V102
parse_page or V103 verify_transport_claim. Verifies cryptographic *integrity*
of retained bytes, not provider-signed authenticity of those bytes. Designed
for the immutable V101 14d future source and the V102/V103 archival contract.
V104 itself opens ZERO actual market sources and never evaluates Elliott.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from research.elliott_v101_preregistered_grammar import grammar_v101 as v101

SCHEMA="nexus.elliott-v104-independent-offline-archive-challenger.v1"
KNOWN_V101_SHA="735d942cdcbf802f6079e5435473e91b7d5b597831087ab4a7439ab04984e221"
KNOWN_V102_SHA="3e994e02d3ef1af2f7ab9a9067558dfe00accca8d191d547b8fdc951a5e9a3e6"
KNOWN_V103_SHA="6f4ca9993bb7cf086fba790dedae74ca591a62200fc6973e91e17b8ff9645da6"
CHALLENGER_TRADE_ENABLED=False
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
MARKET_EVALUATION_ENABLED=False
RESEARCH_ONLY=True
PRIOR_HOLDOUT_UNCHANGED=True
MINUTE_MS=60_000
MAX_RAW_BYTES=400000
MAX_META_BYTES=8192
BATCH_LIMIT=1000
SYMBOLS=("BTCUSDT","ETHUSDT")
PER_SYMBOL_BARS=20160
EXPECTED_PAGE_COUNT=42
EXPECTED_FILE_COUNT=84


def _digest(x:bytes)->str:
    return hashlib.sha256(x).hexdigest()


def _unique(pairs):
    d={}
    for k,v in pairs:
        if k in d:
            raise ValueError("DUPLICATE_JSON_KEY")
        d[k]=v
    return d


def _when(iso:str)->int:
    return int(datetime.fromisoformat(iso.replace("Z","+00:00")).timestamp()*1000)


def fixed_window()->tuple[int,int]:
    if v101.prereg_sha()!=KNOWN_V101_SHA:
        raise ValueError("V101_PREREGISTRATION_HASH_MISMATCH")
    start,end=_when(v101.WINDOW_START_UTC),_when(v101.WINDOW_END_EXCLUSIVE_UTC)
    if (start%MINUTE_MS or end-start!=PER_SYMBOL_BARS*MINUTE_MS
        or tuple(v101.PAIRS)!=SYMBOLS):
        raise ValueError("FUTURE_WINDOW_OR_SYMBOLS_CHANGED")
    return start,end


def descriptors()->list[dict]:
    start,end=fixed_window()
    all_pages=[]
    for symbol in SYMBOLS:
        for index,offset in enumerate(range(0,PER_SYMBOL_BARS,BATCH_LIMIT)):
            n=min(BATCH_LIMIT,PER_SYMBOL_BARS-offset)
            first=start+offset*MINUTE_MS
            last=first+(n-1)*MINUTE_MS
            if last>=end:
                raise ValueError("SOURCE_WINDOW_OVERFLOW")
            all_pages.append({
                "symbol":symbol,"index":index,"count":n,
                "first":first,"last":last,
                "stem":f"{symbol}-{index:02d}",
            })
    if len(all_pages)!=EXPECTED_PAGE_COUNT:
        raise ValueError("SOURCE_PLAN_PAGE_COUNT_CHANGED")
    return all_pages


def _strict_decimal(s:object)->Decimal:
    if type(s) is not str or not s or len(s)>100:
        raise ValueError("UNTRUSTED_NUMERIC_VALUE")
    try:
        d=Decimal(s)
    except (InvalidOperation,ValueError) as exc:
        raise ValueError("MALFORMED_NUMERIC_VALUE") from exc
    if not d.is_finite():
        raise ValueError("NONFINITE_NUMERIC_VALUE")
    return d


def _receipt_field(meta:dict,key:str,expected:object):
    value=meta.get(key)
    if type(value) is not type(expected) or value!=expected:
        raise ValueError("SIDE_CAR_CONTRADICTS_LOCKED_SOURCE_"+key)


def _read_json(raw:bytes,limit:int)->dict:
    if type(raw) is not bytes or not 0<len(raw)<=limit:
        raise ValueError("RAW_SOURCE_MISSING_OR_OVERSIZED")
    try:
        val=json.loads(raw.decode("utf-8"),object_pairs_hook=_unique)
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError("MALFORMED_SOURCE_JSON") from exc
    if type(val) is not dict:
        raise ValueError("EXPECTED_SOURCE_OBJECT")
    return val


def validate_independent_page(spec:dict, raw:bytes,sidecar:bytes)->dict:
    """Independent from V102/V103 parsing implementation.

    This is not a cryptographic signature verification: a forger replacing
    both raw and receipt bytes can satisfy these internal integrity checks.
    """
    actual=_read_json(raw,MAX_RAW_BYTES)
    meta=_read_json(sidecar,MAX_META_BYTES)
    _receipt_field(meta,"schema","nexus.elliott-v103-future-https-transport-archive.v1")
    for key,expected in (
        ("host","api.bybit.com"),("method","GET"),("port",443),
        ("status",200),("symbol",spec["symbol"]),("page",spec["index"]),
        ("tls_host_verified",True),("tls_ca_chain_verified",True),
        ("http_proxy_used",False),("http_redirect_followed",False),
        ("content_type","application/json"),("content_encoding","identity"),
        ("response_body_sha256",_digest(raw)),("response_byte_count",len(raw)),
    ):
        _receipt_field(meta,key,expected)
    route=meta.get("path_query")
    if type(route) is not str:
        raise ValueError("SOURCE_TARGET_MISSING")
    u=urlsplit(route)
    if u.scheme or u.netloc or u.fragment or u.path!="/v5/market/kline":
        raise ValueError("SOURCE_TARGET_CHANGED")
    q=parse_qs(u.query,keep_blank_values=True,strict_parsing=True)
    expected_q={
        "category":["spot"],"symbol":[spec["symbol"]],"interval":["1"],
        "start":[str(spec["first"])],"end":[str(spec["last"])],
        "limit":[str(spec["count"])],
    }
    if q!=expected_q:
        raise ValueError("SOURCE_REQUEST_QUERY_MISMATCH")
    if meta.get("tls_version") not in ("TLSv1.2","TLSv1.3"):
        raise ValueError("TLS_PROTOCOL_DOWNGRADE")
    cert=meta.get("peer_leaf_certificate_sha256")
    if type(cert) is not str or re.fullmatch(r"[0-9a-f]{64}",cert) is None:
        raise ValueError("TLS_CERTIFICATE_DIGEST_INVALID")
    _receipt_field(meta,"origin_proven_by_signature",False)
    begin,end=meta.get("start_utc_ms"),meta.get("end_utc_ms")
    elapsed=meta.get("elapsed_monotonic_ns")
    _,window_end=fixed_window()
    if (type(begin) is not int or type(end) is not int or type(elapsed) is not int
        or elapsed<0 or not window_end<=begin<=end
        or end<spec["last"]+MINUTE_MS):
        raise ValueError("UNSUPPORTED_OR_FUTURE_RECEIPT_TIMESTAMP")
    if meta.get("cache_age_seconds") not in (None,0):
        raise ValueError("CACHED_SOURCE_CANNOT_BE_VERIFIED")
    if (type(actual.get("retCode")) is not int or actual["retCode"]!=0
        or type(actual.get("retMsg")) is not str):
        raise ValueError("BYBIT_RETURNED_ERROR_NOT_SOURCE")
    result=actual.get("result")
    if (type(result) is not dict or result.get("category")!="spot"
        or result.get("symbol")!=spec["symbol"]):
        raise ValueError("BYBIT_RESULT_CATEGORY_OR_SYMBOL_MISMATCH")
    data=result.get("list")
    if type(data) is not list or len(data)!=spec["count"]:
        raise ValueError("BYBIT_PAGE_TRUNCATED_OR_DUPLICATED")
    server_ms=actual.get("time")
    if server_ms is not None and (
        type(server_ms) is not int or server_ms<spec["last"]+MINUTE_MS):
        raise ValueError("BYBIT_SERVER_TIME_STALE")
    normalized=[]
    for i,row in enumerate(reversed(data)):
        if type(row) is not list or len(row)!=7 or any(type(x) is not str for x in row):
            raise ValueError("MALFORMED_PHYSICAL_OHLC_ROW")
        expected=spec["first"]+i*MINUTE_MS
        if (not row[0].isascii() or not row[0].isdigit()
            or row[0]!=str(expected)):
            raise ValueError("BYBIT_MINUTE_GAP_DUPLICATE_OR_WRONG_ORDER")
        o,h,l,c,vol,turn=map(_strict_decimal,row[1:])
        if (not 0<l<=o<=h or not l<=c<=h or vol<0 or turn<0):
            raise ValueError("INVALID_OHLC_PRICE_OR_VOLUME")
        normalized.append([expected,str(o),str(h),str(l),str(c),str(vol),str(turn)])
    return {
        "symbol":spec["symbol"],"page":spec["index"],"count":len(normalized),
        "raw_sha256":_digest(raw),"receipt_sha256":_digest(sidecar),
        "leaf_digest_claimed":cert,
        "candles":normalized,
        "source_signature_verified":False,
        "independent_tls_handshake_observed":False,
    }


def audit_archive_independent(folder:Path)->dict:
    """Second implementation: use raw V103 archive files, no V102 parser.

    Deliberately WAIT until collection window closes *before filesystem IO*.
    This audit neither establishes chain-of-custody against a malicious
    machine nor samples remote market data; its result is INTERNAL_ONLY.
    """
    _,limit=fixed_window()
    if int(datetime.now(timezone.utc).timestamp()*1000)<limit:
        raise ValueError("FUTURE_WINDOW_NOT_CLOSED_NO_SOURCE_IO")
    if not isinstance(folder,Path) or not folder.is_dir() or folder.is_symlink():
        raise ValueError("MISSING_OR_UNTRUSTED_ORIGINAL_ARCHIVE")
    page_specs=descriptors()
    expected={suffix for spec in page_specs for suffix in (
        spec["stem"]+".raw.json",spec["stem"]+".receipt.json")}
    present=set()
    for entry in folder.iterdir():
        if not entry.is_file() or entry.is_symlink():
            raise ValueError("UNEXPECTED_NONFILE_OR_LINK_IN_SOURCE")
        present.add(entry.name)
    if present!=expected:
        raise ValueError("SOURCE_ARCHIVE_MISSING_OR_EXTRA_MEMBERS")
    per_symbol={symbol:[] for symbol in SYMBOLS}
    detail=[]
    for spec in page_specs:
        raw_path=folder/(spec["stem"]+".raw.json")
        receipt_path=folder/(spec["stem"]+".receipt.json")
        if raw_path.stat().st_size>MAX_RAW_BYTES or receipt_path.stat().st_size>MAX_META_BYTES:
            raise ValueError("SOURCE_ARCHIVE_OVERSIZED_MEMBER")
        raw,sidecar=raw_path.read_bytes(),receipt_path.read_bytes()
        item=validate_independent_page(spec,raw,sidecar)
        per_symbol[spec["symbol"]].extend(item.pop("candles"))
        detail.append(item)
    digests={}
    for symbol,rows in per_symbol.items():
        first,last=fixed_window()
        if len(rows)!=PER_SYMBOL_BARS or any(
            record[0]!=first+i*MINUTE_MS for i,record in enumerate(rows)):
            raise ValueError("FULL_PERIOD_INCOMPLETE_OR_REORDERED")
        if rows[-1][0]+MINUTE_MS!=last:
            raise ValueError("FULL_PERIOD_WRONG_END")
        encoded=json.dumps(rows,ensure_ascii=False,separators=(",",":")).encode()
        digests[symbol]=_digest(encoded)
    return {
        "schema":SCHEMA,"status":"INDEPENDENT_FORMAT_AND_INTERNAL_INTEGRITY_ONLY",
        "v101_preregistration_sha256":KNOWN_V101_SHA,
        "v102_source_plan_sha256":KNOWN_V102_SHA,
        "v103_capture_protocol_sha256":KNOWN_V103_SHA,
        "page_count":len(detail),"raw_plus_sidecar_files":len(present),
        "per_symbol_full_close_candle_rows":{symbol:len(per_symbol[symbol])
                                              for symbol in SYMBOLS},
        "per_symbol_7field_canonical_sha256":digests,
        "page_evidence":detail,
        "independently_observed_TLS_exchange_origin":False,
        "cryptographic_Bybit_payload_signature_verified":False,
        "replaced_raw_and_receipt_collusion_detected":False,
        "retrospective_tuning_allowed":False,
        "pattern_position_certified":False,
        "elliott_wave_certified":False,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"orders":0,"net_pnl":None,
    }


def compare_with_primary(independent:dict,primary:dict)->dict:
    """Match V104 independently parsed bytes with a V103 first-pass report.

    A match proves *agreement of two programs examining the same files*,
    NOT independent observations of Bybit or TLS handshake. A discrepancy
    blocks promotion. Does not rerun any algorithm or permit trading.
    """
    if (type(independent) is not dict or independent.get("schema")!=SCHEMA or
        type(primary) is not dict or
        primary.get("schema")!="nexus.elliott-v103-postwindow-offline-transport-audit.v1"):
        raise ValueError("WRONG_OR_MISSING_TWO_AUDITOR_RECEIPTS")
    if (independent.get("page_count")!=EXPECTED_PAGE_COUNT or
        independent.get("raw_plus_sidecar_files")!=EXPECTED_FILE_COUNT or
        primary.get("all_capture_files_verified")!=EXPECTED_FILE_COUNT or
        primary.get("independently_signed_by_exchange") is not False):
        raise ValueError("INCOMPLETE_OR_OVERSOLD_AUDITOR_SOURCE")
    if independent["per_symbol_7field_canonical_sha256"]!=primary.get(
        "source_digest_by_symbol"):
        raise ValueError("DIFFERENT_RAW_MARKET_CANDLE_DIGESTS")
    independent_pages={(x["symbol"],x["page"]):(x["raw_sha256"],x["receipt_sha256"])
                       for x in independent["page_evidence"]}
    primary_pages={(x["symbol"],x["page"]):(x["raw_sha256"],x["receipt_sha256"])
                   for x in primary.get("pages",[])}
    if (len(independent_pages)!=EXPECTED_PAGE_COUNT or
        len(primary_pages)!=EXPECTED_PAGE_COUNT or
        independent_pages!=primary_pages):
        raise ValueError("RAW_OR_RECEIPT_PAGE_DIGEST_DISAGREEMENT")
    return {
        "schema":"nexus.elliott-v104-two-parser-source-agreement.v1",
        "same_raw_archives":True,
        "independent_parsers_agree_on_full_1m_candles":True,
        "independent_parsers_agree_on_raw_and_sidecar_bytes":True,
        "independent_network_collection_count":0,
        "bybit_cryptographic_source_authenticity_proven":False,
        "elliott_pattern_certified":False,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"orders":0,
    }


def frozen_protocol()->dict:
    return {
        "schema":"nexus.elliott-v104-frozen-independent-source-challenge-plan.v1",
        "state":"OFFLINE_SECOND_PARSER_NO_MARKET_DATA_OPENED",
        "previous_v101_sha256":KNOWN_V101_SHA,
        "previous_v102_sha256":KNOWN_V102_SHA,
        "previous_v103_sha256":KNOWN_V103_SHA,
        "fixed_source":"BYBIT_PUBLIC_SPOT_ONE_MINUTE",
        "symbols":list(SYMBOLS),
        "start_utc":v101.WINDOW_START_UTC,
        "end_exclusive_utc":v101.WINDOW_END_EXCLUSIVE_UTC,
        "request_page_count":EXPECTED_PAGE_COUNT,
        "full_source_minute_count":PER_SYMBOL_BARS*len(SYMBOLS),
        "immutable_source_file_count":EXPECTED_FILE_COUNT,
        "independent_second_parser_no_v102_parse_page":True,
        "offline_second_parser_no_v103_transport_get":True,
        "all_claimed_tls_fields_challenged":True,
        "original_byte_hashes_recomputed":True,
        "source_time_and_ohlc_recomputed":True,
        "cross_parser_hash_disagreements_block":True,
        "self_reported_tls_does_not_prove_exchange_origin":True,
        "source_signature_not_available":True,
        "data_fetched_during_v104":0,
        "real_market_patterns_evaluated":0,
        "orders":0,"profitability_not_established":True,
        "v52_unchanged":True,"live_enabled":False,
    }


def freeze_protocol(destination:Path)->dict:
    if not isinstance(destination,Path):
        raise ValueError("explicit frozen research file path required")
    raw=(json.dumps(frozen_protocol(),sort_keys=True,indent=2)+"\n").encode()
    if destination.exists():
        if destination.read_bytes()!=raw:
            raise ValueError("IMMUTABLE_V104_PROTOCOL_DIFFERS")
    else:
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(raw)
    return {"status":"OFFLINE_SECOND_OBSERVER_READY_NOT_MARKET_TESTED",
            "sha256":_digest(raw),"real_source_rows":0,
            "trades":0}


def main()->None:
    import argparse
    arg=argparse.ArgumentParser()
    arg.add_argument("--mode",choices=("status","audit"),default="status")
    arg.add_argument("--archive",type=Path)
    cfg=arg.parse_args()
    if cfg.mode=="status":
        obj={"status":"BLOCKED_FUTURE_WINDOW" if datetime.now(
            timezone.utc).timestamp()*1000<fixed_window()[1] else
            "POSTWINDOW_OFFLINE_ARCHIVE_REQUIRED",
            "V104_source_fetched":0,"V104_market_patterns_assessed":0,
            "orders":0,"live_enabled":False}
    else:
        if cfg.archive is None:
            arg.error("explicit archived source path required")
        obj=audit_archive_independent(cfg.archive)
    print(json.dumps(obj,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
