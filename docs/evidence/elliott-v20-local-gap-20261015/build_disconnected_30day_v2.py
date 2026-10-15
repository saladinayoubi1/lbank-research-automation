"""V20 offline, DISCONNECTED 30-day cached Bybit public trade v2 reconstruction.

Build 2026-09-08..2026-10-07 separately from V19's July31/Aug01
pilot. This DOES NOT bridge Aug02..Sep07 or Oct08..Oct15 and cannot
be used as V17 genuinely unseen future data or any Demo trading signal.

No HTTP, no Bybit credentials, no old file writes, no strategy calls.
"""
from __future__ import annotations

import argparse
from datetime import date,timedelta
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

import bybit_spot_backfill as backfill
from nexus_elliott_forward_bridge_v18 import validate_frame

START=date(2026,9,8)
END=date(2026,10,7)
SYMBOLS=("BTCUSDT","ETHUSDT")
EXPECTED_DAYS=30
EXPECTED_ARCHIVES=60
ROWS={"minute15":2880,"hour1":720,"hour4":180}
INTERVALS={"minute15":pd.Timedelta(minutes=15),
           "hour1":pd.Timedelta(hours=1),
           "hour4":pd.Timedelta(hours=4)}
RESEARCH_ONLY=True
LIVE_ENABLED=False
AUTO_DEMO=False
TRADING_AUTHORITY=False


def digest_file(path:Path)->str:
    h=sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def fixed_days()->list[str]:
    out=[]
    d=START
    while d<=END:
        out.append(d.isoformat())
        d+=timedelta(days=1)
    if len(out)!=EXPECTED_DAYS:
        raise AssertionError("pre-registered segment duration changed")
    return out


def source_name(symbol:str,day:str)->str:
    if symbol not in SYMBOLS or day not in fixed_days():
        raise ValueError("not in isolated 30-day research source scope")
    return f"{symbol}_{day}.csv.gz"


def preflight(cache:Path,new_state:Path,protected:list[Path])->list[dict]:
    if new_state.exists():
        raise FileExistsError("new v2 state root must be fresh, no resume or overwrite")
    out=new_state.resolve()
    for original in [cache,*protected]:
        root=original.resolve()
        if out==root or root in out.parents or out in root.parents:
            raise ValueError("output collides with original source/legacy archive")
    if not cache.is_dir():
        raise ValueError("cached raw source directory unavailable")
    sources=[]
    for day in fixed_days():
        for symbol in SYMBOLS:
            name=source_name(symbol,day)
            f=cache/name
            if not f.is_file() or f.stat().st_size==0:
                raise FileNotFoundError("missing/nonempty raw source required: "+name)
            sources.append({"symbol":symbol,"day":day,"filename":name,
                            "path":str(f),"sha256":digest_file(f),
                            "size_bytes":f.stat().st_size,
                            "provider_authenticity_rechecked":False})
    if len(sources)!=EXPECTED_ARCHIVES:
        raise AssertionError("incomplete local raw archive count")
    return sources


def offline_inventory(symbol:str)->backfill.ArchiveInventory:
    if symbol not in SYMBOLS:
        raise ValueError("invalid symbol")
    return backfill.ArchiveInventory(symbol=symbol,monthly={},
        daily={day:source_name(symbol,day) for day in fixed_days()})


def offline_downloader(cache:Path,source_hashes:dict):
    def load(symbol:str,filename:str,_cache_root:Path)->dict:
        if (symbol,filename) not in source_hashes:
            raise ValueError("unplanned local source filename")
        p=cache/filename
        if digest_file(p)!=source_hashes[(symbol,filename)]:
            raise ValueError("local raw source file changed since preflight")
        return {
            "symbol":symbol,"filename":filename,
            "path":str(p),"sha256":source_hashes[(symbol,filename)],
            "size_bytes":p.stat().st_size,
            "url":None,"http_status":None,
            "acquisition":"preexisting-local-cached-trade-gzip",
            "provider_authenticity_rechecked":False,
        }
    return load


def verify(state:Path,source_rows:list[dict],original_pilot:Path,
           original_before:dict[str,str])->dict:
    backfill.validate_candle_model_state(state)
    model=json.loads((state/backfill.CANDLE_MODEL_NAME).read_text(encoding="utf-8"))
    if model!=backfill.candle_model_receipt():
        raise AssertionError("unexpected v2 model version on disk")
    manifest=json.loads((state/backfill.SOURCE_MANIFEST_NAME).read_text(encoding="utf-8"))
    if len(manifest)!=EXPECTED_ARCHIVES or (
        {x["filename"] for x in manifest}!={x["filename"] for x in source_rows}
    ):
        raise AssertionError("30-day archive sources were not completely committed")
    expected={(x["symbol"],x["filename"]):x["sha256"] for x in source_rows}
    if any(x.get("sha256")!=expected.get((x["symbol"],x["filename"]))
           or x.get("candle_model")!=model or x.get("http_status") is not None
           for x in manifest):
        raise AssertionError("source integrity or no-network flags inconsistent")
    output={}
    for sym in SYMBOLS:
        alias=sym.lower().replace("usdt","_usdt")
        timeframes={}
        for tf,n in ROWS.items():
            f=state/"bybit_market"/alias/(tf+".parquet")
            df=pd.read_parquet(f)
            if len(df)!=n or df.timestamp.iloc[0]!=pd.Timestamp(START,tz="UTC") or (
                df.timestamp.iloc[-1]+INTERVALS[tf]!=pd.Timestamp(END+timedelta(days=1),tz="UTC")
            ) or not df.timestamp.is_unique or (
                df.timestamp.diff().dropna()!=INTERVALS[tf]
            ).any():
                raise AssertionError("partial/non-contiguous generated timeframe")
            if tf=="minute15":
                validate_frame(df)
            timeframes[tf]={"rows":n,"sha256":digest_file(f)}
        output[sym]=timeframes
    after={}
    for relative,digest in original_before.items():
        f=original_pilot/relative
        after[relative]=digest_file(f)
        if after[relative]!=digest:
            raise AssertionError("protected V19 pilot changed")
    return {
        "schema":"nexus.elliott-v20-isolated-offline-30day-v2.v1",
        "disposition":"PASS_DISCONNECTED_30DAY_OFFLINE_V2_SEGMENT",
        "source_date_start_utc":START.isoformat(),
        "source_date_end_utc":END.isoformat(),
        "raw_source_archives":source_rows,
        "source_count":len(source_rows),
        "source_market_origin_independently_attested":False,
        "v2_model_receipt":model,
        "timeframes":output,
        "protected_v19_six_hashes_unchanged":True,
        "protected_v19_hashes":after,
        "does_not_bridge_2026_08_02_to_2026_09_07":True,
        "does_not_cover_2026_10_08_to_2026_10_15":True,
        "prospective_v17_eligible":False,
        "research_only":True,"live_enabled":False,"auto_demo":False,
        "orders_placed":0,"external_network_requests":0,
        "old_history_backtest_replayed":False,
    }


def run(cache:Path,state:Path,protected_pilot:Path)->dict:
    protected=[]
    before={}
    for sym in SYMBOLS:
        alias=sym.lower().replace("usdt","_usdt")
        for tf in ROWS:
            rel=f"bybit_market/{alias}/{tf}.parquet"
            p=protected_pilot/rel
            if not p.is_file():
                raise ValueError("original V19 six-file pilot missing")
            before[rel]=digest_file(p)
    protected.append(protected_pilot)
    sources=preflight(cache,state,protected)
    hashes={(x["symbol"],x["filename"]):x["sha256"] for x in sources}
    summary=backfill.run_backfill(
        start_date=START.isoformat(),end_date=END.isoformat(),
        state_root=state,cache_root=cache,
        max_archives_per_run=EXPECTED_ARCHIVES,symbols=SYMBOLS,
        inventory_fetcher=offline_inventory,
        downloader=offline_downloader(cache,hashes),
        clean=False,
    )
    final=summary["summary"]
    if (final["completed_units"]!=EXPECTED_DAYS or
        final["archives_completed_this_run"]!=EXPECTED_ARCHIVES or
        final["run_failures"] or not final["backfill_complete"] or
        not final["current_dataset_integrity_ok"]):
        raise AssertionError("full 30-day raw-source replay incomplete")
    return verify(state,sources,protected_pilot,before)


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cache",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--protected-v19",type=Path,required=True)
    args=p.parse_args()
    result=run(args.cache,args.output,args.protected_v19)
    (args.output/"V20_OFFLINE_SEGMENT_RECEIPT.json").write_text(
        json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "disposition":result["disposition"],
        "input_files":result["source_count"],
        "rows_per_pair":{sym:{tf:v["rows"] for tf,v in obj.items()}
                         for sym,obj in result["timeframes"].items()},
        "network_requests":0,"old_pilot_untouched":True,
        "prospective_v17_eligible":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
