"""NEXUS V23: acquire EXACTLY two official September-2026 Bybit spot raw-trade gzips.

Single-shot GET, no redirects/retries/credentials/market API, isolated new folder.
Capture SHA256 and verify complete gzip stream and CSV line count using constant
memory. Transport integrity is NOT a complete trade-identity/price QA, and
no claim of V17 holdout readiness or profitable Elliott inference is made.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
from datetime import datetime, timezone
import requests

ROOT_URL="https://public.bybit.com/spot"
PAIR=("BTCUSDT","ETHUSDT")
MONTH="2026-09"
MAX_COMPRESSED=200_000_000
MAX_UNCOMPRESSED=5_000_000_000
CHUNK=1024*1024

RESEARCH_ONLY=True
AUTO_DEMO=False
LIVE_ENABLED=False
ORDERS_PLACED=0

def sha256_file(file:Path)->str:
    h=hashlib.sha256()
    with file.open("rb") as fd:
        for chunk in iter(lambda:fd.read(CHUNK),b""):
            h.update(chunk)
    return h.hexdigest()

def verify_gzip_stream(file:Path)->dict:
    """Consumes compressed stream through CRC/footer without loading CSV in RAM."""
    seen=0
    lines=0
    head=b""
    final=b""
    with gzip.open(file,"rb") as stream:
        while block:=stream.read(CHUNK):
            seen+=len(block)
            if seen>MAX_UNCOMPRESSED:
                raise ValueError("decompression safety limit exceeded")
            lines+=block.count(b"\n")
            if not head:
                head=block.partition(b"\n")[0][:300]
            final=block[-100:]
    if lines < 1000 or not head or seen < 10_000:
        raise ValueError("monthly source stream unexpectedly small or empty")
    if b"," not in head:
        raise ValueError("source first row not valid CSV-shaped record")
    return {"uncompressed_bytes":seen,"newline_count":lines,
            "first_row_preview":head.decode("utf-8-sig",errors="replace"),
            "last_chunk_ends_newline":final.endswith(b"\n"),
            "full_gzip_crc_and_footer_checked":True}

def capture(output:Path)->dict:
    if output.exists():
        raise FileExistsError("isolated output already exists: refuse replace/repeat")
    output.mkdir(parents=True,exist_ok=False)
    rows=[]
    for symbol in PAIR:
        filename=f"{symbol}-{MONTH}.csv.gz"
        url=f"{ROOT_URL}/{symbol}/{filename}"
        dest=output/filename
        part=output/(filename+".part")
        if dest.exists() or part.exists():
            raise FileExistsError("capture source collision")
        digest=hashlib.sha256()
        size=0
        with requests.Session() as session:
            with session.get(url,stream=True,timeout=(12,60),
                             allow_redirects=False,
                             headers={"Accept":"application/octet-stream"}) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"Official public archive HTTP {response.status_code}; no retry, no bypass")
                length=response.headers.get("Content-Length")
                expected=int(length) if length is not None and length.isdecimal() else None
                if expected is not None and not 0<expected<=MAX_COMPRESSED:
                    raise ValueError("official source reported invalid file size")
                meta={"symbol":symbol,"filename":filename,"url":url,"http_status":200,
                      "content_length_header":expected,
                      "last_modified":response.headers.get("Last-Modified"),
                      "fetched_at_utc":datetime.now(timezone.utc).isoformat(),
                      "redirects_followed":0,"retries":0}
                with part.open("xb") as writer:
                    for block in response.iter_content(CHUNK):
                        if not block:
                            continue
                        size+=len(block)
                        if size>MAX_COMPRESSED:
                            raise ValueError("compressed file size safety limit")
                        writer.write(block)
                        digest.update(block)
        if size<10_000 or expected is not None and size!=expected:
            raise ValueError("official file missing bytes")
        if sha256_file(part)!=digest.hexdigest():
            raise AssertionError("downloaded file SHA256 drifted on disk")
        stream=verify_gzip_stream(part)
        os.replace(part,dest)
        file_receipt={**meta,"download_bytes":size,"sha256":digest.hexdigest(),
                      "verified_on_disk_sha256":sha256_file(dest),
                      "gzip_validation":stream,"trade_parser_audit_complete":False}
        rows.append(file_receipt)
        # Atomic progress receipt for the first file even if the second fails.
        tmp=output/"PROGRESS.tmp"
        tmp.write_text(json.dumps({"files_completed":rows,"orders_placed":0},
                                  indent=2,sort_keys=True)+"\n",encoding="utf-8")
        os.replace(tmp,output/"PROGRESS.json")
        print(f"CAPTURED {symbol} {size} SHA256={digest.hexdigest()} lines={stream['newline_count']}",flush=True)
    result={
        "schema":"nexus.elliott-v23-official-september-gzip-acquisition.v1",
        "disposition":"PASS_TWO_SEPTEMBER_ARCHIVES_TRANSPORT_ONLY",
        "month":MONTH,
        "files":rows,
        "research_only":True,"live_enabled":False,"auto_demo":False,
        "orders_placed":0,"direct_public_host":ROOT_URL,
        "network_call_scope":"two direct public archive GET requests; zero redirects and retries",
        "raw_trade_semantics_validated":False,
        "source_continuity_and_future_study_ready":False,
        "existing_legacy_v19_v20_v21_mutated":False
    }
    temp=output/"CAPTURE_RECEIPT.tmp"
    temp.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.replace(temp,output/"CAPTURE_RECEIPT.json")
    return result

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--new-root",required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps({"disposition":capture(args.new_root)["disposition"]}),flush=True)
