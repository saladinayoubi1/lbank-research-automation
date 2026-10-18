"""Offline, memory-bounded 4h research OHLCV from official Bybit Spot trade archives.

Requires local immutable raw .csv.gz and separately recorded exact SHA256.
Never connects to Bybit API, never submits orders, never backfills missing
timestamps, and never treats file SHA or a claimed public URL as a provider
cryptographic signature. For legitimate independent source QA only.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date,datetime,timezone,timedelta
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any

SYMBOLS=("BTCUSDT","ETHUSDT")
HEADER=["id","timestamp","price","volume","side","rpi"]
URL_PATTERN="https://public.bybit.com/spot/{symbol}/{symbol}_{date}.csv.gz"
SCHEMA="nexus.bybit-official-spot-raw-trade-4h-offline-research.v1"
MANIFEST_SCHEMA="nexus.bybit-official-spot-raw-trade-sample-claims.v1"
FOUR_H_MS=14_400_000
DAY_MS=86_400_000
MAX_GZIP_SIZE=200_000_000
MAX_TRADE_ROWS=12_000_000
SHA64=re.compile(r"^[a-f0-9]{64}$")


class RawTradeSourceError(ValueError):
    pass


def _digest(obj:Any)->str:
    return sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),
        allow_nan=False).encode()).hexdigest()


def _sha256_file(path:Path)->str:
    digest=sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda:handle.read(1048576),b""):
            digest.update(chunk)
    return digest.hexdigest()


def _day(day:str)->date:
    try:
        parsed=date.fromisoformat(day)
    except (TypeError,ValueError) as exc:
        raise RawTradeSourceError("invalid fixed UTC source day") from exc
    if parsed.isoformat()!=day:
        raise RawTradeSourceError("source date not canonical ISO yyyy-mm-dd")
    return parsed


def aggregate_gzip_day(path:Path,symbol:str,day:str,expected_sha256:str)->dict:
    """Stream one COMPLETE real Spot trade UTC day; no candle imputation.

    Separate full-day source receipt and TLS/provenance are necessary.
    The trade-file compression checksum alone is not a proof of origin.
    """
    if symbol not in SYMBOLS:
        raise RawTradeSourceError("unexpected Spot asset")
    start=_day(day)
    expected_name=f"{symbol}_{day}.csv.gz"
    if (path.name!=expected_name or path.is_symlink() or
        not path.is_file() or
        not 100<path.stat().st_size<MAX_GZIP_SIZE):
        raise RawTradeSourceError("missing/linked/oversized or wrong-day raw source")
    if not isinstance(expected_sha256,str) or not SHA64.fullmatch(expected_sha256):
        raise RawTradeSourceError("missing exact prereviewed raw SHA256")
    rawsha=_sha256_file(path)
    if rawsha!=expected_sha256:
        raise RawTradeSourceError("raw official-host trade file SHA256 mismatch")
    midnight=int(datetime(start.year,start.month,start.day,
                          tzinfo=timezone.utc).timestamp()*1000)
    bars:list[dict|None]=[None]*6
    last_id=0
    last_time=-1
    trades=0
    try:
        with gzip.open(path,"rt",newline="",encoding="utf8") as source:
            reader=csv.DictReader(source)
            if reader.fieldnames!=HEADER:
                raise RawTradeSourceError("unexpected original Spot trade CSV schema")
            for row in reader:
                trades+=1
                if trades>MAX_TRADE_ROWS or set(row)!=set(HEADER):
                    raise RawTradeSourceError("oversized or malformed raw Spot trades")
                try:
                    ident=int(row["id"])
                    trade_ms=int(row["timestamp"])
                    price=float(row["price"])
                    quantity=float(row["volume"])
                except (ValueError,TypeError) as exc:
                    raise RawTradeSourceError("invalid raw trade numeric field") from exc
                if (ident<=last_id or trade_ms<last_time
                    or not midnight<=trade_ms<midnight+DAY_MS
                    or not math.isfinite(price) or price<=0
                    or not math.isfinite(quantity) or quantity<=0
                    or row["side"] not in ("buy","sell")
                    or row["rpi"] not in ("0","1")):
                    raise RawTradeSourceError("out-of-order, out-of-day or invalid trade")
                last_id=ident
                last_time=trade_ms
                index=(trade_ms-midnight)//FOUR_H_MS
                bucket=bars[index]
                if bucket is None:
                    stamp=(datetime(start.year,start.month,start.day,
                                    tzinfo=timezone.utc)+timedelta(hours=4*index))
                    bars[index]={
                        "timestamp":stamp.isoformat(),
                        "open":price,
                        "high":price,
                        "low":price,
                        "close":price,
                        "volume":quantity,
                        "first_trade_ms":trade_ms,
                        "last_trade_ms":trade_ms,
                        "trades":1,
                    }
                else:
                    bucket["high"]=max(bucket["high"],price)
                    bucket["low"]=min(bucket["low"],price)
                    bucket["close"]=price
                    bucket["volume"]+=quantity
                    bucket["last_trade_ms"]=trade_ms
                    bucket["trades"]+=1
    except (EOFError,OSError,UnicodeError,csv.Error) as exc:
        raise RawTradeSourceError("corrupt/incomplete original Spot gzip CSV") from exc
    if trades==0 or any(b is None for b in bars) or sum(b["trades"] for b in bars)!=trades:
        raise RawTradeSourceError("incomplete 4h source buckets: cannot impute missing candles")
    return {
        "symbol":symbol,"date":day,"raw_file_name":expected_name,
        "claimed_official_url":URL_PATTERN.format(symbol=symbol,date=day),
        "raw_file_sha256":rawsha,"raw_gzip_bytes":path.stat().st_size,
        "total_raw_trade_rows":trades,"fully_observed_4h_bars":bars,
        "provider_origin_cryptographically_signed":False,
        "ready_to_score_prospective_strategy":False,
        "paper_eligible":False,"live_enabled":False,"orders":0,
    }


def audited_samples(root:Path,manifest_path:Path)->dict:
    """Immutable sampled source rows, NOT a contiguous full future dataset."""
    if (manifest_path.is_symlink() or not manifest_path.is_file()
        or not 100<manifest_path.stat().st_size<20_000):
        raise RawTradeSourceError("raw source SHA manifest absent or untrusted")
    try:
        manifest=json.loads(manifest_path.read_text("utf8"))
    except (UnicodeError,ValueError) as exc:
        raise RawTradeSourceError("invalid raw trade manifest") from exc
    if (type(manifest) is not dict or set(manifest)!={"schema","assets","samples",
         "study_scope","source_claim_not_exchange_signed"}
        or manifest.get("schema")!=MANIFEST_SCHEMA
        or manifest.get("assets")!=list(SYMBOLS)
        or manifest.get("study_scope")!="historical_source_seam_and_warmup_examples_only"
        or manifest.get("source_claim_not_exchange_signed") is not True
        or not isinstance(manifest.get("samples"),list)
        or not 1<=len(manifest["samples"])<=12):
        raise RawTradeSourceError("unreviewed raw sample scope")
    keys=set()
    samples=[]
    for item in manifest["samples"]:
        if type(item) is not dict or set(item)!={"symbol","date","raw_sha256"}:
            raise RawTradeSourceError("unreviewed sample entry")
        symbol,day,sha=item["symbol"],item["date"],item["raw_sha256"]
        if symbol not in SYMBOLS:
            raise RawTradeSourceError("wrong exchange symbol in manifest")
        key=(symbol,day)
        if key in keys:
            raise RawTradeSourceError("duplicate sample receipt")
        keys.add(key)
        samples.append(aggregate_gzip_day(root/f"{symbol}_{day}.csv.gz",
                                          symbol,day,sha))
    return {
        "schema":SCHEMA,
        "sample_only_not_full_day_by_day_source_coverage":True,
        "raw_files_have_official_https_claim_but_no_exchange_signature":True,
        "independent_provider_qa_still_required":True,
        "actual_original_canonical_seam_parity_not_proven_by_this_parser_alone":True,
        "not_future_prospective_holdout":True,
        "source_type":"SPOT_RAW_TRADE_NOT_SPOT_KLINE_API",
        "sampled_bybit_spot_days":samples,
        "paper_eligible":False,"live_enabled":False,"orders":0,
    }


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root",required=True,type=Path)
    parser.add_argument("--manifest",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    result=audited_samples(args.raw_root,args.manifest)
    result["digest"]=_digest(result)
    if args.output.exists() or args.output.is_symlink():
        raise RawTradeSourceError("write-once evidence already exists")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,sort_keys=True,indent=2,
                                       allow_nan=False)+"\n",encoding="utf8")
    print(json.dumps({"source_4h_sample_files":len(result["sampled_bybit_spot_days"]),
        "digest":result["digest"],
        "full_future_coverage_proven":False,"paper_eligible":False,
        "live_enabled":False},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
