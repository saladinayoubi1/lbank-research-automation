"""ONE DAY, READ-ONLY source reconciliation:
Bybit BTCUSDT Spot Oct22 archived TRADE prints vs precommitted 20:00Z
independent public WSS confirmed 4h close. No private API, strategy, trades.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path

from research.nexus_mr40_bybit_archive_bridge_v1 import epoch, rollup, STEP4
from research.nexus_mr40_bybit_4h_raw_close_gate_v2 import classify_capture, canonical

PROTOCOL="nexus.mr40.bybit_oct22_tick_ws_4h_reconciliation.protocol.v1"
DAY="2026-10-22"
DAY_BEGIN=epoch(DAY)
DAY_END=epoch("2026-10-23")
URL="https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-10-22.csv.gz"
LAST_BRIDGE="f118d0affe21995f4bfa01c1b5261eb7e963d1c1d46bfb094debf28a35c3114e"
BRIDGE_ROWS_SHA="a3fe422736b0dd27342b711765e721608cb88f7ec49ef22b723d09b64acaf5a6"
LAST_BRIDGE_BAR=epoch("2026-10-21")+5*STEP4
WS_SHA="7704589ec16144ee9852fb4c8d0aeea49287346891c27f5149825e0311445a7e"
WS_GATE_DIGEST="d52988afdce73267a9a8489e516cbce20cd58707b96bf907fc79fcfe4904f30f"
FIXED_BAR_START=DAY_BEGIN+4*STEP4
MAX_GZIP=15_000_000
OHLC_USDT_TOLERANCE=D("0.01")
VOLUME_REL_TOLERANCE=D("0.001")


def reject_before_day_end(now_ms):
    if now_ms<DAY_END:
        raise ValueError("fixed_oct22_full_UTC_day_not_yet_completed_no_network")


def pinned_protocol(policy):
    assert isinstance(policy,dict)
    if (policy.get("schema")!=PROTOCOL or policy.get("archive",{}).get("url")!=URL
        or policy["archive"]["timestamp_day_start_ms"]!=DAY_BEGIN
        or policy["archive"]["timestamp_day_end_exclusive_ms"]!=DAY_END
        or policy["predefined_tolerances"]["absolute_max_per_OHLC_usdt"]!="0.01"
        or policy["predefined_tolerances"]["max_relative_base_volume_error"]!="0.001"
        or policy["historical_prefix"]["bridge_evidence_digest"]!=LAST_BRIDGE
        or policy["historical_prefix"]["previous_12_rows_digest"]!=BRIDGE_ROWS_SHA
        or policy["live_capture"]["raw_source_sha256"]!=WS_SHA
        or policy["live_capture"]["source_gate_digest"]!=WS_GATE_DIGEST
        or policy["live_capture"]["fixed_open_ms"]!=FIXED_BAR_START
        or policy["safety"]["orders"]!=0
        or policy["safety"]["promote"] is not False):
        raise ValueError("precommitted_source_reconciliation_protocol_drift")
    return policy


def verified_bridge(doc):
    if doc.get("digest")!=LAST_BRIDGE or not doc.get("bridge_source_integrity_gate_pass"):
        raise ValueError("source_bridge_status_not_pinned_pass")
    body=dict(doc)
    body.pop("digest",None)
    if hashlib.sha256(canonical(body)).hexdigest()!=LAST_BRIDGE:
        raise ValueError("source_bridge_content_digest_mismatch")
    rows=doc.get("new_4h_rows_utc_day20_21")
    if not isinstance(rows,list) or len(rows)!=12 or hashlib.sha256(canonical(rows)).hexdigest()!=BRIDGE_ROWS_SHA:
        raise ValueError("source_bridge_12_rows_changed")
    if rows[-1][0]!=LAST_BRIDGE_BAR:
        raise ValueError("source_bridge_last_candle_wrong")
    for index,row in enumerate(rows):
        if row[0]!=(rows[0][0]+index*STEP4):
            raise ValueError("source_bridge_intraday_gap")
    return rows[-1][0]


def verified_raw_ws(raw_bytes,gate):
    if hashlib.sha256(raw_bytes).hexdigest()!=WS_SHA:
        raise ValueError("not_previously_observed_unchanged_websocket_capture")
    if gate.get("digest")!=WS_GATE_DIGEST or gate.get("gate",{}).get("confirmed_4h_closed_seen") is not True:
        raise ValueError("previous_websocket_closed_source_proof_missing")
    rec=json.loads(raw_bytes)
    source=classify_capture(rec)  # strict native Boolean + distinct UTC clocks + 49 source messages
    if source.get("confirmed_4h_closed_seen") is not True or source.get("snapshots")!=49:
        raise ValueError("invalid_original_websocket_confirmation")
    confirmations=source["confirmed_source_4h_evidence"]
    if len(confirmations)!=1 or confirmations[0]["bar_start_ms"]!=FIXED_BAR_START:
        raise ValueError("ambiguous_pinned_realtime_closed_candle")
    return confirmations[0], source


def reconcile(rows,observed,bridge_last):
    if len(rows)!=6:
        raise ValueError("expected_six_complete_utc_fourhour_bars")
    times=[x[0] for x in rows]
    expected=[bridge_last+(i+1)*STEP4 for i in range(6)]
    if times!=expected:
        raise ValueError("missing_or_out_of_order_oct22_fourhour_sequence")
    if times[4]!=FIXED_BAR_START:
        raise ValueError("selected_archived_fourhour_candle_changed")
    archive=[D(str(x)) for x in rows[4][1:6]]
    ws=[D(str(x)) for x in observed["ohlcv"]]
    price_abs=[abs(archive[i]-ws[i]) for i in range(4)]
    max_vol=max(archive[4],ws[4])
    volume_abs=abs(archive[4]-ws[4])
    volume_relative=volume_abs/max_vol if max_vol>0 else None
    price_pass=all(x<=OHLC_USDT_TOLERANCE for x in price_abs)
    volume_pass=(volume_relative is not None and volume_relative<=VOLUME_REL_TOLERANCE)
    return {
        "day_utc":DAY,
        "new_4h_candle_count":len(rows),
        "all_six_contiguous_to_pinned_oct21_prefix":True,
        "same_venue_independent_sources":"Bybit BTCUSDT Spot public trades vs Bybit BTCUSDT Spot public WS",
        "chosen_fixed_candle_utc":"2026-10-22T16:00:00Z–2026-10-22T20:00:00Z",
        "archive_fixed_4h_ohlcv":[str(x) for x in archive],
        "prior_observed_ws_ohlcv":[str(x) for x in ws],
        "price_OHLC_abs_diff_usdt":[str(x) for x in price_abs],
        "base_volume_abs_diff_btc":str(volume_abs),
        "base_volume_relative_diff":str(volume_relative) if volume_relative is not None else None,
        "price_comparison_pass":price_pass,
        "volume_comparison_pass":volume_pass,
        "source_same_venue_reconciliation_pass":price_pass and volume_pass,
        "not_account_or_market_order_fill_evidence":True,
        "not_prospective_PNL_or_edge_validation":True,
        "does_not_automatically_authorize_live_MR40":True,
        "no_orders_sent":True,
    }


def load_pinned_files(protocol_path,bridge_path,ws_raw_path,ws_gate_path):
    policy=pinned_protocol(json.loads(protocol_path.read_bytes()))
    bridge=json.loads(bridge_path.read_bytes())
    prev=verified_bridge(bridge)
    raw=ws_raw_path.read_bytes()
    gate=json.loads(ws_gate_path.read_bytes())
    closed,info=verified_raw_ws(raw,gate)
    return policy,prev,closed,info


def execute(protocol_path,bridge_path,ws_raw_path,ws_gate_path,archive_path,output):
    if archive_path.exists() or output.exists():
        raise ValueError("refuse_overwrite_existing_raw_source_or_result")
    policy,prev,closed,info=load_pinned_files(protocol_path,bridge_path,ws_raw_path,ws_gate_path)
    now_ms=int(time.time()*1000)
    reject_before_day_end(now_ms)
    req=urllib.request.Request(URL,headers={"User-Agent":"NEXUS-Research-Bybit-Spot-Trade-WS-SameVenue-Reconcile"})
    # HEAD is read-only; no fallback to a different venue/domain or date.
    try:
        with urllib.request.urlopen(urllib.request.Request(URL,headers=req.headers,method="HEAD"),timeout=12) as response:
            head_status=response.status
            last_modified=response.headers.get("Last-Modified")
            compressed_length=response.headers.get("Content-Length")
    except urllib.error.HTTPError as e:
        if e.code==404:
            raise ValueError("official_oct22_archive_not_yet_published_http404") from None
        raise
    if head_status!=200:
        raise ValueError("official_oct22_archive_HEAD_not_200")
    with urllib.request.urlopen(req,timeout=35) as response:
        if response.status!=200:
            raise ValueError("official_oct22_archive_GET_not_200")
        raw=response.read(MAX_GZIP+1)
    if len(raw)>MAX_GZIP or len(raw)<100000:
        raise ValueError("official_oct22_archive_oversized_or_truncated")
    if compressed_length is not None and int(compressed_length)!=len(raw):
        raise ValueError("official_oct22_HEAD_GET_length_changed")
    csv_raw=gzip.decompress(raw)  # full CRC and length check before accepting
    rows,src=rollup(csv_raw,DAY)   # validated 1,440/1,440 1m and 6/6 4h
    if src["minutes_verified"]!=1440 or src["four_hour_candles_verified"]!=6 or not src["exact_1m_to_4h"]:
        raise ValueError("source_1m_fourhour_integrity_failed")
    comparison=reconcile(rows,closed,prev)
    result={
        "schema":"nexus.mr40.oct22_spot_tick_ws_reconciliation.results.v1",
        "protocol_sha256":hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "bridge_digest":LAST_BRIDGE,
        "prior_spot_WS_capture_sha256":WS_SHA,
        "prior_spot_WS_gate_digest":WS_GATE_DIGEST,
        "source_validation":src,
        "official_trade_archive":{
            "url":URL,"received_utc":datetime.fromtimestamp(now_ms/1000,timezone.utc).isoformat(),
            "last_modified_header":last_modified,
            "gz_size_bytes":len(raw),
            "gz_sha256":hashlib.sha256(raw).hexdigest(),
            "csv_sha256":hashlib.sha256(csv_raw).hexdigest()
        },
        "source_4h_candles":rows,
        "source_reconciliation":comparison,
        "native_confirm_verified_live_source":True,
        "no_strategy_replay_or_order_produced":True,
        "paper_changed":False,"orders_sent":0,"live":False,"promote":False,"merge":False
    }
    result["digest"]=hashlib.sha256(canonical(result)).hexdigest()
    archive_path.parent.mkdir(parents=True,exist_ok=True)
    archive_path.write_bytes(raw)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({"digest":result["digest"],"archives":src,
        "price_abs":[str(x) for x in comparison["price_OHLC_abs_diff_usdt"]],
        "volume_relative":comparison["base_volume_relative_diff"],
        "source_reconciliation_pass":comparison["source_same_venue_reconciliation_pass"],
        "MR40_automatically_authorized":False},ensure_ascii=False))


def cli():
    p=argparse.ArgumentParser()
    for name in ("protocol_path","bridge_path","ws_raw_path","ws_gate_path","archive_path","output"):
        p.add_argument("--"+name.replace("_","-"),required=True,type=Path)
    args=p.parse_args()
    execute(**vars(args))


if __name__=="__main__":
    cli()
