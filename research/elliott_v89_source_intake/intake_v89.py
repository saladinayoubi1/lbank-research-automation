"""V89 frozen July 2024 official Binance source intake and checksum QA only.

Must consume V88 COMMITTED immutable preregistration before opening a source.
No Elliott pattern evaluation, no strategy parameters, no orders, no P/L.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from research.elliott_v88_replication_lock import lock_v88 as v88

RESEARCH_ONLY = True
LIVE_ENABLED = False
PAPER_ELIGIBLE = False
ENTRY_SIGNAL = False
V52_UNCHANGED = True
RESULT_SCORING_ENABLED = False
BASE = Path(r"E:\NEXUS-QA\elliott-v89-binance-source-20261017")
RECEIPT = BASE / "V89_SOURCE_INTAKE.json"
PREREG_HASH = "fae91774a57f887fc14122b4b1c74a26f6c7ad5daac28488c4e440b836523899"
EXPECTED_LOCK_COMMIT = "6c6e57fefe96246f6fedaa12223d5ed544eb88dc"
MAX_ZIP_BYTES = 4_000_000
MAX_CSV_BYTES = 8_000_000


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def locked_manifest() -> dict:
    raw=v88.ARTIFACT.read_bytes()
    if sha(raw)!=PREREG_HASH:
        raise ValueError("frozen V88 bytes/hash differ from previously committed SHA")
    sealed=json.loads(raw)
    if v88.canonical_bytes(sealed)!=raw:
        raise ValueError("preregistration is not canonical byte-for-byte")
    v88.verify(sealed)
    if len(sealed["scheduled_inputs"])!=28 or any(
            x["downloaded"] is not False or x["zip_sha256"] is not None
            for x in sealed["scheduled_inputs"]):
        raise ValueError("V88 source freeze contaminated by observed data")
    return sealed


def strict_decimal(raw: str) -> Decimal:
    if type(raw) is not str or not raw:
        raise ValueError("missing numeric source")
    try:
        n=Decimal(raw)
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ValueError("malformed source number") from exc
    if not n.is_finite():
        raise ValueError("nonfinite source number")
    return n


def validate_csv(csv_bytes: bytes, day: str) -> dict:
    """Physical 12-column Binance Spot daily 1m complete integrity."""
    if not isinstance(csv_bytes,bytes) or not 0<len(csv_bytes)<=MAX_CSV_BYTES:
        raise ValueError("empty or oversize CSV")
    try:
        table=list(csv.reader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
    except (UnicodeDecodeError,csv.Error) as exc:
        raise ValueError("malformed source CSV") from exc
    if len(table)!=1440:
        raise ValueError(f"expected 1440 closed 1m bars; got {len(table)}")
    try:
        start=int(datetime.strptime(day,"%Y-%m-%d")
                  .replace(tzinfo=timezone.utc).timestamp()*1000)
    except ValueError as exc:
        raise ValueError("invalid locked source UTC date") from exc
    min_low=None
    max_high=None
    for i,row in enumerate(table):
        if len(row)!=12:
            raise ValueError(f"12-column source schema mismatch at row {i}")
        try:
            opening=int(row[0])
            closing=int(row[6])
        except ValueError as exc:
            raise ValueError(f"non-integer UTC source timestamp at {i}") from exc
        if opening!=start+i*60000 or closing!=opening+59999:
            raise ValueError(f"missing, duplicated, unaligned or ill-closed candle {i}")
        op,hi,lo,cl=[strict_decimal(v) for v in row[1:5]]
        if lo<=0 or not (lo<=op<=hi and lo<=cl<=hi):
            raise ValueError(f"invalid physical OHLC at candle {i}")
        if strict_decimal(row[5])<0:
            raise ValueError(f"negative base volume at {i}")
        if min_low is None or lo<min_low:
            min_low=lo
        if max_high is None or hi>max_high:
            max_high=hi
    return {
        "row_count":1440,"first_open_ms":start,
        "last_open_ms":start+1439*60000,
        "end_exclusive_ms":start+1440*60000,
        "member_sha256":sha(csv_bytes),
        "minimum_low":str(min_low),
        "maximum_high":str(max_high),
        "ohlc_numeric": "strict_finite_decimal",
    }


def checksum_name_body(data: bytes, expected_zip: str) -> str:
    try:
        manifest=data.decode("utf-8-sig").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("checksum manifest not UTF-8") from exc
    match=re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?([^/\\\s]+)",manifest)
    if not match or match.group(2)!=expected_zip:
        raise ValueError("official checksum filename or digest malformed")
    return match.group(1).lower()


def verify_committed_lock() -> None:
    import subprocess
    repo=v88.REPOSITORY_ROOT
    rel="docs/evidence/elliott-v88-frozen-independent-replication-20261017/V88_PREREGISTRATION.json"
    prior=subprocess.run(["git","show",EXPECTED_LOCK_COMMIT+":"+rel],
                         cwd=repo,capture_output=True,check=True).stdout
    if sha(prior)!=PREREG_HASH:
        raise ValueError("declared V88 commit did not freeze the source manifest")
    subprocess.run(["git","merge-base","--is-ancestor",EXPECTED_LOCK_COMMIT,"HEAD"],
                   cwd=repo,capture_output=True,check=True)


def fetch_bytes(url: str, cap: int) -> bytes:
    """Validated URL is supplied exclusively from exact frozen manifest."""
    for attempt in range(2):
        try:
            req=urllib.request.Request(
                url,headers={"User-Agent":"NEXUS-V89-Official-Historical-Source-Integrity/1.0"})
            with urllib.request.urlopen(req,timeout=25) as resp:
                if resp.status!=200:
                    raise RuntimeError(f"HTTP status {resp.status}")
                body=resp.read(cap+1)
            if not 0<len(body)<=cap:
                raise ValueError("empty or oversize HTTP source")
            return body
        except (TimeoutError,OSError,urllib.error.URLError) as exc:
            if attempt==1:
                raise RuntimeError(f"official source network failed twice: {type(exc).__name__}") from exc
    raise RuntimeError("unreachable")


def verify_archive(entry: dict, archive: bytes, check: bytes) -> dict:
    official_hash=checksum_name_body(check,entry["zip_file"])
    actual_hash=sha(archive)
    if actual_hash!=official_hash:
        raise ValueError("official SHA256 CHECKSUM does not match ZIP")
    if len(archive)>MAX_ZIP_BYTES:
        raise ValueError("oversize archive")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            infos=zf.infolist()
            if len(infos)!=1 or infos[0].filename!=entry["csv_member"]:
                raise ValueError("unexpected ZIP member: fail closed")
            if infos[0].file_size>MAX_CSV_BYTES:
                raise ValueError("oversize ZIP extracted member")
            member=zf.read(infos[0])
    except (zipfile.BadZipFile,RuntimeError) as exc:
        raise ValueError("invalid ZIP archive") from exc
    daily=validate_csv(member,entry["utc_day"])
    return {
        "name":entry["zip_file"],
        "symbol":entry["symbol"],
        "utc_day":entry["utc_day"],
        "official_zip_url":entry["official_source_url"],
        "official_checksum_url":entry["official_checksum_url"],
        "official_checksum_sha256":official_hash,
        "zip_sha256":actual_hash,
        "checksum_file_sha256":sha(check),
        "csv_member_name":entry["csv_member"],
        "csv_member_sha256":daily["member_sha256"],
        "rows_1m":daily["row_count"],
        "first_open_ms":daily["first_open_ms"],
        "last_open_ms":daily["last_open_ms"],
        "end_exclusive_ms":daily["end_exclusive_ms"],
        "minimum_low":daily["minimum_low"],
        "maximum_high":daily["maximum_high"],
        "verified":True,
        "research_only":True,
    }


def write_exact(path: Path, source: bytes) -> None:
    if path.exists():
        if path.read_bytes()!=source:
            raise ValueError("previous same-name source bytes differ: no overwrite")
        return
    tmp=path.with_name(path.name+".v89temp")
    if tmp.exists():
        raise ValueError("conflicting interrupted temporary source file")
    with tmp.open("xb") as fh:
        fh.write(source)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp,path)


def retrieve_one(entry: dict) -> dict:
    """One frozen pair ZIP + official CHECKSUM, both validated before caching."""
    name=entry["zip_file"]
    if not re.fullmatch(r"(BTCUSDT|ETHUSDT)-1m-2024-07-(0[1-9]|1[0-4])\.zip",name):
        raise ValueError("source filename outside exact V88 frozen calendar")
    path=BASE/name
    check_path=BASE/entry["official_checksum_file"]
    if path.exists()!=check_path.exists():
        raise ValueError("partial archived day without ZIP and CHECKSUM pair")
    if path.exists():
        archive=path.read_bytes()
        check=check_path.read_bytes()
        from_cache=True
    else:
        check=fetch_bytes(entry["official_checksum_url"],2048)
        archive=fetch_bytes(entry["official_source_url"],MAX_ZIP_BYTES)
        from_cache=False
    daily=verify_archive(entry,archive,check)
    if not from_cache:
        write_exact(check_path,check)
        write_exact(path,archive)
    daily["cached_after_verification"]=from_cache
    daily["observed_archive_bytes"]=len(archive)
    return daily


def complete_receipt(sealed: dict, days: list[dict]) -> dict:
    if len(days)!=28 or not all(x.get("verified") is True for x in days):
        raise ValueError("all 28 daily official files must be verified")
    exact=[(e["symbol"],e["utc_day"]) for e in sealed["scheduled_inputs"]]
    if [(x["symbol"],x["utc_day"]) for x in days]!=exact:
        raise ValueError("source days do not match frozen ordered calendar")
    per_symbol={}
    for symbol in sealed["exchange_and_granularity"]["symbols"]:
        series=[x for x in days if x["symbol"]==symbol]
        if len(series)!=14:
            raise ValueError("missing one or more source days for "+symbol)
        for left,right in zip(series,series[1:]):
            if left["end_exclusive_ms"]!=right["first_open_ms"]:
                raise ValueError("gap/overlap across daily source archives")
        rows=sum(x["rows_1m"] for x in series)
        if rows!=sealed["exchange_and_granularity"]["per_symbol_expected_1m_rows"]:
            raise ValueError("wrong total source row count")
        per_symbol[symbol]={
            "source_days":len(series),
            "verified_1m_rows":rows,
            "theoretical_completed_3m_bars":rows//3,
            "theoretical_completed_15m_bars":rows//15,
            "first_open_ms":series[0]["first_open_ms"],
            "exclusive_end_ms":series[-1]["end_exclusive_ms"],
            "week_A_verified_days":7,
            "week_B_verified_days":7,
        }
    return {
        "schema":"nexus.elliott-v89-independent-source-ingestion.v1",
        "status":"VERIFIED_ALL_28_OFFICIAL_DAILY_FILES",
        "recorded_utc":datetime.now(timezone.utc).isoformat(),
        "preregistration_committed_sha":EXPECTED_LOCK_COMMIT,
        "preregistration_bytes_sha256":PREREG_HASH,
        "source_provider":"Binance Official Spot Daily 1m Archive",
        "source_data_exploration_before_preregistration":False,
        "source_period_utc":"2024-07-01 through 2024-07-14 inclusive",
        "source_archive_count":28,
        "per_symbol":per_symbol,
        "archives":days,
        "source_unavailable_or_invalid_days":0,
        "data_source_integrity_verified":True,
        "strategy_evaluation_completed":False,
        "future_holdout_results_available":False,
        "research_only":True,
        "paper_eligible":False,
        "live_enabled":False,
        "entry_signal":False,
        "new_pnl":None,
        "v52_unchanged":True,
        "draft_pr_only":True,
    }


def main() -> dict:
    sealed=locked_manifest()
    verify_committed_lock()
    BASE.mkdir(parents=True,exist_ok=True)
    inputs=sealed["scheduled_inputs"]
    results={}
    errors={}
    print("V89_LOCK_VERIFIED: "+PREREG_HASH,flush=True)
    print("V89_ARCHIVE_DAYS="+str(len(inputs)),flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(retrieve_one,e):e for e in inputs}
        for future in as_completed(futures):
            entry=futures[future]
            name=entry["zip_file"]
            try:
                result=future.result()
                results[name]=result
                print("VALIDATED "+name+" "+result["zip_sha256"],flush=True)
            except Exception as exc:
                errors[name]=f"{type(exc).__name__}: {exc}"
                print("FAILED "+name+": "+errors[name],flush=True)
    ordered=[results[x["zip_file"]] for x in inputs if x["zip_file"] in results]
    if errors or len(ordered)!=28:
        partial={
            "schema":"nexus.elliott-v89-incomplete-source-ingestion.v1",
            "status":"INCOMPLETE_NO_STRATEGY_EVALUATION",
            "expected_count":28,"verified_count":len(ordered),
            "failures":errors,"research_only":True,
            "paper_eligible":False,"new_pnl":None,
        }
        (BASE/"V89_BLOCKED_NOT_FOR_COMMIT.json").write_text(
            json.dumps(partial,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        print(json.dumps(partial,indent=2),flush=True)
        raise RuntimeError("V89 source ingestion incomplete; fail closed")
    report=complete_receipt(sealed,ordered)
    encoded=(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode("utf-8")
    if RECEIPT.exists() and RECEIPT.read_bytes()!=encoded:
        raise RuntimeError("source receipt already exists; never silently overwrite")
    RECEIPT.write_bytes(encoded)
    digest=sha(encoded)
    print(json.dumps({
        "status":report["status"],
        "receipt_file":str(RECEIPT),
        "receipt_sha256":digest,
        "days":len(ordered),
        "by_symbol":report["per_symbol"],
        "new_trading_signals":0,"new_pnl":None,
    },indent=2),flush=True)
    return report


if __name__=="__main__":
    main()
