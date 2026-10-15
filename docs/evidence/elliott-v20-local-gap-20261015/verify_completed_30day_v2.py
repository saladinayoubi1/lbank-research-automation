"""V20 offline completed-segment verification WITHOUT re-running backfill.

Reads already-built 30-day v2 raw-trade parquet/source manifest and V19
legacy preservation receipt, recomputes SHA-256 of all source gz files,
checks all six protected V19 parquet digests and calls V20's existing
verified 15m/1h/4h source/semantic checks. NO exchanges, trading signals,
new market evaluations, network calls or original file changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_disconnected_30day_v2 as v20


def verify_existing(cache: Path, state: Path, pilot: Path) -> dict:
    target=state/"V20_OFFLINE_SEGMENT_RECEIPT.json"
    if target.exists():
        raise FileExistsError("existing V20 final receipt; do not overwrite")
    manifest_path=state/"_source_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("completed V20 raw source manifest missing")
    source_rows=json.loads(manifest_path.read_text(encoding="utf-8"))
    if len(source_rows)!=v20.EXPECTED_ARCHIVES:
        raise ValueError("source manifest not exactly 60 raw gzip records")
    planned={(sym,v20.source_name(sym,date)) for date in v20.fixed_days()
             for sym in v20.SYMBOLS}
    seen={(s.get("symbol"),s.get("filename")) for s in source_rows}
    if seen!=planned:
        raise ValueError("source manifest includes missing/unknown day or symbol")
    for item in source_rows:
        f=cache/item["filename"]
        if not f.is_file() or f.stat().st_size!=item["size_bytes"] or (
            v20.digest_file(f)!=item["sha256"]
        ):
            raise ValueError("raw gzip source changed versus v2 source manifest")
        if item.get("http_status") is not None:
            raise ValueError("unexpected HTTP ingestion recorded")
    old_receipt=pilot/"V19_QA_RECEIPT.json"
    if not old_receipt.is_file():
        raise ValueError("original V19 independent receipt absent")
    old=json.loads(old_receipt.read_text(encoding="utf-8"))
    if old.get("disposition")!="PASS_TWO_DAY_OFFLINE_V2_ARCHIVE_NO_FUTURE_BRIDGE":
        raise ValueError("original V19 research source unqualified")
    protected={}
    if set(old.get("timeframe_series",{}))!=set(v20.SYMBOLS):
        raise ValueError("original V19 both pairs are required")
    for sym in v20.SYMBOLS:
        alias=sym.lower().replace("usdt","_usdt")
        if set(old["timeframe_series"][sym])!=set(v20.ROWS):
            raise ValueError("original V19 all three timeframes required")
        for timeframe in v20.ROWS:
            protected[f"bybit_market/{alias}/{timeframe}.parquet"]=(
                old["timeframe_series"][sym][timeframe]["sha256"]
            )
    result=v20.verify(state,source_rows,pilot,protected)
    if result["disposition"]!="PASS_DISCONNECTED_30DAY_OFFLINE_V2_SEGMENT":
        raise AssertionError("V20 dataset audit not accepted")
    if result["prospective_v17_eligible"] is not False or (
        result["orders_placed"]!=0 or result["external_network_requests"]!=0
    ):
        raise AssertionError("unapproved future or trading claims")
    target.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return result


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument("--cache",required=True,type=Path)
    p.add_argument("--state",required=True,type=Path)
    p.add_argument("--protected-v19",required=True,type=Path)
    args=p.parse_args()
    outcome=verify_existing(args.cache,args.state,args.protected_v19)
    print(json.dumps({
        "disposition":outcome["disposition"],
        "source_count":outcome["source_count"],
        "rows_per_pair":{pair:{tf:details["rows"] for tf,details in series.items()}
                         for pair,series in outcome["timeframes"].items()},
        "protected_six_hashes_unchanged":outcome["protected_v19_six_hashes_unchanged"],
        "genuinely_future_dataset_complete":False,
        "orders_placed":outcome["orders_placed"],
    },sort_keys=True))


if __name__=="__main__":
    main()
