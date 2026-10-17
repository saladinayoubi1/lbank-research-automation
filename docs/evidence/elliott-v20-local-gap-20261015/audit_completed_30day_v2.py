"""Compact forensic digest + INDEPENDENT 15m -> 1h/4h aggregation QA.

Pure read-only on the already-completed V20 segment. No backfill/replay,
web, account, trading strategy, price optimization or Paper/Live use.
Does not claim provider attestation or prospective profit.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

PAIRS=("BTCUSDT","ETHUSDT")
TF={"hour1":"h","hour4":"4h"}
FIELD_NAMES=("open","high","low","close","volume")
RESEARCH_ONLY=True
ENTRY_SIGNAL=LIVE_ENABLED=AUTO_DEMO=False


def compare_from_15m(state:Path)->dict:
    out={}
    for pair in PAIRS:
        folder=state/"bybit_market"/pair.lower().replace("usdt","_usdt")
        base=pd.read_parquet(folder/"minute15.parquet")
        if len(base)!=2880:
            raise AssertionError("not 30 full days of completed 15m bars")
        per={}
        for target,freq in TF.items():
            actual=pd.read_parquet(folder/(target+".parquet"))
            groups=base.groupby(base.timestamp.dt.floor(freq),sort=True)
            independently=groups.agg(
                timestamp=("timestamp","first"),
                open=("open","first"), high=("high","max"),
                low=("low","min"),close=("close","last"),
                volume=("volume","sum"),
            ).reset_index(drop=True)
            if len(actual)!=len(independently) or not actual.timestamp.equals(
                independently.timestamp
            ):
                raise AssertionError(f"{pair} {target} UTC group boundary differs")
            n=0; mismatches={}
            for field in FIELD_NAMES:
                lhs=actual[field].to_numpy(dtype=float)
                rhs=independently[field].to_numpy(dtype=float)
                if not (np.isfinite(lhs).all() and np.isfinite(rhs).all()):
                    raise AssertionError("bad aggregated price or volume")
                tolerance=1e-6 if field=="volume" else 1e-8
                unequal=~np.isclose(lhs,rhs,rtol=1e-10,atol=tolerance)
                mismatches[field]=int(unequal.sum())
                n+=len(lhs)
            per[target]={"bars":len(actual),"field_comparisons":n,
                         "material_mismatches":sum(mismatches.values()),
                         "by_field":mismatches}
        out[pair]=per
    return out


def digest_existing(state:Path)->dict:
    original=state/"V20_OFFLINE_SEGMENT_RECEIPT.json"
    if not original.is_file():
        raise ValueError("V20 native source receipt missing")
    raw=original.read_bytes()
    receipt=json.loads(raw)
    if receipt.get("disposition")!="PASS_DISCONNECTED_30DAY_OFFLINE_V2_SEGMENT":
        raise ValueError("V20 30-day original receipt not qualified")
    if receipt.get("source_count")!=60 or len(receipt.get("raw_source_archives",[]))!=60:
        raise ValueError("60 source files required")
    if receipt.get("prospective_v17_eligible") is not False or any(
        receipt.get(k)!=0 for k in ("orders_placed","external_network_requests")
    ) or receipt.get("protected_v19_six_hashes_unchanged") is not True:
        raise ValueError("future authorization/safety/protected original mismatch")
    source=receipt["raw_source_archives"]
    actual={(v["symbol"],v["filename"]) for v in source}
    expected={(symbol,f"{symbol}_{d.isoformat()}.csv.gz")
              for symbol in PAIRS
              for d in (date(2026,9,8)+timedelta(days=i) for i in range(30))}
    if actual!=expected:
        raise ValueError("gapped, repeated or wrong raw source date universe")
    aggregate=compare_from_15m(state)
    comparisons=sum(
        item["field_comparisons"] for pair in aggregate.values() for item in pair.values()
    )
    mismatches=sum(
        item["material_mismatches"] for pair in aggregate.values() for item in pair.values()
    )
    if comparisons!=9000 or mismatches:
        raise AssertionError("15m vs H1/H4 independent OHLCV reconciliation failed")
    return {
        "schema":"nexus.elliott-v20-independent-completed-segment-qa.v1",
        "disposition":"PASS_ISOLATED_V20_30DAY_MODEL_V2_ONLY",
        "original_native_receipt_sha256":sha256(raw).hexdigest(),
        "source_period_utc":"2026-09-08..2026-10-07",
        "pairs":list(PAIRS),
        "raw_trade_files":60,
        "raw_gzip_sha256":[{"symbol":i["symbol"],"filename":i["filename"],
                            "sha256":i["sha256"],"size_bytes":i["size_bytes"]}
                           for i in sorted(source,key=lambda a:(a["filename"],a["symbol"]))],
        "parquet_sha256_by_pair":{
            key:{tf:v["sha256"] for tf,v in item.items()}
            for key,item in receipt["timeframes"].items()
        },
        "protected_v19_six_parquet_sha256":receipt["protected_v19_hashes"],
        "independent_15m_to_h1_h4_ohlcv":aggregate,
        "independent_field_comparisons":comparisons,
        "material_aggregate_mismatches":mismatches,
        "provider_origin_freshly_attested":False,
        "historical_market_segment_only":True,
        "missing_aug02_to_sep07":True,
        "missing_oct08_to_oct15":True,
        "prospective_v17_eligible":False,
        "orders_placed":0,
        "live_enabled":False,"auto_demo":False,
        "source_archives_mutated":False,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--state",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError("evidence already exists: do not overwrite")
    outcome=digest_existing(args.state)
    args.output.write_text(json.dumps(outcome,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({
        "disposition":outcome["disposition"],
        "source_count":outcome["raw_trade_files"],
        "independent_comparisons":outcome["independent_field_comparisons"],
        "mismatches":outcome["material_aggregate_mismatches"],
        "prospective_ready":outcome["prospective_v17_eligible"]
    },sort_keys=True))


if __name__=="__main__":
    main()
