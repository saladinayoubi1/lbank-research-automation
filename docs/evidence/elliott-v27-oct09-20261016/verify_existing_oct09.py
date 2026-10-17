"""Read-only full-row QA of the ALREADY downloaded V27 Oct09 Bybit Spot files.

No HTTP access, no orders, no exchange credentials, no archive rewrites.
Reject false V27 initial receipt: it mistakenly rejected lowercase raw sides.
Verify preserved final receipt and original files, normalize via repo's real
Bybit parser, test ALL trade IDs/fields/timestamps, and reconstruct 3 TFs
in-memory with the versioned, stable source-row-order builder.
Do not merge into V19/V20 or declare profitability/future readiness.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from bybit_spot_archive_audit import read_trade_archive
from bybit_spot_backfill import validate_trade_range, trades_to_range_candles

DAY="2026-10-09"
SYMBOLS=("BTCUSDT","ETHUSDT")
EXPECTED={
    "BTCUSDT":{"sha256":"d43ab98cc7d1b089af6a8aeeda623d2a41bfc8326f129e9424a15c99c1d346d6",
               "bytes":5989359,"rows":1012531},
    "ETHUSDT":{"sha256":"81225224c0570744212c281f6d35f4013f26791aa0602dee480c4f1438dac3bb",
               "bytes":1954760,"rows":278788},
}
TIMES={"minute15":96,"hour1":24,"hour4":6}
FAILURE_METRICS=("invalid_numeric_rows","invalid_symbol_rows","invalid_side_rows",
                 "non_positive_price_rows","negative_size_rows",
                 "outside_range_rows","duplicate_trade_id_count")
RESEARCH_ONLY=True
LIVE_ENABLED=AUTO_DEMO=PAPER_ELIGIBLE=False


def sha_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):
            h.update(block)
    return h.hexdigest()


def qualify(root:Path)->dict:
    receipt_file=root/"CAPTURE_FINAL_RECEIPT.json"
    if not receipt_file.is_file():
        raise ValueError("existing immutable V27 final receipt absent")
    receipt=json.loads(receipt_file.read_text(encoding="utf-8"))
    if receipt.get("schema")!="nexus.elliott-v27-oct09-raw-source-capture.v2" or (
        receipt.get("prospective_v17_eligible") is not False
    ) or receipt.get("live_enabled") is not False:
        raise ValueError("source receipt not acceptable")
    files=receipt.get("files")
    if not isinstance(files,list) or len(files)!=2 or (
        {r.get("symbol") for r in files}!=set(SYMBOLS)
    ):
        raise ValueError("missing/duplicate source pair receipts")
    results={}
    for item in files:
        sym=item["symbol"]
        filename=f"{sym}_{DAY}.csv.gz"
        src=root/filename
        expected=EXPECTED[sym]
        expected_url=f"https://public.bybit.com/spot/{sym}/{filename}"
        if item.get("source_url")!=expected_url or item.get("date_utc")!=DAY or (
            item.get("http_status")!=200
        ) or item.get("gzip_crc_checked_to_eof") is not True:
            raise ValueError("provider/date transport receipt mismatch")
        if item.get("sha256")!=expected["sha256"] or (
            item.get("download_bytes")!=expected["bytes"]
        ) or item.get("rows_checked")!=expected["rows"] or (
            item.get("invalid_rows")!=0
        ):
            raise ValueError("pinned source receipt hash/row mismatch")
        if not src.is_file() or src.stat().st_size!=expected["bytes"] or (
            sha_file(src)!=expected["sha256"]
        ):
            raise ValueError("native raw file SHA256/length mismatch")
        parsed, parser=read_trade_archive(src)
        if parser.get("malformed_csv_rows") or parser.get("source_rows_skipped") or (
            parser.get("source_rows_parsed")!=expected["rows"]
        ) or len(parsed)!=expected["rows"]:
            raise ValueError("malformed or lost native raw trade rows")
        if "trade_id" not in parsed or parsed["trade_id"].isna().any():
            raise ValueError("raw archive lacks complete trade IDs")
        clean,quality=validate_trade_range(parsed,sym,DAY,DAY)
        if len(clean)!=expected["rows"] or any(quality[k] for k in FAILURE_METRICS):
            raise ValueError("full independent raw trade ID/date/OHLC input QA failed")
        # V2 stable row-order reconstruction. In-memory only: no historical
        # archive or existing parquets are modified.
        bars={}
        for timeframe, expected_count in TIMES.items():
            frame=trades_to_range_candles(clean,sym,timeframe,DAY,DAY)
            if len(frame)!=expected_count:
                raise ValueError("unexpected incomplete v2 day frame")
            bars[timeframe]={
                "closed_bars":int(len(frame)),
                "first_open_utc":str(frame["timestamp"].iloc[0]),
                "last_open_utc":str(frame["timestamp"].iloc[-1]),
            }
        results[sym]={
            "source_url":expected_url,"filename":filename,"sha256":expected["sha256"],
            "size_bytes":expected["bytes"],"raw_trades_fully_checked":expected["rows"],
            "parser":parser,"zero_invalid_or_duplicate_trade_ids":True,
            "full_row_quality":quality,"v2_rebuilt_in_memory_candles":bars,
        }
    return {
        "schema":"nexus.elliott-v27-oct09-independent-source-qa.v1",
        "disposition":"PASS_OCT09_TWO_PAIRS_FULL_TRADE_AND_V2_GRID_QA",
        "native_final_receipt_sha256":sha_file(receipt_file),
        "historical_first_receipt_retained":(root/"CAPTURE_RECEIPT.json").exists(),
        "original_gzip_files_rewritten":False,
        "source_pair_count":2,"date_utc":DAY,
        "pairs":results,
        "no_network_requests":True,"no_paper_demo_live_orders":True,
        "market_backtest_performed":False,"future_economic_edge_demonstrated":False,
        "prospective_v17_eligible":False,"paper_eligible":False,
        "research_only":True,"auto_demo":False,"live_enabled":False,
        "orders_placed":0,
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--original",type=Path,required=True)
    p.add_argument("--new-receipt",type=Path,required=True)
    args=p.parse_args()
    if args.new_receipt.exists():
        raise FileExistsError("cannot overwrite an earlier independent QA")
    out=qualify(args.original)
    args.new_receipt.parent.mkdir(parents=True,exist_ok=True)
    args.new_receipt.write_text(json.dumps(out,indent=2,sort_keys=True,default=str)+"\n",
                                encoding="utf-8")
    print(json.dumps({
        "disposition":out["disposition"],
        "validated_rows":{k:x["raw_trades_fully_checked"] for k,x in out["pairs"].items()},
        "bar_counts":{k:{tf:data["closed_bars"] for tf,data in x["v2_rebuilt_in_memory_candles"].items()} for k,x in out["pairs"].items()},
        "orders_placed":0,
    },sort_keys=True))


if __name__=="__main__":
    main()
