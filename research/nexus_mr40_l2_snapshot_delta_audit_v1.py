"""Stream SHA-pinned third-party Bybit spot L2: snapshot+delta update replay.

No orders, private endpoints, user-account action, nor asserted fills.
Reject a book estimate if u or seq continuity, crossed prices or stale book fails.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,hashlib,json,zipfile
from pathlib import Path

DAY_SHA="6a7e3f08c46da49ea2241aaec77371ca414a3f400e0cec4ec3b1ecda662b0d88"
FOCUS=1760129774936
QTY=0.09461
TARGETS=[("before_1s",FOCUS-1000),("before_1ms",FOCUS-1),("first_cross",FOCUS),
         ("after_100ms",FOCUS+100),("after_1s",FOCUS+1000),
         ("after_5s",FOCUS+5000),("after_15s",FOCUS+15000),
         ("first_recovery_print",1760129817331)]
def canon(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def iso(ms):
    return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat(timespec="milliseconds")
def snapshot_state(t,label,bids,asks,last,valid,broken,position_qty):
    update_ms=last.get("ts") if last else None
    staleness=(t-update_ms) if update_ms is not None else None
    ok=bool(valid and bids and asks and staleness is not None and 0<=staleness<=2000)
    result={"label":label,"target_utc":iso(t),"source_timestamp_utc":iso(update_ms) if update_ms else None,
            "source_engine_cts_utc":iso(last["cts"]) if last and last.get("cts") else None,
            "source_u":last["u"] if last else None,"source_seq":last["seq"] if last else None,
            "age_ms":staleness,"book_valid":ok,"invalidation_reason":broken}
    if not ok:
        result["depth_mark"]={"estimated":False,"reason":"invalid/stale/unavailable book"}
        return result
    pb=sorted(((float(p),q) for p,q in bids.items() if q>0),reverse=True)[:200]
    pa=sorted(((float(p),q) for p,q in asks.items() if q>0))[:200]
    if not pb or not pa or pb[0][0]>=pa[0][0]:
        result["book_valid"]=False
        result["invalidation_reason"]="crossed or missing top levels"
        result["depth_mark"]={"estimated":False}
        return result
    spread=pa[0][0]-pb[0][0]
    def quantity(levels,n):
        return sum(q for _,q in levels[:n])
    remain=position_qty;notional=0.0;levels=0;worstprice=None
    for price,sz in pb:
        used=min(sz,remain)
        if used>0:
            notional+=price*used;remain-=used;levels+=1;worstprice=price
        if remain<=1e-12:
            remain=0;break
    mark={
        "bid":pb[0][0],"ask":pa[0][0],"spread_usdt":round(spread,8),
        "spread_bps_of_mid":round(10000*spread/((pb[0][0]+pa[0][0])/2),5),
        "top_1_bid_btc":quantity(pb,1),"top_5_bid_btc":quantity(pb,5),
        "top_20_bid_btc":quantity(pb,20),"top_200_bid_btc":quantity(pb,200),
        "recorded_position_qty_btc":position_qty,
        "zero_latency_static_displayed_book_walk_completely_covered":remain==0,
        "book_walk_levels":levels,"remaining_uncovered_btc":round(remain,9),
        "book_walk_worst_level_price":worstprice,
        "static_book_walk_vwap_mark":round(notional/(position_qty-remain),6) if remain<position_qty else None,
        "EXPLICIT_NON_EXECUTABLE":"Static displayed L2 mark, NOT actual fill, no queue/latency/cancellations/spread execution estimate."
    }
    result["depth_mark"]=mark
    return result
def main(archive,policy,output):
    if output.exists():raise ValueError("no_overwrite")
    c=json.loads(policy.read_bytes())
    if c["schema"]!="mr40.bybit-spot-historical-l2-crash.v1" or c["source_size_bytes"]!=95584674:raise ValueError("protocol_drift")
    if archive.stat().st_size!=95584674:raise ValueError("archive_size_not_equal")
    h=hashlib.sha256()
    with archive.open("rb") as f:
        for chunk in iter(lambda:f.read(1<<22),b""):
            h.update(chunk)
    if h.hexdigest()!=DAY_SHA:raise ValueError("archive_sha_drift")
    bids={};asks={};valid=False;reason="no_snapshot";last=None
    stats=collections.Counter()
    issues=[];anchors={};idx=0
    first_ts=None;last_ts=None;max_delta_ts_cts=None;prior_u=None;prior_seq=None
    latest_valid_snapshot_ts=None
    with zipfile.ZipFile(archive) as z:
        members=z.infolist()
        if len(members)!=1 or members[0].filename!="2025-10-10_BTCUSDT_ob200.data" or members[0].file_size!=530351866:
            raise ValueError("ZIP_contents_changed")
        with z.open(members[0]) as f:
            for raw in f:
                stats["jsonl_messages"]+=1
                event=json.loads(raw)
                ts=int(event["ts"]); kind=event["type"];data=event["data"]
                if event["topic"]!="orderbook.200.BTCUSDT" or data["s"]!="BTCUSDT":
                    raise ValueError("topic_not_spot_btcusdt")
                u=int(data["u"]);seq=int(data["seq"]);cts=int(event.get("cts") or ts)
                if ts>=1760140800000 and ts<1760141100000 and cts<=ts+2000:
                    # Archive contains an adjacent-date trailing delta (first at
                    # 2025-10-11 00:00:00.065); this FAILS full-day scope.
                    # Do NOT update the October 10 state from future data.
                    stats["out_of_day_trailing_records"]+=1
                    continue
                if not(1760054400000<=ts<1760140800000 and cts<=ts+2000):
                    raise ValueError("timestamp_outside_day_or_cts_future")
                if last_ts is not None and ts<last_ts:
                    stats["nonmonotone_ts"]+=1
                    valid=False;reason="nonmonotone_archive_ts"
                if prior_seq is not None and seq<prior_seq:
                    stats["nonmonotone_seq"]+=1
                    valid=False;reason="nonmonotone_seq"
                if first_ts is None:first_ts=ts
                # Anchor t represents the book last publicly generated at/BEFORE t.
                while idx<len(TARGETS) and TARGETS[idx][1]<ts:
                    tag,target=TARGETS[idx]
                    anchors[tag]=snapshot_state(target,tag,bids,asks,last,valid,reason,QTY)
                    idx+=1
                if kind=="snapshot":
                    bids={str(p):float(q) for p,q in data["b"] if float(q)>0}
                    asks={str(p):float(q) for p,q in data["a"] if float(q)>0}
                    valid=True;reason=None
                    stats["snapshots"]+=1;latest_valid_snapshot_ts=ts
                elif kind=="delta":
                    stats["deltas"]+=1
                    if prior_u is None or u==1 or u!=prior_u+1:
                        stats["u_gaps_or_resets"]+=1
                        if len(issues)<12:issues.append({"when":iso(ts),"previous_u":prior_u,"current_u":u,"kind":"u_gap"})
                        valid=False;reason="missing_delta_or_restart_requires_snapshot"
                    if valid:
                        for where,levels in ((bids,data["b"]),(asks,data["a"])):
                            for p,q in levels:
                                qty=float(q)
                                if qty<0:raise ValueError("negative_qty")
                                if qty==0:where.pop(str(p),None)
                                else:where[str(p)]=qty
                    else:
                        stats["invalid_deltas"]+=1
                else:
                    raise ValueError("invalid_record_type:"+str(kind))
                if abs(ts-cts)>2000:stats["stale_cts_gt_2000"]+=1
                delta=ts-cts
                max_delta_ts_cts=delta if max_delta_ts_cts is None else max(max_delta_ts_cts,delta)
                prior_u=u;prior_seq=seq;last_ts=ts
                last={"ts":ts,"cts":cts,"u":u,"seq":seq,"type":kind}
                # Same timestamp events must be applied BEFORE an anchor at t.
            # At EOF zipfile validates CRC.
            while idx<len(TARGETS):
                tag,target=TARGETS[idx]
                anchors[tag]=snapshot_state(target,tag,bids,asks,last,valid,reason,QTY)
                idx+=1
    if stats["jsonl_messages"]<100000:raise ValueError("incomplete_day_stream")
    data={"schema":"mr40.bybit-spot-historical-l2-crash.results.v1",
          "source":{"url":c["source"],"compressed_bytes":archive.stat().st_size,"sha256":DAY_SHA,
                    "jsonl_bytes":530351866,"first_ts_utc":iso(first_ts),"last_ts_utc":iso(last_ts),
                    "vendor":"Third-party recorder, not a certified exchange-native archive"},
          "policy_sha256":hashlib.sha256(policy.read_bytes()).hexdigest(),
          "counts":dict(stats),"max_ts_minus_cts_ms":max_delta_ts_cts,
          "first_issues":issues,
          "snapshots":list(anchors.values()),"test":"Historical displayed book liquidity, not executable stop fills.",
          "prior_4h_1m_full_ohlc_parity":"FAILED and deliberately not changed",
          "full_day_strict_time_scope_pass":stats["out_of_day_trailing_records"]==0,
          "adjacent_day_overflow_caveat":"Exclude all post-midnight records from October 10 L2 state; strict full-day date-only scope remains FAILED.",
          "real_fill_verified":False,"paper_changed":False}
    data["cross_state_usable"]=bool(anchors["first_cross"]["book_valid"])
    data["digest"]=hashlib.sha256(canon(data)).hexdigest()
    output.write_bytes(canon(data)+b"\n")
    print(json.dumps({"digest":data["digest"],"counts":data["counts"],
       "issue_samples":issues[:3],"max_cts_delta":max_delta_ts_cts,
       "crossing_snapshot":anchors["first_cross"],
       "after_1s":anchors["after_1s"],"after_5s":anchors["after_5s"],
       "cross_usable":data["cross_state_usable"]},ensure_ascii=False),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("archive","policy","output"):p.add_argument("--"+k,required=True,type=Path)
    main(**vars(p.parse_args()))
