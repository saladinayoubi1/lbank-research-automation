"""Research-only 2026-10-20/21 Bybit Spot archived-ticks history bridge.

Not a forward performance test. No private API, no orders or demo changes.
Only accepted source: fully published daily Spot trade CSV archives on public.bybit.com.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,io,json,urllib.request
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import ClosedMR40,frozen_rows,canon

STEP1=60000
STEP4=14400000
DAY=86400000
MAX_BYTES=12000000
HEADER=["id","timestamp","price","volume","side","rpi"]
DAY_NAMES=("2026-10-20","2026-10-21")
FROZEN_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
BASE_URL="https://public.bybit.com/spot/BTCUSDT/BTCUSDT_"


def epoch(date):
    return int(datetime.fromisoformat(date).replace(tzinfo=timezone.utc).timestamp()*1000)


def ohlc_update(table,t,px,vol):
    if t not in table:table[t]=[px,px,px,px,vol,1]
    else:
        x=table[t]
        x[1]=max(x[1],px)
        x[2]=min(x[2],px)
        x[3]=px
        x[4]+=vol
        x[5]+=1


def rollup(csv_raw,day):
    """Aggregates in source order, refusing unsorted or invalid trade data."""
    start=epoch(day);end=start+DAY
    seen=set()
    minute={};four={}
    reader=csv.DictReader(io.StringIO(csv_raw.decode("utf-8-sig"),newline=""))
    if reader.fieldnames!=HEADER:raise ValueError("unexpected_csv_header")
    last_ts=None
    n=0
    for record in reader:
        if set(record)!=set(HEADER):raise ValueError("invalid_trade_columns")
        key=record["id"]
        if not key or key in seen:raise ValueError("duplicate_or_missing_trade_id")
        seen.add(key)
        ts=int(record["timestamp"])
        if not start<=ts<end:raise ValueError("wrong_utc_archive_day")
        if last_ts is not None and ts<last_ts:raise ValueError("nonmonotonic_timestamp_source")
        last_ts=ts
        px,vol=D(record["price"]),D(record["volume"])
        if (not px.is_finite() or not vol.is_finite() or px<=0 or vol<=0
                or record["side"].lower() not in ("buy","sell")
                or record["rpi"] not in ("0","1")):
            raise ValueError("invalid_spot_trade")
        ohlc_update(minute,ts//STEP1*STEP1,px,vol)
        ohlc_update(four,ts//STEP4*STEP4,px,vol)
        n+=1
    if sorted(minute)!=list(range(start,end,STEP1)):
        raise ValueError("missing_or_extra_minute")
    if sorted(four)!=list(range(start,end,STEP4)):
        raise ValueError("missing_or_extra_four_hour_bar")
    for t,x in four.items():
        subs=[minute.get(t+i*STEP1) for i in range(240)]
        if any(s is None for s in subs):raise ValueError("minute_gap")
        agg=[subs[0][0],max(s[1] for s in subs),min(s[2] for s in subs),
             subs[-1][3],sum((s[4] for s in subs),D(0)),sum(s[5] for s in subs)]
        if x!=agg:raise ValueError("trade_minute_fourhour_inconsistency")
        if min(x[:5])<=0 or x[1]<max(x[0],x[3]) or x[2]>min(x[0],x[3]):
            raise ValueError("inconsistent_four_hour_ohlcv")
    rows=[[t,*[str(x) for x in four[t][:5]]] for t in sorted(four)]
    return rows,{"day":day,"number_of_trades":n,"minutes_verified":len(minute),
                 "four_hour_candles_verified":len(four),
                 "source_trade_order_preserved":True,"exact_1m_to_4h":True}


def get_day(day,expected_bytes,folder):
    target=folder/("Bybit_BTCUSDT_Spot_"+day+".csv.gz")
    if target.exists():raise ValueError("refuse_overwrite_archive:"+day)
    url=BASE_URL+day+".csv.gz"
    req=urllib.request.Request(url,headers={"User-Agent":"NEXUS-BybitSpot-Archive-Research-Only"})
    with urllib.request.urlopen(req,timeout=22) as resp:
        if resp.status!=200:raise ValueError("not_public_archive_http200")
        raw=resp.read(MAX_BYTES+1)
        lm=resp.headers.get("Last-Modified")
    if len(raw)!=expected_bytes or len(raw)>MAX_BYTES:
        raise ValueError("changed_or_oversize_daily_archive")
    csv_raw=gzip.decompress(raw)
    rows,detail=rollup(csv_raw,day)
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(raw)
    detail.update({"archive_public_url":url,"archive_len":len(raw),
                   "archive_gzip_sha256":hashlib.sha256(raw).hexdigest(),
                   "decompressed_csv_sha256":hashlib.sha256(csv_raw).hexdigest(),
                   "server_last_modified":lm,
                   "on_research_device":str(target)})
    return rows,detail


def analyze(rows,forward):
    combined=rows+forward
    engine=ClosedMR40()
    frozen_events=[]
    appended=[]
    for r in combined:
        item=engine.feed(r,confirmed=True,source_verified=True)
        if item.bar_index<len(rows):
            if item.first_entry_close:frozen_events.append(("entry",item.bar_index))
            if item.natural_exit_close:frozen_events.append(("exit",item.bar_index))
        else:
            appended.append({
                "open_utc":datetime.fromtimestamp(item.start_ms/1000,timezone.utc).isoformat(),
                "bar_start_ms":item.start_ms,
                "z_score_as_of_this_confirmed_close":item.z_score,
                "raw_active":item.raw_active,
                "momentum_episode_admitted":item.episode_admitted,
                "closed_signal_target":item.final_target,
                "first_entry_signal_at_close":item.first_entry_close,
                "natural_exit_signal_at_close":item.natural_exit_close,
                "potential_next_open_ms":item.start_ms+STEP4,
                "next_open_fill_or_account_proven":False,
            })
    entries=sum(1 for kind,_ in frozen_events if kind=="entry")
    exits=sum(1 for kind,_ in frozen_events if kind=="exit")
    if entries!=47 or exits!=47:raise ValueError("baseline_47_47_prefix_changed")
    if len(appended)!=12:raise ValueError("12_bridge_signal_rows_expected")
    return appended,{"frozen_prefix_market_rows":len(rows),"frozen_prefix_entries_replayed":entries,
                     "frozen_prefix_exits_replayed":exits,
                     "new_closed_market_rows":len(appended),
                     "bridge_entry_close_markers":sum(x["first_entry_signal_at_close"] for x in appended),
                     "bridge_exit_close_markers":sum(x["natural_exit_signal_at_close"] for x in appended),
                     "new_close_signals_are_not_fills":True,
                     "historical_backfill_not_blind_forward":True}


def run(policy,sources,archive_dir,output):
    if output.exists():raise ValueError("refuse_overwrite_report")
    p=json.loads(policy.read_bytes())
    if (p["schema"]!="nexus.mr40.bybit_archive_bridge_two_days.v1"
        or tuple(p["days"])!=DAY_NAMES or p["pinned_frozen_rows_sha256"]!=FROZEN_SHA
        or p["frozen_rows"]!=8514 or p["safety"]["orders"]!=0
        or p["future_boundary"][:10]!="First elig"):
        raise ValueError("frozen_bridge_protocol_mismatch")
    existing=frozen_rows(sources)
    if len(existing)!=8514 or existing[-1][0]!=epoch("2026-10-19")+5*STEP4:
        raise ValueError("frozen_prefix_end_modified")
    bridged=[];receipts=[]
    for day in DAY_NAMES:
        cand,detail=get_day(day,p["archive_bytes"][day],archive_dir)
        bridged.extend(cand)
        receipts.append(detail)
    if len(bridged)!=12:raise ValueError("not_twelve_new_bars")
    for i,r in enumerate(bridged):
        expected=existing[-1][0]+(i+1)*STEP4
        if r[0]!=expected:raise ValueError("gap_or_future_row_not_contiguous")
    signals,stats=analyze(existing,bridged)
    report={
        "schema":"nexus.mr40.bybit_spot_oct20_oct21_bridge.results.v1",
        "protocol_sha256":hashlib.sha256(policy.read_bytes()).hexdigest(),
        "frozen_source_sha256":FROZEN_SHA,
        "new_4h_rows_utc_day20_21":bridged,
        "new_4h_rows_canonical_digest":hashlib.sha256(canon(bridged)).hexdigest(),
        "official_archive_receipts":receipts,
        "new_asof_signal_descriptions":signals,
        "source_and_prefix_verification":stats,
        "bridge_source_integrity_gate_pass":True,
        "classification":"BACKFILL_ALREADY_PUBLISHED__NOT_TRULY_FORWARD",
        "first_prospective_full_UTC_day_fixed_as_2026_10_23":True,
        "profit_outcomes_measured":False,
        "rest_api_restored":False,"L2_execution_verified":False,
        "paper_modified":False,"orders":0,"live":False,"promote":False,"merge":False,
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"receipts":receipts,
                      "stats":stats,
                      "new_asof_signals":[x for x in signals if x["first_entry_signal_at_close"] or x["natural_exit_signal_at_close"]],
                      "latest_close_signal":signals[-1]},
                     ensure_ascii=False,default=str))


if __name__=="__main__":
    a=argparse.ArgumentParser()
    for k in ("policy","sources","archive_dir","output"):a.add_argument("--"+k,type=Path,required=True)
    run(**vars(a.parse_args()))
