"""Independently reproduce July 31 OHLCV from CACHED original Bybit trades.

Research-only forensic check; never fetch, write or modify source parquets.
Two aggregation semantics: legacy timestamp-only unstable sort versus v2
stable source-row-order tie handling. Printed API comparisons are explicitly
from a quarantined *stdout transcription*, not raw HTTP attestation.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

import bybit_spot_archive_audit as legacy
import bybit_spot_backfill as v2

FILE_NAMES={
    "BTCUSDT":"BTCUSDT_2026-07-31.csv.gz",
    "ETHUSDT":"ETHUSDT_2026-07-31.csv.gz",
}
DIRECTORIES={"BTCUSDT":"btc_usdt","ETHUSDT":"eth_usdt"}
_FIELDS=("open","high","low","close","volume")
START=pd.Timestamp("2026-07-31T22:00:00Z")
END=pd.Timestamp("2026-07-31T23:45:00Z")
FIXED_SOURCE={
    "BTCUSDT":"c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
    "ETHUSDT":"ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}


def file_sha(file: Path) -> str:
    digest=sha256()
    with file.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):
            digest.update(block)
    return digest.hexdigest()


def comparable(df: pd.DataFrame) -> dict:
    chosen=df[(df["timestamp"]>=START)&(df["timestamp"]<=END)]
    if len(chosen)!=8 or len(chosen.timestamp.unique())!=8:
        raise AssertionError("incomplete July 31 source-overlap window")
    result={}
    for row in chosen.itertuples(index=False):
        ms=int(pd.Timestamp(row.timestamp).value//1_000_000)
        result[ms]={field:Decimal(str(getattr(row,field))) for field in _FIELDS}
    if set(result)!=set(range(int(START.value//1_000_000),int(END.value//1_000_000)+1,900_000)):
        raise AssertionError("overlap timestamps not 15m contiguous")
    return result


def field_diff(a:dict,b:dict) -> dict:
    out={}
    for f in _FIELDS:
        nonzero=[{"open_ms":ts,"a":str(a[ts][f]),"b":str(b[ts][f]),
                  "signed_difference":str(a[ts][f]-b[ts][f])}
                 for ts in sorted(a) if a[ts][f]!=b[ts][f]]
        out[f]={"count":len(nonzero),"differences":nonzero}
    return out


def audit(cached:Path,archive:Path,transcription:Path)->dict:
    obs=json.loads(transcription.read_text(encoding="utf-8"))
    if obs.get("schema")!="nexus.elliott-v18.observed-public-api-overlap.v1":
        raise ValueError("unknown API stdout transcription")
    report={
        "schema":"nexus.elliott-v18-original-trade-reconstruction.v1",
        "status":"FORENSIC_EVIDENCE_ONLY_NO_FUTURE_MARKET_EVALUATION",
        "research_only":True,"live_enabled":False,"orders_placed":0,
        "original_parquets_modified":False,"cached_raw_trades_modified":False,
        "market_api_invoked":False,
        "api_comparison_status":"QUARANTINED_STDOUT_TRANSCRIPTION_NOT_RAW_HTTP_ATTESTED",
        "pairs":{},
    }
    for symbol in FILE_NAMES:
        raw_path=cached/FILE_NAMES[symbol]
        frozen_path=archive/"bybit_market"/DIRECTORIES[symbol]/"minute15.parquet"
        if file_sha(frozen_path)!=FIXED_SOURCE[symbol]:
            raise AssertionError("frozen source identity mismatch")
        raw,raw_schema=legacy.read_trade_archive(raw_path)
        valid_old,legacy_quality=legacy.validate_trades(raw,symbol,"2026-07-31")
        valid_new,stable_quality=v2.validate_trade_range(raw,symbol,"2026-07-31","2026-07-31")
        old=legacy.trades_to_candles(valid_old,symbol,"minute15","2026-07-31")
        new=v2.trades_to_range_candles(valid_new,symbol,"minute15","2026-07-31","2026-07-31")
        frozen=pd.read_parquet(frozen_path)
        api={}
        for fields in obs["symbols"][symbol]["list"]:
            ts=int(fields[0])
            api[ts]={key:Decimal(str(val)) for key,val in zip(_FIELDS,fields[1:])}
        original=comparable(frozen)
        legacy_values=comparable(old)
        stable_values=comparable(new)
        if set(original)!=set(api):
            raise AssertionError("API overlap timestamps differ from raw archive")
        pairs={
            "legacy_vs_frozen":field_diff(legacy_values,original),
            "row_stable_v2_vs_frozen":field_diff(stable_values,original),
            "row_stable_v2_vs_legacy":field_diff(stable_values,legacy_values),
            "quarantined_api_vs_frozen":field_diff(api,original),
            "quarantined_api_vs_legacy":field_diff(api,legacy_values),
            "quarantined_api_vs_v2":field_diff(api,stable_values),
        }
        summary={n:{field:val["count"] for field,val in fields.items()}
                 for n,fields in pairs.items()}
        report["pairs"][symbol]={
            "raw_trade_csv_gz_sha256":file_sha(raw_path),
            "raw_trade_rows":int(len(raw)),
            "legacy_accepted_trade_rows":int(len(valid_old)),
            "stable_accepted_trade_rows":int(len(valid_new)),
            "raw_parser_schema":raw_schema,
            "legacy_quality":legacy_quality,
            "stable_quality":stable_quality,
            "frozen_parquet_sha256":file_sha(frozen_path),
            "overlap_comparisons":pairs,
            "summary_counts":summary,
        }
    return report


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cached-trades",type=Path,required=True)
    p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--transcription",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    result=audit(args.cached_trades,args.archive,args.transcription)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True,default=str)+"\n",encoding="utf-8")
    print(json.dumps({
        "schema":result["schema"],
        "compared_candles_per_pair":8,
        "counts":{p:d["summary_counts"] for p,d in result["pairs"].items()},
        "raw_trade_sha256":{p:d["raw_trade_csv_gz_sha256"] for p,d in result["pairs"].items()},
        "research_only":True,
    },indent=2))


if __name__=="__main__":
    main()
