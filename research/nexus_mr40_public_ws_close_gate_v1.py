"""Fail-closed PUBLIC Bybit SPOT WebSocket 4h close and continuity gate.

Read only actual one-shot research receipt plus SHA-pinned 2-day archive bridge.
Unconfirmed snapshots and gaps NEVER produce MR40 close signal authority.
No WebSocket client, broker API, orders, PnL or scheduler in this module.
"""
from __future__ import annotations
import argparse,hashlib,json
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path

STEP4=14_400_000
BRIDGE_DIGEST="f118d0affe21995f4bfa01c1b5261eb7e963d1c1d46bfb094debf28a35c3114e"
BRIDGE_ROWS_SHA="a3fe422736b0dd27342b711765e721608cb88f7ec49ef22b723d09b64acaf5a6"
BRIDGE_END=1792612800000
TOPIC="kline.240.BTCUSDT"
URL="wss://stream.bybit.com/v5/public/spot"


def canon(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bridge_last_bar(doc):
    if doc.get("digest")!=BRIDGE_DIGEST:raise ValueError("bridge_digest_wrong")
    raw=dict(doc)
    raw.pop("digest")
    if hashlib.sha256(canon(raw)).hexdigest()!=BRIDGE_DIGEST:
        raise ValueError("bridge_payload_modified")
    rows=doc["new_4h_rows_utc_day20_21"]
    if hashlib.sha256(canon(rows)).hexdigest()!=BRIDGE_ROWS_SHA or len(rows)!=12:
        raise ValueError("bridge_rows_modified")
    if rows[-1][0]!=BRIDGE_END or not doc.get("bridge_source_integrity_gate_pass"):
        raise ValueError("bridge_last_time_or_integrity_invalid")
    return BRIDGE_END


def evaluate(probe,prior_open_ms):
    if (probe.get("schema")!="nexus.mr40.bybit.public_spot_ws_one_shot_result.v1"
        or probe.get("endpoint")!=URL
        or probe.get("topic")!=TOPIC
        or probe.get("orders_sent")!=0
        or probe.get("paper_modified") is not False
        or probe.get("private_api_used") is not False):
        raise ValueError("invalid_live_public_probe_provenance")
    if type(prior_open_ms) is not int or prior_open_ms%STEP4:
        raise ValueError("untrusted_historical_prefix_end")
    expected=prior_open_ms+STEP4
    connected=probe.get("public_ws_connected") is True
    subscribed=probe.get("subscribe_ack_success") is True
    has_transport=connected and subscribed and probe.get("failure_type") is None
    statuses=[]
    accepted=[]
    gap_count=None
    last_msg_ts=None
    for sample in probe.get("received_frames",[]):
        # Fail even for an unconfirmed snapshot if malformed: source evidence
        # should not be trusted by silently dropping invalid frames.
        if (not isinstance(sample,dict)
            or sample.get("interval")!="240"
            or type(sample.get("bar_start_ms")) is not int
            or type(sample.get("bybit_message_ts")) is not int
            or type(sample.get("confirmed_closed")) is not bool):
            raise ValueError("malformed_spot_kline_frame")
        ts=sample["bar_start_ms"]
        msg_ms=sample["bybit_message_ts"]
        if ts%STEP4 or msg_ms<ts or (last_msg_ts is not None and msg_ms<last_msg_ts):
            raise ValueError("invalid_or_backward_spot_kline_clock")
        last_msg_ts=msg_ms
        vals=[D(str(sample[k])) for k in ("open","high","low","close","base_volume")]
        o,h,l,c,v=vals
        if not all(x.is_finite() for x in vals) or min(o,h,l,c)<=0 or v<0 or h<max(o,c) or l>min(o,c):
            raise ValueError("invalid_spot_public_ohlcv")
        received=datetime.fromisoformat(sample["received_utc"].replace("Z","+00:00"))
        if received.tzinfo is None:raise ValueError("naive_receipt_timestamp")
        received_ms=int(received.timestamp()*1000)
        has_gap=ts>expected
        if has_gap:
            gap_count=max(0,(ts-expected)//STEP4)
        if sample["confirmed_closed"] is True:
            if msg_ms<ts+STEP4 or received_ms<ts+STEP4:
                raise ValueError("confirmed_before_4h_candle_end")
        okay=bool(has_transport and sample["confirmed_closed"] is True and ts==expected)
        if okay:
            accepted.append({"bar_start_ms":ts,
                             "ohlcv":[str(x) for x in vals],
                             "receipt_utc":sample["received_utc"]})
        statuses.append({"bar_start_ms":ts,
                         "confirmed":sample["confirmed_closed"],
                         "gap_from_prefix":has_gap,
                         "signal_input_accepted":okay})
    result={
        "public_websocket_connected":connected,
        "spot_subscribe_acknowledged":subscribed,
        "transport_qualified_for_market_read_only":has_transport,
        "source_samples_seen":len(statuses),
        "confirmed_closed_samples_seen":sum(s["confirmed"] for s in statuses),
        "confirmed_4h_contiguous_rows_accepted":len(accepted),
        "expected_next_fourhour_start_ms":expected,
        "missing_completed_4h_bars_before_latest_ws_bar":gap_count,
        "per_sample_gate":statuses,
        "accepted_closed_bars":accepted,
        "may_feed_mr40_from_this_probe":len(accepted)>0,
        "reason":("accepted_verified_closed_contiguous_source" if accepted else
                  ("no_verified_transport" if not has_transport else
                   "unconfirmed_and_or_missing_contiguous_history")),
        "no_live_signal_claim":True,
        "paper_unchanged":True,
        "orders_sent":0,
        "private_api_used":False,
        "promote":False
    }
    return result


def main(protocol,bridge_file,probe_file,output_file):
    if output_file.exists():raise ValueError("refuse_overwrite")
    p=json.loads(protocol.read_bytes())
    if (p["schema"]!="nexus.mr40.public_spot_ws_closed_bar_gate.v1"
        or p["required_transport"]["endpoint"]!=URL
        or p["required_transport"]["topic"]!=TOPIC
        or p["safety"]["no_order_transport"] is not True):
        raise ValueError("unexpected_unlocked_protocol")
    bridge=json.loads(bridge_file.read_bytes())
    end=bridge_last_bar(bridge)
    probe=json.loads(probe_file.read_bytes())
    out={
        "schema":"nexus.mr40.bybit_spot_ws_close_gate.results.v1",
        "protocol_sha256":digest(protocol),
        "bridge_sha256":digest(bridge_file),
        "probe_sha256":digest(probe_file),
        "archive_bridge_last_4h_open_ms":end,
        "gate":evaluate(probe,end),
        "no_real_signal_mr40_executed":True,
        "no_private_account_access":True
    }
    out["digest"]=hashlib.sha256(canon(out)).hexdigest()
    output_file.parent.mkdir(parents=True,exist_ok=True)
    output_file.write_text(json.dumps(out,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":out["digest"],"gate":out["gate"]},ensure_ascii=False))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for k in ("protocol","bridge_file","probe_file","output_file"):
        a.add_argument("--"+k,type=Path,required=True)
    main(**vars(a.parse_args()))
