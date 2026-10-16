"""Research-only external Binance Spot source intake. No trading or optimization."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(r"E:\NEXUS-QA\elliott-v80-binance-source-20261016")
ROOT = "https://data.binance.vision/data/spot/daily/klines"
DATES = ("2024-03-01", "2024-03-02")
SYMBOLS = ("BTCUSDT", "ETHUSDT")

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(b):
    return hashlib.sha256(b).hexdigest()

def acquire(url, dest):
    received_start = now()
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "NEXUS-research-source-audit/1.0"}), timeout=25) as response:
        body = response.read()
        status = response.status
    received_end = now()
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {url}")
    dest.write_bytes(body)
    return body, {"url":url, "status":status, "started_utc":received_start, "finished_utc":received_end}

def read_rows(zbytes, expected_csv, expected_day):
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        if z.namelist() != [expected_csv]:
            raise AssertionError(f"ZIP member mismatch: {z.namelist()}")
        csvbytes = z.read(expected_csv)
    rows=list(csv.reader(io.StringIO(csvbytes.decode("utf-8-sig"))))
    if len(rows) != 1440:
        raise AssertionError(f"Expected 1440 1m rows, got {len(rows)}")
    day_ms = int(datetime.strptime(expected_day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()*1000)
    for i,row in enumerate(rows):
        if len(row) != 12:
            raise AssertionError(f"CSV schema mismatch at {i}: {len(row)}")
        t=int(row[0])
        if t != day_ms + i*60000:
            raise AssertionError(f"Gap/duplicate/microsecond mismatch at {i}: {t}")
        o,h,l,c=map(float,row[1:5])
        if not (0 < l <= min(o,c) <= max(o,c) <= h):
            raise AssertionError(f"Invalid OHLC at row {i}")
        if int(row[6]) != t + 59999:
            raise AssertionError(f"closeTime mismatch at row {i}")
    return rows, sha(csvbytes)

def aggregate(rows, stride):
    out=[]
    for offset in range(0,len(rows),stride):
        chunk=rows[offset:offset+stride]
        if len(chunk) != stride:
            raise AssertionError("Partial aggregate")
        t=int(chunk[0][0])
        if t % (stride*60000):
            raise AssertionError(f"Nonaligned {stride}m bar: {t}")
        out.append([t,chunk[0][1],str(max(float(x[2]) for x in chunk)),
                    str(min(float(x[3]) for x in chunk)),chunk[-1][4],
                    str(sum(float(x[5]) for x in chunk)),int(chunk[-1][6])])
    return out

def main():
    BASE.mkdir(parents=True,exist_ok=True)
    report={"stage":"V80", "label":"EXPLORATORY_EXTERNAL_SOURCE_ONLY_NOT_HOLDOUT",
            "scope":"Binance official Spot 1m, two historical days, source intake and continuity QA",
            "bybit_execution":False,"demo_eligible":False,"live_trading":False,
            "start_utc":now(),"files":[],"symbols":{}}
    for symbol in SYMBOLS:
        full=[]
        for day in DATES:
            stem=f"{symbol}-1m-{day}.zip"
            url=f"{ROOT}/{symbol}/1m/{stem}"
            manifest_url=url+".CHECKSUM"
            manifest_bytes,manifest_receipt=acquire(manifest_url,BASE/(stem+".CHECKSUM"))
            manifest=manifest_bytes.decode("utf-8-sig").strip()
            match=re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?([^/\\\s]+)",manifest)
            if not match or match.group(2)!=stem:
                raise AssertionError(f"Bad official checksum manifest: {manifest!r}")
            zbytes,data_receipt=acquire(url,BASE/stem)
            actual=sha(zbytes)
            if actual.lower()!=match.group(1).lower():
                raise AssertionError(f"Official checksum mismatch: {stem}")
            rows,csv_hash=read_rows(zbytes,stem.removesuffix(".zip")+".csv",day)
            full.extend(rows)
            report["files"].append({"name":stem,"sha256":actual,"official_checksum_sha256":match.group(1).lower(),
                                    "manifest_sha256":sha(manifest_bytes),"csv_member_sha256":csv_hash,
                                    "rows_1m":len(rows),"verified":True,"data_receipt":data_receipt,
                                    "checksum_receipt":manifest_receipt})
        for i,row in enumerate(full):
            expected=int(full[0][0])+60000*i
            if int(row[0])!=expected:
                raise AssertionError(f"Cross-date gap for {symbol} at {i}")
        summary={"total_1m":len(full),"first_open_ms":int(full[0][0]),"last_open_ms":int(full[-1][0])}
        for stride in (3,15):
            bars=aggregate(full,stride)
            out=BASE/f"{symbol}-{stride}m-V80_EXPLORATORY.csv"
            with out.open("w",newline="",encoding="utf-8") as fp:
                writer=csv.writer(fp); writer.writerow(["open_time_ms","open","high","low","close","volume","close_time_ms"]);writer.writerows(bars)
            summary[f"bars_{stride}m"]=len(bars)
            summary[f"aggregated_{stride}m_csv_sha256"]=sha(out.read_bytes())
        report["symbols"][symbol]=summary
    report["end_utc"]=now()
    path=BASE/"V80_OFFICIAL_BINANCE_SOURCE_QA.json"
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print("V80_SOURCE_QA_PASS")
    print(json.dumps({"results":report["symbols"],"files":[{"name":f["name"],"sha256":f["sha256"],"verified":f["verified"]} for f in report["files"]],"receipt":str(path),"receipt_sha256":sha(path.read_bytes()),"completed_utc":report["end_utc"]},indent=2))
if __name__=="__main__":
    main()
