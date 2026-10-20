"""Bybit BTCUSDT Spot October 1-19 source intake only; never computes signals."""
from __future__ import annotations
import argparse,concurrent.futures,csv,gzip,hashlib,json,math,re,urllib.request
from datetime import datetime,timezone
from pathlib import Path
STEP=14_400_000
HEADER=["id","timestamp","price","volume","side","rpi"]
ROOT=Path(r"E:\NEXUS-QA\mr40-october-followup-20261021")
CACHE=Path(r"E:\NEXUS-QA")
URL="https://public.bybit.com/spot/BTCUSDT/BTCUSDT_{day}.csv.gz"

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def hashes(path):
    sha=hashlib.sha256();md5=hashlib.md5()
    with path.open("rb") as source:
        for chunk in iter(lambda:source.read(1048576),b""):
            sha.update(chunk);md5.update(chunk)
    return sha.hexdigest(),md5.hexdigest()

def cached(day,root=ROOT):
    number=int(day[-2:]);name=f"BTCUSDT_{day}.csv.gz"
    if number<=7:folder=CACHE/"elliott-v32-oct01-07-official-20261016"
    elif number==9:folder=CACHE/"elliott-v27-oct09-official-20261016"
    elif number==10:folder=CACHE/"elliott-v28-oct10-official-20261016"
    elif 11<=number<=14:folder=CACHE/"elliott-v29-oct11-14-official-20261016"
    elif number==17:folder=CACHE/"bybit-official-spot-source-20261018"/"raw-sample"
    else:folder=root/"raw"
    path=folder/name
    return path if path.is_file() else root/"raw"/name

def acquire(day,root):
    url=URL.format(day=day)
    request=urllib.request.Request(url,method="HEAD",headers={"User-Agent":"NEXUS-Research/1.0"})
    with urllib.request.urlopen(request,timeout=30) as response:
        if response.status!=200 or response.url!=url:raise ValueError("unexpected official HEAD response")
        length=int(response.headers["Content-Length"])
        if not 100<length<200_000_000:raise ValueError("invalid official source length")
        etag=response.headers.get("ETag","").strip('"')
        modified=response.headers.get("Last-Modified")
    path=cached(day,root);reuse=path.is_file()
    if not reuse:
        path.parent.mkdir(parents=True,exist_ok=True);part=path.with_suffix(path.suffix+".part")
        if part.exists():raise ValueError("unresolved partial download")
        with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"NEXUS-Research/1.0"}),timeout=30) as response:
            if response.status!=200 or response.url!=url:raise ValueError("unexpected official download response")
            with part.open("xb") as out:
                total=0
                while True:
                    block=response.read(1048576)
                    if not block:break
                    total+=len(block)
                    if total>length:raise ValueError("source exceeds official length")
                    out.write(block)
        if total!=length:raise ValueError("incomplete source download")
        part.rename(path)
    if path.stat().st_size!=length:raise ValueError("cached source length differs from official host")
    sha,md5=hashes(path)
    etag_match=bool(re.fullmatch("[a-fA-F0-9]{32}",etag)) and md5.lower()==etag.lower()
    if re.fullmatch("[a-fA-F0-9]{32}",etag) and not etag_match:
        raise ValueError("cached bytes differ from official ETag")
    return {"date":day,"url":url,"path":str(path),"bytes":length,"sha256":sha,"md5":md5,
            "official_etag":etag,"etag_is_plain_md5":bool(re.fullmatch("[a-fA-F0-9]{32}",etag)),
            "official_etag_md5_match":etag_match,"last_modified":modified,
            "https_verified":True,"http_status":200,"reused":reuse}

def aggregate(path,day,expected_sha):
    if hashes(path)[0]!=expected_sha:raise ValueError("raw source substitution")
    midnight=int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()*1000)
    bins=[None]*6;last_id=-1;last_time=-1;count=0;zero_quantity=0
    with gzip.open(path,"rt",encoding="utf-8",newline="") as source:
        reader=csv.reader(source);header=next(reader)
        if header not in (HEADER,HEADER[:-1]):raise ValueError("unknown Spot schema")
        for row in reader:
            if len(row)!=6:raise ValueError("wrong raw field count")
            ident=int(row[0]);stamp=int(row[1]);price=float(row[2]);quantity=float(row[3])
            if ident<=last_id or stamp<last_time:raise ValueError("out-of-order or duplicate trade")
            if not midnight<=stamp<midnight+86_400_000:raise ValueError("wrong UTC source day")
            if not math.isfinite(price) or price<=0 or not math.isfinite(quantity) or quantity<0:
                raise ValueError("invalid trade price/quantity")
            if row[4] not in ("buy","sell") or row[5] not in ("0","1"):
                raise ValueError("invalid side or RPI")
            last_id=ident;last_time=stamp;count+=1;zero_quantity+=int(quantity==0)
            index=(stamp-midnight)//STEP
            if bins[index] is None:
                bins[index]={"open":price,"high":price,"low":price,"close":price,"volume":quantity,
                             "count":1,"first_ms":stamp,"last_ms":stamp}
            else:
                bar=bins[index];bar["high"]=max(bar["high"],price);bar["low"]=min(bar["low"],price)
                bar["close"]=price;bar["volume"]+=quantity;bar["count"]+=1;bar["last_ms"]=stamp
    if not count or any(x is None for x in bins):raise ValueError("missing observed 4h bucket")
    if sum(x["count"] for x in bins)!=count:raise ValueError("trade/bucket count mismatch")
    rows=[[midnight+i*STEP,*[str(bar[k]) for k in ("open","high","low","close","volume")]]
          for i,bar in enumerate(bins)]
    return {"date":day,"header":header,"rows_validated":count,"zero_quantity_rows":zero_quantity,
            "gzip_crc_to_eof":True,"ids_unique_and_increasing_within_day":True,
            "ids_not_assumed_globally_unique_across_days":True,"timestamps_nondecreasing":True,
            "observed_4h_buckets":6,"bucket_trade_counts":[x["count"] for x in bins],
            "first_trade_ms":bins[0]["first_ms"],"last_trade_ms":bins[-1]["last_ms"],"rows":rows}

def main(root):
    manifest_path=root/"source_manifest.json"
    if manifest_path.exists():raise ValueError("refuse source manifest overwrite")
    days=[f"2026-10-{d:02d}" for d in range(1,20)]
    items=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(acquire,day,root):day for day in days}
        for future in concurrent.futures.as_completed(futures):
            item=future.result();items.append(item)
            print(json.dumps({"stage":"sealed_source","date":item["date"],"bytes":item["bytes"],"reused":item["reused"]}),flush=True)
    items.sort(key=lambda x:x["date"])
    manifest={"schema":"nexus.mr40-october-source-manifest.v1","created_utc":datetime.now(timezone.utc).isoformat(),
              "complete_utc_days":days,"files":items,"orders":0,"live_enabled":False}
    manifest["digest"]=digest(manifest)
    manifest_path.write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8",newline="\n")
    audits=[];rows=[]
    for item in items:
        audit=aggregate(Path(item["path"]),item["date"],item["sha256"])
        rows.extend(audit.pop("rows"));audits.append(audit)
        print(json.dumps({"stage":"audited_day","date":item["date"],"trades":audit["rows_validated"]}),flush=True)
    if len(rows)!=114 or any(rows[i][0]-rows[i-1][0]!=STEP for i in range(1,len(rows))):
        raise ValueError("incomplete October cadence")
    extension={"schema":"nexus.mr40-october-input-extension.v1","source_manifest_digest":manifest["digest"],
               "base_input_digest":"fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe",
               "start_utc":"2026-10-01T00:00:00+00:00","end_exclusive_utc":"2026-10-20T00:00:00+00:00",
               "rows":rows,"audits":audits,"no_imputed_candles":True,"orders":0,"live_enabled":False}
    extension["digest"]=digest(extension)
    (root/"october_input_extension.json").write_text(json.dumps(extension,separators=(",",":"))+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"stage":"intake_complete","source_digest":manifest["digest"],"extension_digest":extension["digest"],
                      "days":19,"bars":len(rows),"trades":sum(x["rows_validated"] for x in audits),
                      "cached_files":sum(x["reused"] for x in items),"new_downloads":sum(not x["reused"] for x in items),
                      "all_etag_md5_match":all(x["official_etag_md5_match"] for x in items)}),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--root",type=Path,default=ROOT);args=parser.parse_args();main(args.root)
