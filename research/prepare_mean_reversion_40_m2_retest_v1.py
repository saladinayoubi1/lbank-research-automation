"""Prepare pinned Bybit Spot inputs without downloading or touching a Paper profile."""
from __future__ import annotations
import argparse, gzip, hashlib, json, math
from pathlib import Path
import numpy as np
import pandas as pd
STEP=14_400_000
def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda:source.read(1<<20),b""): h.update(block)
    return h.hexdigest()
def ms(text):
    return int(pd.Timestamp(text,tz="UTC").value//1_000_000)
def validate_rows(rows,start,end):
    if len(rows)!=(end-start)//STEP: raise ValueError("incomplete bar count")
    for i,row in enumerate(rows):
        if row[0]!=start+i*STEP: raise ValueError("missing, duplicate or unaligned bar")
        vals=np.asarray(row[1:6],dtype=float)
        if not np.isfinite(vals).all() or min(vals[:4])<=0 or vals[4]<0: raise ValueError("invalid OHLCV")
        if vals[1]<max(vals[0],vals[2],vals[3]) or vals[2]>min(vals[0],vals[1],vals[3]): raise ValueError("invalid OHLC envelope")
def aggregate_month(path,receipt,month):
    path=Path(path)
    if path.is_symlink() or path.name!=f"BTCUSDT-{month}.csv.gz": raise ValueError("wrong raw source identity")
    if path.stat().st_size!=receipt["bytes"] or sha_file(path)!=receipt["sha256"]: raise ValueError("raw transport digest/size mismatch")
    with gzip.open(path,"rt",encoding="utf-8",newline="") as stream:
        header=stream.readline().strip()
    if header!="id,timestamp,price,volume,side": raise ValueError("unexpected original monthly header")
    start=ms(month+"-01")
    end=int((pd.Timestamp(month+"-01",tz="UTC")+pd.offsets.MonthBegin(1)).value//1_000_000)
    accumulated={};last_id=-1;last_time=-1;total=0;zero_size=0;chunks=0
    # Bybit's original named header has five names while data has optional sixth RPI.
    names=["id","timestamp","price","volume","side","rpi"]
    iterator=pd.read_csv(path,compression="gzip",header=None,names=names,skiprows=1,chunksize=250_000,
        dtype={"id":"int64","timestamp":"int64","price":"float64","volume":"float64","side":"string","rpi":"string"},
        on_bad_lines="error")
    for chunk in iterator:
        if len(chunk)==0: continue
        if chunk[["id","timestamp","price","volume","side"]].isna().any().any(): raise ValueError("missing mandatory trade field")
        ids=chunk.id.to_numpy();stamp=chunk.timestamp.to_numpy();p=chunk.price.to_numpy();v=chunk.volume.to_numpy()
        if not (ids[0]>last_id and (np.diff(ids)>0).all()): raise ValueError("duplicate or non-increasing raw trade IDs")
        if not (stamp[0]>=last_time and (np.diff(stamp)>=0).all()): raise ValueError("out-of-order raw trade timestamp")
        if not ((stamp>=start)&(stamp<end)).all(): raise ValueError("raw trades outside declared month")
        if not (np.isfinite(p).all() and np.isfinite(v).all() and (p>0).all() and (v>=0).all()): raise ValueError("invalid raw trade numeric")
        if not chunk.side.isin(["buy","sell"]).all(): raise ValueError("invalid raw trade side")
        if not (chunk.rpi.isna()|chunk.rpi.isin(["0","1"])).all(): raise ValueError("invalid optional RPI")
        zero_size+=int((v==0).sum())
        last_id=int(ids[-1]);last_time=int(stamp[-1]);total+=len(chunk);chunks+=1
        chunk["bucket"]=(stamp//STEP)*STEP
        grouped=chunk.groupby("bucket",sort=True).agg(open=("price","first"),high=("price","max"),low=("price","min"),
            close=("price","last"),volume=("volume","sum"),trades=("id","size"))
        for key,row in grouped.iterrows():
            key=int(key)
            if key not in accumulated: accumulated[key]=[float(row.open),float(row.high),float(row.low),float(row.close),[float(row.volume)],int(row.trades)]
            else:
                a=accumulated[key];a[1]=max(a[1],float(row.high));a[2]=min(a[2],float(row.low));a[3]=float(row.close)
                a[4].append(float(row.volume));a[5]+=int(row.trades)
        if chunks%8==0: print(json.dumps({"month":month,"parsed_rows":total}),flush=True)
    if total!=receipt["rows"] or sum(x[5] for x in accumulated.values())!=total: raise ValueError("original full raw row count mismatch")
    rows=[[key,*[str(x) for x in a[:4]],str(math.fsum(a[4]))] for key,a in sorted(accumulated.items())]
    validate_rows(rows,start,end)
    evidence={**receipt,"month":month,"raw_trade_semantics_validated":True,"raw_rows":total,"bars":len(rows),
        "zero_size_rows":zero_size,"raw_trade_ids_strictly_increasing":True,"timestamps_nondecreasing":True,
        "full_gzip_read_completed":True,"source_header":header,"parser":"5-name header with optional sixth RPI; no skipped malformed records",
        "bar_sha256":hashlib.sha256(canonical(rows)).hexdigest(),"aggregation":"UTC left-closed 4h, first/max/min/last, volume compensated sum",
        "provider_origin_cryptographically_signed":False}
    print(json.dumps({"month":month,"quality":"PASS","rows":total,"bars":len(rows),"bar_sha256":evidence["bar_sha256"]}),flush=True)
    return rows,evidence
def prepare(root,archive,august,september):
    root=Path(root);contract=json.loads((root/"study_contract.json").read_text(encoding="utf-8"))
    if sha_file(archive)!=contract["source_inputs"][0]["sha256"]: raise ValueError("canonical history Parquet SHA mismatch")
    history=pd.read_parquet(archive)
    if history.columns.tolist()!=["timestamp","open","high","low","close","volume","symbol","timeframe"]: raise ValueError("canonical schema")
    if set(history.symbol.astype(str))!={"btc_usdt"} or set(history.timeframe.astype(str))!={"hour4"}: raise ValueError("canonical asset/timeframe")
    rows=[[int(pd.Timestamp(r.timestamp).value//1_000_000),str(r.open),str(r.high),str(r.low),str(r.close),str(r.volume)] for r in history.itertuples(index=False)]
    validate_rows(rows,ms("2022-12-01"),ms("2026-08-01"))
    sources=[{"kind":"pinned historical Parquet","sha256":sha_file(archive),"rows":len(rows),
              "start_ms":rows[0][0],"end_exclusive_ms":rows[-1][0]+STEP,"bar_sha256":hashlib.sha256(canonical(rows)).hexdigest()}]
    for path,receipt,month in [(august,contract["source_inputs"][1],"2026-08"),(september,contract["source_inputs"][2],"2026-09")]:
        new,evidence=aggregate_month(path,receipt,month)
        if new[0][0]!=rows[-1][0]+STEP: raise ValueError("history/month splice gap or overlap")
        rows.extend(new);sources.append(evidence)
    validate_rows(rows,ms("2022-12-01"),ms("2026-10-01"))
    result={"schema":"nexus.mr40-retest-inputs.v1","symbol":"BTCUSDT","timeframe":"hour4","rows":rows,"sources":sources,
            "all_bars_sha256":hashlib.sha256(canonical(rows)).hexdigest(),"research_only":True}
    result["input_digest"]=hashlib.sha256(canonical(result)).hexdigest()
    target=root/"prepared_inputs.json"
    if target.exists(): raise ValueError("refuse overwrite prepared study input")
    target.write_text(json.dumps(result,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps({"input_file":str(target),"rows":len(rows),"input_digest":result["input_digest"],"source_checks":"PASS"}),flush=True)
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument("--root",type=Path,required=True);p.add_argument("--archive",type=Path,required=True)
    p.add_argument("--august",type=Path,required=True);p.add_argument("--september",type=Path,required=True);a=p.parse_args()
    prepare(a.root,a.archive,a.august,a.september)
if __name__=="__main__": main()
