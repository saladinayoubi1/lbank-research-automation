"""Read-only forensic verifier for raw official Bybit Spot minute WS messages.

This is POST-CAPTURE diagnostics, not a preregistered hypothesis test.
The observed confirm=True 1m message NEVER authorizes 4h MR40 signals.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path

TOPIC="kline.1.BTCUSDT"
URL="wss://stream.bybit.com/v5/public/spot"


def canon(x):
    return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def inspect_message(outer):
    r=datetime.fromisoformat(outer["received_utc"].replace("Z","+00:00"))
    if r.tzinfo is None:raise ValueError("receipt_utc_missing_offset")
    payload=outer["payload"]
    if payload.get("topic")!=TOPIC:raise ValueError("not_a_public_spot_minute_message")
    server_ms=payload.get("ts")
    if type(server_ms) is not int:raise ValueError("invalid_server_timestamp")
    out=[]
    for item in payload["data"]:
        if type(item.get("confirm")) is not bool or str(item.get("interval"))!="1":
            raise ValueError("invalid_confirm_or_interval")
        start,end=item["start"],item["end"]
        if type(start) is not int or type(end) is not int or start%60000 or end!=start+59999:
            raise ValueError("bad_one_minute_bar_clock")
        o,h,l,c,v=[D(str(item[x])) for x in ("open","high","low","close","volume")]
        if not all(x.is_finite() for x in (o,h,l,c,v)) or min(o,h,l,c)<=0 or v<0 or h<max(o,c) or l>min(o,c):
            raise ValueError("bad_minute_ohlcv")
        trade_ms=item.get("timestamp")
        if type(trade_ms) is not int or trade_ms<start:
            raise ValueError("invalid_recorded_trade_timestamp")
        if server_ms<start:raise ValueError("server_before_candle")
        received_ms=int(r.timestamp()*1000)
        server_after=server_ms>=end+1
        receipt_after=received_ms>=end+1
        confirmed=item["confirm"] is True
        if confirmed and (not server_after or not receipt_after):
            raise ValueError("premature_confirm_true_in_raw_feed")
        out.append({
            "bar_open_ms":start,"bar_end_ms_inclusive":end,
            "ws_confirm_strict_boolean":confirmed,
            "server_generated_ms":server_ms,
            "receipt_utc":outer["received_utc"],
            "server_after_candle_end":server_after,
            "receipt_after_candle_end":receipt_after,
            # Bybit's timestamp field is recorded as sent, not inferred to
            # be the final trade of the represented minute.
            "trade_timestamp_ms":trade_ms,
            "trade_timestamp_beyond_candle_end_ms":max(0,trade_ms-end),
            "eligible_evidence_of_one_minute_closed_source":
                confirmed and server_after and receipt_after,
            "eligible_MR40_fourhour_signal_input":False,
        })
    return out


def forensic(raw_file,output):
    if output.exists():raise ValueError("refuse_overwrite")
    b=raw_file.read_bytes()
    p=json.loads(b)
    if (p.get("schema")!="nexus.mr40.bybit_spot_raw_minute_diagnostic.results.v1"
        or p.get("endpoint")!=URL or p.get("topic")!=TOPIC
        or p.get("connected") is not True or p.get("subscription_ack") is not True
        or p.get("allow_feed_to_mr40") is not False
        or p.get("orders_sent")!=0 or p.get("private_api") is not False):
        raise ValueError("untrusted_one_minute_market_receipt")
    series=[]
    for frame in p["raw_frames"]:
        series+=inspect_message(frame)
    valid_closed=[z for z in series if z["eligible_evidence_of_one_minute_closed_source"]]
    exceed=[z for z in series if z["trade_timestamp_beyond_candle_end_ms"]>0]
    report={
        "schema":"nexus.mr40.bybit_spot_ws_minute_postcapture_forensics.results.v1",
        "source_provenance_sha256":hashlib.sha256(b).hexdigest(),
        "classification":"POST_HOC_FIELD_SEMANTICS_DIAGNOSTIC_NOT_STRATEGY_VALIDATION",
        "topic":TOPIC,"source_frames":len(p["raw_frames"]),
        "minute_bar_updates_validated":len(series),
        "strict_confirmed_closed_one_minute_count":len(valid_closed),
        "confirmed_minute_market_evidence":valid_closed,
        "trade_timestamp_after_bar_end_count":len(exceed),
        "trade_timestamp_after_bar_end_samples":exceed,
        "finding":"The server message ts and independent receipt fall after the 1-minute bar end for the confirm=true frame. The embedded data.timestamp can lie after that end; do not silently assume it is in the candle. Quarantine this field as a source-semantic warning, not as an MR40 signal clock.",
        "earlier_tight_validator_result_overridden":False,
        "confirmed_fourhour_bar_observed":False,
        "missing_prior_fourhour_bars_repaired":False,
        "MR40_next_open_signal_authorized":False,
        "paper_modified":False,"orders_sent":0,"private_api":False,"promote":False
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"source_frames":report["source_frames"],
        "minute_confirmed":len(valid_closed),"timestamp_after_end":len(exceed),
        "accepted_MR40":False,"warning_ms":[z["trade_timestamp_beyond_candle_end_ms"] for z in exceed]},
        ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--raw",type=Path,required=True)
    a.add_argument("--output",type=Path,required=True)
    p=a.parse_args()
    forensic(p.raw,p.output)
