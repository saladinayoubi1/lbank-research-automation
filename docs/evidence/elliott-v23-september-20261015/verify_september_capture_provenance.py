"""Read-only V23 September source SHA reconciliation and corrected receipt.

The original first-run capture receipt incorrectly inherited V22's uppercase
AUGUST success label. KEEP the original receipt bytes untouched for audit.
Verify all September source metadata and on-disk sha/size before writing
a corrected independent evidence receipt. No network, no replay, no orders.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

SYMBOLS=("BTCUSDT","ETHUSDT")
MONTH="2026-09"
ORIGINAL_DISPOSITION="PASS_TWO_AUGUST_ARCHIVES_TRANSPORT_ONLY"
CORRECTED_DISPOSITION="PASS_TWO_SEPTEMBER_ARCHIVES_TRANSPORT_ONLY"
SOURCE="https://public.bybit.com/spot"


def sha_file(p:Path)->str:
    h=hashlib.sha256()
    with p.open("rb") as file:
        for b in iter(lambda:file.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def audit_and_correct(root:Path)->dict:
    src=root/"CAPTURE_RECEIPT.json"
    dest=root/"CORRECTED_CAPTURE_RECEIPT.json"
    if dest.exists():
        raise FileExistsError("corrected September evidence already exists")
    raw=src.read_bytes()
    original=json.loads(raw)
    if original.get("schema")!="nexus.elliott-v23-official-september-gzip-acquisition.v1":
        raise ValueError("unexpected September source capture schema")
    if original.get("disposition")!=ORIGINAL_DISPOSITION or original.get("month")!=MONTH:
        raise ValueError("wrong expected one-time metadata label bug")
    if original.get("source_continuity_and_future_study_ready") is not False or (
        original.get("raw_trade_semantics_validated") is not False
    ) or original.get("orders_placed")!=0:
        raise ValueError("unsafe source qualification claim")
    files=original.get("files",[])
    if not isinstance(files,list) or len(files)!=2 or (
        {x.get("symbol") for x in files}!=set(SYMBOLS)
    ):
        raise ValueError("not exactly two source symbols")
    observed=[]
    for x in files:
        sym=x["symbol"]
        filename=f"{sym}-{MONTH}.csv.gz"
        expected_url=f"{SOURCE}/{sym}/{filename}"
        if x.get("filename")!=filename or x.get("url")!=expected_url:
            raise ValueError("not official September file name and origin")
        if x.get("http_status")!=200 or x.get("redirects_followed")!=0 or x.get("retries")!=0:
            raise ValueError("unexpected source transport")
        bytes_on_disk=(root/filename).stat().st_size
        digest=sha_file(root/filename)
        if x.get("download_bytes")!=bytes_on_disk or x.get("content_length_header")!=bytes_on_disk:
            raise AssertionError("captured source bytes/Content-Length mismatch")
        if x.get("sha256")!=digest or x.get("verified_on_disk_sha256")!=digest:
            raise AssertionError("captured source SHA256 mismatch")
        if x.get("gzip_validation",{}).get("full_gzip_crc_and_footer_checked") is not True:
            raise ValueError("no prior complete gzip validation")
        observed.append({"symbol":sym,"bytes":bytes_on_disk,
                         "source_sha256":digest,
                         "gzip_lines":x["gzip_validation"]["newline_count"]})
    result={**original,
        "disposition":CORRECTED_DISPOSITION,
        "provenance_correction":{
            "reason":"The first-run September source script inherited an uppercase AUGUST status constant from the earlier V22 script. The original unmodified receipt remains on disk.",
            "original_receipt_sha256":hashlib.sha256(raw).hexdigest(),
            "original_disposition":ORIGINAL_DISPOSITION,
            "source_files_bytes_changed":False,
            "sha_and_size_recomputed_from_disk":True,
            "audit_mode":"offline_read_only_source_verification",
            "independently_reconciled_files":observed,
        }
    }
    dest.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    args=p.parse_args()
    x=audit_and_correct(args.root)
    print(json.dumps({"disposition":x["disposition"],
                      "files":x["provenance_correction"]["independently_reconciled_files"],
                      "source_continuity_and_future_study_ready":False},sort_keys=True))

if __name__=="__main__":
    main()
