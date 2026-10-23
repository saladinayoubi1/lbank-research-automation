"""Bybit BTCUSDT Spot 4h raw WebSocket close SOURCE gate, NOT a trader.

Input is an immutable, source-receipt JSON captured from public Spot websocket.
The acceptance criterion was frozen in MR40 4h-close-v2 protocol BEFORE test.
No networking, private API, Paper, account state or order functions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

UTC=timezone.utc
STEP4=14_400_000
BAR_START=1_792_684_800_000
BAR_END=BAR_START+STEP4-1
PREFIX_END=1_792_612_800_000
TOPIC="kline.240.BTCUSDT"
URL="wss://stream.bybit.com/v5/public/spot"


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def must_utc_ms(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None or d.utcoffset()!=UTC.utcoffset(d):
        raise ValueError("not_UTC_receipt")
    return int(d.timestamp()*1000)


def strict_bar(obj,server_ts,receipt_ms):
    if not isinstance(obj,dict):
        raise ValueError("not_a_source_candle")
    start,end=obj.get("start"),obj.get("end")
    if type(start) is not int or start!=BAR_START or type(end) is not int or end!=BAR_END:
        raise ValueError("fixed_4h_bar_clock_or_identity_mismatch")
    if obj.get("interval")!="240" or type(obj.get("confirm")) is not bool:
        raise ValueError("interval_or_confirm_not_native_bool")
    vals=[]
    for field in ("open","high","low","close","volume"):
        try:
            v=D(str(obj[field]))
        except (KeyError,ArithmeticError,TypeError,ValueError):
            raise ValueError("invalid_ohlcv_field_"+field) from None
        if not v.is_finite():
            raise ValueError("nonfinite_ohlcv")
        vals.append(v)
    o,h,l,c,v=vals
    if min(o,h,l,c)<=0 or v<0 or h<max(o,c) or l>min(o,c):
        raise ValueError("invalid_ohlcv_envelope")
    if type(server_ts) is not int or server_ts<start or receipt_ms<start:
        raise ValueError("server_or_receipt_before_candle_start")
    # This is telemetry only, NOT proof of candle closure:
    data_timestamp=obj.get("timestamp")
    if data_timestamp is not None and type(data_timestamp) is not int:
        raise ValueError("invalid_ancillary_data_timestamp")
    if obj["confirm"] is True and (server_ts<end+1 or receipt_ms<end+1):
        raise ValueError("premature_true_before_candle_end")
    return {
        "bar_start_ms":start,
        "bar_end_ms":end,
        "ohlcv":[str(x) for x in vals],
        "confirm":obj["confirm"],
        "server_timestamp_ms":server_ts,
        "source_received_ms":receipt_ms,
        "ancillary_data_timestamp_ms":data_timestamp,
        "ancillary_timestamp_after_bar_end_ms":max(0,data_timestamp-end) if data_timestamp is not None else None,
    }


def classify_capture(capture):
    if (capture.get("schema")!="nexus.mr40.bybit.public_spot_fourhour_raw_close_v2.results.v1"
        or capture.get("endpoint")!=URL
        or capture.get("topic")!=TOPIC
        or capture.get("orders_sent")!=0
        or capture.get("paper_modified") is not False
        or capture.get("private_api_used") is not False
        or capture.get("live_enabled") is not False):
        raise ValueError("untrusted_public_market_capture_identity")
    if capture.get("public_ws_connected") is not True:
        return {"transport_connected":False,"subscription_ack":False,"snapshots":0,
                "confirmed_4h_closed_seen":False,"MR40_source_ready":False,
                "missing_fourhour_bars":4,"reason":"not_connected"}
    if capture.get("subscribe_ack_success") is not True:
        return {"transport_connected":True,"subscription_ack":False,"snapshots":0,
                "confirmed_4h_closed_seen":False,"MR40_source_ready":False,
                "missing_fourhour_bars":4,"reason":"not_subscribed"}

    saw_true=[]
    snapshots=[]
    for rec in capture.get("raw_topic_receipts",[]):
        if not isinstance(rec,dict) or type(rec.get("raw_text")) is not str:
            raise ValueError("corrupt_raw_receipt")
        when=must_utc_ms(rec["received_utc"])
        message=json.loads(rec["raw_text"])
        if (message.get("topic")!=TOPIC or message.get("type")!="snapshot"
            or not isinstance(message.get("data"),list)
            or type(message.get("ts")) is not int):
            raise ValueError("wrong_topic_type_or_server_time")
        for bar in message["data"]:
            parsed=strict_bar(bar,message["ts"],when)
            parsed["received_utc"]=rec["received_utc"]
            snapshots.append(parsed)
            if parsed["confirm"] is True:
                saw_true.append(parsed)
                if len(saw_true)>1:
                    raise ValueError("duplicate_true_for_same_closed_4h_bar")
    # A valid closed 4h source message is still NOT the next contiguous
    # trusted MR40 bar: four Oct22 00/04/08/12 4h bars are absent.
    missing=(BAR_START-(PREFIX_END+STEP4))//STEP4
    if missing!=4:
        raise ValueError("unexpected_historical_bridge_gap")
    return {
        "transport_connected":True,
        "subscription_ack":True,
        "snapshots":len(snapshots),
        "unconfirmed_updates":sum(not x["confirm"] for x in snapshots),
        "confirmed_4h_closed_seen":len(saw_true)==1,
        "confirmed_source_4h_evidence":saw_true,
        "MR40_source_ready":False,
        "missing_fourhour_bars":missing,
        "reason":"historical_prefix_gap_blocks_MR40" if saw_true else "no_confirmed_fourhour_candle",
        "archive_gap_cannot_be_filled_with_1m_sample":True,
        "no_position_or_signal_generated":True,
    }


def run(protocol,raw_capture,output):
    if output.exists():
        raise ValueError("refuse_overwrite")
    p=json.loads(protocol.read_bytes())
    if (p.get("schema")!="nexus.mr40.bybit_spot_4h_close_proof_v2.protocol"
        or p.get("fixed_bar_start_ms")!=BAR_START
        or p.get("fixed_bar_end_ms_inclusive")!=BAR_END
        or p.get("raw_acceptance",{}).get("true_boolean_confirmation","").split(" ")[0]!="Use"
        or p.get("safety",{}).get("orders")!=0
        or p.get("safety",{}).get("promote") is not False):
        raise ValueError("unlocked_market_source_protocol")
    raw=raw_capture.read_bytes()
    capture=json.loads(raw)
    gate=classify_capture(capture)
    res={
        "schema":"nexus.mr40.bybit_public_fourhour_close_v2.source_gate.v1",
        "protocol_sha256":hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "raw_capture_sha256":hashlib.sha256(raw).hexdigest(),
        "gate":gate,"MR40_entry_or_exit_sent":False,"paper_modified":False,
        "orders_sent":0,"private_api_used":False,"promote":False
    }
    res["digest"]=hashlib.sha256(canonical(res)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(res,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":res["digest"],"gate":gate},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for name in ("protocol","raw_capture","output"):
        a.add_argument("--"+name,required=True,type=Path)
    args=a.parse_args()
    run(args.protocol,args.raw_capture,args.output)
