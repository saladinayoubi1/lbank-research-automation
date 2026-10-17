"""Read-only quarantined overlap audit. Does not assert external API authenticity.

Compares a TRANSCIBED (not raw-byte-attested) observed public-market stdout
snapshot with byte-pinned, inspected historical Bybit 15m parquet. Any material
OHLCV conflict remains UNRESOLVED and must never auto-rewrite the archive.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd
from nexus_elliott_forward_bridge_v18 import PAIR_DIR, FROZEN_SHA, digest_file

EXPECTED_START_MS=1785535200000
EXPECTED_END_MS=1785541500000
TIME_STEP_MS=900000
FIELDS=("open","high","low","close","volume")
TOLERANCES={
    "open":Decimal("0.00000001"),"high":Decimal("0.00000001"),
    "low":Decimal("0.00000001"),"close":Decimal("0.00000001"),
    "volume":Decimal("0.00000001"),
}
RESEARCH_ONLY=True
LIVE_ENABLED=False
AUTO_DEMO=False
REPAIRS_APPLIED=0


def positive_decimal(value,field,*,allow_zero=False):
    if isinstance(value,bool):
        raise ValueError(field+" boolean invalid")
    try:
        number=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as e:
        raise ValueError(field+" numeric parse failure") from e
    if not number.is_finite() or number<0 or (number==0 and not allow_zero):
        raise ValueError(field+" nonfinite or invalid")
    return number


def validate_observed_snapshot(snapshot:dict)->dict:
    if not isinstance(snapshot,dict) or snapshot.get("schema")!=(
        "nexus.elliott-v18.observed-public-api-overlap.v1"
    ):
        raise ValueError("not the quarantined observed snapshot schema")
    if snapshot.get("query_bounds_ms")!={"start":EXPECTED_START_MS,"end":EXPECTED_END_MS}:
        raise ValueError("overlap window mismatch")
    if set(snapshot.get("symbols",{}))!=set(PAIR_DIR):
        raise ValueError("both frozen BTC/ETH observations required")
    normalized={}
    for symbol,block in snapshot["symbols"].items():
        if block.get("retCode")!=0 or block.get("category")!="spot":
            raise ValueError("observed response status or category inconsistent")
        raw=block.get("list")
        if not isinstance(raw,list) or len(raw)!=8:
            raise ValueError("exactly 8 observed OHLCV bars required")
        times=[]
        rows=[]
        for row in raw:
            if not isinstance(row,list) or len(row)!=6:
                raise ValueError("observed row must contain 6 fields")
            try:
                ms=int(row[0])
            except (TypeError,ValueError) as e:
                raise ValueError("observed timestamp malformed") from e
            if str(ms)!=str(row[0]) or ms%TIME_STEP_MS:
                raise ValueError("observed timestamp not 15m-aligned")
            times.append(ms)
            values=[positive_decimal(v,name,allow_zero=(name=="volume"))
                    for name,v in zip(FIELDS,row[1:])]
            op,hi,lo,cl,_=values
            if hi<max(op,lo,cl) or lo>min(op,hi,cl):
                raise ValueError("observed OHLC bounds invalid")
            rows.append((ms,values))
        if times!=list(range(EXPECTED_END_MS,EXPECTED_START_MS-1,-TIME_STEP_MS)):
            raise ValueError("observed timestamp grid gaps, ordering or duplicates")
        normalized[symbol]=rows
    return normalized


def compare_observed_with_frozen(snapshot:dict,archive_root:Path)->dict:
    observed=validate_observed_snapshot(snapshot)
    out={
        "schema":"nexus.elliott-v18-overlap-forensic-disposition.v1",
        "source_status":"QUARANTINED_TRANSCRIPTION_NOT_RAW_HTTP_ATTESTED",
        "not_exchange_authenticity_proof":True,
        "repair_performed":False,"orders_placed":0,
        "research_only":True,"live_enabled":False,"auto_demo":False,
        "immutable_original_archive":True,"symbols":{},
    }
    total=0
    for symbol,rows in observed.items():
        p=Path(archive_root)/"bybit_market"/PAIR_DIR[symbol]/"minute15.parquet"
        source_hash=digest_file(p)
        if source_hash!=FROZEN_SHA[symbol]:
            raise AssertionError("fixed historical archive sha mismatch")
        frame=pd.read_parquet(p)
        selected=frame.loc[
            (frame.timestamp>=pd.Timestamp(EXPECTED_START_MS,unit="ms",tz="UTC"))&
            (frame.timestamp<=pd.Timestamp(EXPECTED_END_MS,unit="ms",tz="UTC")),
            ["timestamp",*FIELDS],
        ]
        if len(selected)!=8:
            raise AssertionError("eight original overlap bars missing")
        originals={}
        for record in selected.itertuples(index=False):
            ms=int(pd.Timestamp(record.timestamp).timestamp()*1000)
            if ms in originals:
                raise AssertionError("duplicate frozen timestamp")
            originals[ms]=[positive_decimal(x,field,allow_zero=(field=="volume"))
                           for field,x in zip(FIELDS,record[1:])]
        mismatches=[]
        for ms,from_observed in rows:
            if ms not in originals:
                raise AssertionError("missing timestamp in frozen overlap")
            for field,candidate,frozen in zip(FIELDS,from_observed,originals[ms]):
                if abs(candidate-frozen)>TOLERANCES[field]:
                    mismatches.append({
                        "open_ms":ms,
                        "open_utc":datetime.fromtimestamp(ms/1000,timezone.utc).isoformat(),
                        "field":field,
                        "observed_stdout_value":str(candidate),
                        "frozen_archive_value":str(frozen),
                        "observed_minus_frozen":str(candidate-frozen),
                    })
        counts={name:sum(m["field"]==name for m in mismatches) for name in FIELDS}
        total+=len(mismatches)
        out["symbols"][symbol]={
            "frozen_archive_sha256":source_hash,
            "overlap_bars":len(rows),
            "field_mismatch_counts":counts,
            "mismatches":mismatches,
        }
    out["total_ohlcv_field_mismatches"]=total
    out["disposition"]=(
        "BLOCKED_UNRESOLVED_OBSERVED_SOURCE_CONFLICT" if total
        else "MATCH_WITH_UNATTESTED_OBSERVED_TRANSCRIPTION_NOT_PROVIDER_PROOF"
    )
    return out


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--observed",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    snapshot=json.loads(args.observed.read_text(encoding="utf-8"))
    out=compare_observed_with_frozen(snapshot,args.archive)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "disposition":out["disposition"],
        "total_ohlcv_field_mismatches":out["total_ohlcv_field_mismatches"],
        "per_symbol":{k:v["field_mismatch_counts"] for k,v in out["symbols"].items()},
        "original_files_changed":False,
    },sort_keys=True))


if __name__=="__main__":
    main()
