"""NEXUS Elliott V19 isolated OFFLINE public trade -> versioned v2 15m/1h/4h proof.

Safely use pre-existing local BTC/ETH CSV.GZ files, with the repository's
existing v2 resumable backfill engine. NO network calls, private exchange
credentials, live orders, signals, Paper/Demo, or historical archive rewrite.
The two-day 2026-07-31 through 2026-08-01 pilot is NOT a valid substitute
for the missing 2026-08 through 2026-10 fully contiguous prospective bridge.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

import bybit_spot_backfill as backfill
from bybit_spot_archive_audit import SYMBOLS

DAY_START="2026-07-31"
DAY_END="2026-08-01"
DATES=(DAY_START,DAY_END)
EXISTING_DAY_SHA={
    "BTCUSDT":"3d2a7d32eed34a28ee90c2861b29fc2d5fbf1461f7f6b0223ae9bc05836aae7a",
    "ETHUSDT":"1b81677c2afdaacb9492c01d0a55c5a47ba73d93909405691814f25c9ad8f851",
}
TIMEFRAMES={"minute15":(96,192),"hour1":(24,48),"hour4":(6,12)}
FIELDS=("open","high","low","close","volume")
TOLERANCE=Decimal("0.00000001")
RESEARCH_ONLY=True
LIVE_ENABLED=AUTO_DEMO=ENTRY_SIGNAL=PAPER_ELIGIBLE=False


def file_sha(path:Path)->str:
    h=sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def file_name(symbol:str,day:str)->str:
    if symbol not in ("BTCUSDT","ETHUSDT") or day not in DATES:
        raise ValueError("outside fixed offline cached pilot manifest")
    return f"{symbol}_{day}.csv.gz"


def certified_local_inventory(symbol:str)->backfill.ArchiveInventory:
    if symbol not in ("BTCUSDT","ETHUSDT"):
        raise ValueError("not BTC/ETH")
    return backfill.ArchiveInventory(symbol=symbol,monthly={},
                                    daily={date:file_name(symbol,date) for date in DATES})


def offline_source(cache_root:Path,symbol:str,filename:str,_unused_cache_root:Path)->dict:
    if symbol not in ("BTCUSDT","ETHUSDT"):
        raise ValueError("unexpected symbol")
    expected={file_name(symbol,day) for day in DATES}
    if filename not in expected:
        raise ValueError("filename not in declared local source inventory")
    file=cache_root/filename
    if not file.is_file():
        raise FileNotFoundError(f"local raw source absent: {filename}")
    digest=file_sha(file)
    if filename.endswith("_2026-07-31.csv.gz") and digest!=EXISTING_DAY_SHA[symbol]:
        raise ValueError("original July 31 trade-file digest differs from prior QA")
    return {
        "symbol":symbol,"filename":filename,"path":str(file),
        "sha256":digest,"size_bytes":file.stat().st_size,
        "url":None,"http_status":None,
        "acquisition":"preexisting-offline-local-raw-archive",
        "external_exchange_origin_attested":False,
    }


def require_new_isolated_output(root:Path,readonly_roots:tuple[Path,...]):
    resolved=root.resolve()
    for old in readonly_roots:
        readonly=old.resolve()
        if resolved==readonly or readonly in resolved.parents or resolved in readonly.parents:
            raise ValueError("output overlaps or contains protected cached/original source")
    if root.exists():
        raise FileExistsError("V19 pilot must use a fresh unique root, never overwrite or clean")


def source_integrity_summary(root:Path, legacy_root:Path)->dict:
    if not (root/backfill.CANDLE_MODEL_NAME).is_file():
        raise AssertionError("new v2 model receipt missing")
    backfill.validate_candle_model_state(root)
    model=json.loads((root/backfill.CANDLE_MODEL_NAME).read_text(encoding="utf-8"))
    if model.get("schema")!=backfill.CANDLE_MODEL_SCHEMA or (
        model.get("timestamp_tie_order")!="original_archive_row_order"
    ) or model.get("automatic_strategy_promotion") is not False or (
        model.get("live_trading_authority") is not False
    ):
        raise AssertionError("source candle-model authority mismatch")
    manifest=json.loads((root/backfill.SOURCE_MANIFEST_NAME).read_text(encoding="utf-8"))
    if len(manifest)!=4 or {x["filename"] for x in manifest}!={
        file_name(s,day) for s in ("BTCUSDT","ETHUSDT") for day in DATES
    }:
        raise AssertionError("incomplete raw archive source manifest")
    if any(x["candle_model"]["schema"]!=model["schema"] or
           x["candle_model"]["module_sha256"]!=model["module_sha256"] or
           x.get("external_exchange_origin_attested") is not False for x in manifest):
        raise AssertionError("model version or acquisition truth inconsistent")
    out={
        "schema":"nexus.elliott-v19.offline-v2-two-day-pilot.v1",
        "research_only":True,"live_enabled":False,"auto_demo":False,
        "orders_placed":0,"original_archive_modified":False,
        "cached_trade_files_modified":False,"network_requests":0,
        "external_exchange_origin_attested":False,
        "v2_source_receipt":model,
        "root":str(root),"source_archives":[
            {"symbol":x["symbol"],"filename":x["filename"],"sha256":x["sha256"],
             "size_bytes":x["size_bytes"]} for x in manifest
        ],
        "timeframe_series":{},
        "july31_overlap":{},
    }
    mismatches=0
    total_comparisons=0
    for symbol in ("BTCUSDT","ETHUSDT"):
        alias=symbol.lower().replace("usdt","_usdt")
        series={}
        july_mismatches={}
        for tf,(day,all_) in TIMEFRAMES.items():
            file=root/"bybit_market"/alias/f"{tf}.parquet"
            src=pd.read_parquet(file)
            if len(src)!=all_ or (
                src.timestamp.iloc[0]!=pd.Timestamp(DAY_START,tz="UTC")
            ) or src.timestamp.iloc[-1]!=(
                pd.Timestamp(DAY_END,tz="UTC")+pd.Timedelta(days=1)-
                {"minute15":pd.Timedelta(minutes=15),
                 "hour1":pd.Timedelta(hours=1),"hour4":pd.Timedelta(hours=4)}[tf]
            ):
                raise AssertionError("source OHLCV grid is not exactly two full days")
            source_digest=file_sha(file)
            series[tf]={"rows":int(len(src)),"sha256":source_digest}
            legacy_path=legacy_root/"bybit_market"/alias/f"{tf}.parquet"
            if not legacy_path.is_file():
                raise AssertionError("source frozen overlap missing")
            historical=pd.read_parquet(legacy_path)
            a=src.iloc[:day]
            b=historical.iloc[-day:]
            if (a.timestamp.reset_index(drop=True)!=b.timestamp.reset_index(drop=True)).any():
                raise AssertionError("July 31 overlap UTC index mismatch")
            field_results={}
            for field in FIELDS:
                delta=[
                    (i,Decimal(str(av))-Decimal(str(bv)))
                    for i,(av,bv) in enumerate(zip(a[field],b[field]))
                    if abs(Decimal(str(av))-Decimal(str(bv)))>TOLERANCE
                ]
                field_results[field]={
                    "compared":day,"material_mismatches":len(delta),
                    "first_diff":(
                        {"index":delta[0][0],"difference":str(delta[0][1])}
                        if delta else None
                    ),
                }
                total_comparisons+=day
                mismatches+=len(delta)
            july_mismatches[tf]=field_results
        out["timeframe_series"][symbol]=series
        out["july31_overlap"][symbol]=july_mismatches
    out["july31_field_comparisons"]=total_comparisons
    out["july31_material_mismatches"]=mismatches
    out["new_v2_candles_start_utc"]="2026-07-31T00:00:00+00:00"
    out["new_v2_candles_end_utc"]="2026-08-01T23:45:00+00:00"
    out["prospective_bridge_complete"]=False
    out["v17_future_study_authorized"]=False
    out["disposition"]=(
        "PASS_TWO_DAY_OFFLINE_V2_ARCHIVE_NO_FUTURE_BRIDGE" if mismatches==0
        else "FAIL_TWO_DAY_JULY_RECONCILIATION_NO_FUTURE_BRIDGE"
    )
    return out


def run(*,cache_root:Path,state_root:Path,legacy_root:Path)->dict:
    protected=(cache_root,legacy_root)
    require_new_isolated_output(state_root,protected)
    for symbol in ("BTCUSDT","ETHUSDT"):
        for day in DATES:
            if not (cache_root/file_name(symbol,day)).is_file():
                raise FileNotFoundError("Missing cached required source "+file_name(symbol,day))
    # Do not pass provider discovery/download functions: injection is mandatory.
    result=backfill.run_backfill(
        start_date=DAY_START,end_date=DAY_END,
        state_root=state_root,cache_root=cache_root,max_archives_per_run=4,
        symbols=("BTCUSDT","ETHUSDT"),
        inventory_fetcher=certified_local_inventory,
        downloader=lambda symbol,filename,ignored:offline_source(
            cache_root,symbol,filename,ignored),
        clean=False,
    )
    meta=result["summary"]
    if not meta["backfill_complete"] or meta["run_failures"] or (
        not meta["current_dataset_integrity_ok"]
    ) or meta["completed_units"]!=2 or meta["archives_completed_this_run"]!=4:
        raise AssertionError("isolated official v2 backfill did not complete")
    return source_integrity_summary(state_root,legacy_root)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--cached-trades",required=True,type=Path)
    parser.add_argument("--legacy-archive",required=True,type=Path)
    parser.add_argument("--output-root",required=True,type=Path)
    args=parser.parse_args()
    report=run(cache_root=args.cached_trades,
               legacy_root=args.legacy_archive,state_root=args.output_root)
    (args.output_root/"V19_QA_RECEIPT.json").write_text(
        json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "disposition":report["disposition"],
        "compared":report["july31_field_comparisons"],
        "material_mismatches":report["july31_material_mismatches"],
        "prospective_bridge_complete":False,
        "source_hashes":[x["sha256"] for x in report["source_archives"]],
    },sort_keys=True))
    if report["july31_material_mismatches"]:
        raise SystemExit(2)


if __name__=="__main__":
    main()
