"""MR40 offline read-only audit: intrabar-low lower bound and trade-event attribution."""
from __future__ import annotations
import collections
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path

D=Decimal
START_END={"train":("2023-01-01","2025-01-01"),"evaluation":("2025-01-01","2026-10-20"),"full":("2023-01-01","2026-10-20")}
SOURCE_DIGEST="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"

def canonical(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def tstamp(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp()*1000)
def lower_bound(frame,record,window,capital):
    start,end=(tstamp(x) for x in START_END[window])
    positions=[i for i,r in enumerate(frame) if start<=r[0]<end]
    assert positions and frame[positions[0]][0]==start and frame[positions[-1]][0]+14400000==end
    offset=positions[0]
    bybar=collections.defaultdict(list)
    for f in record["fills"]:
        bybar[f["bar_index"]].append(f)
    cash=D(capital);qty=D(0)
    peak=float(capital);worst_close=worst_low=0.0
    max_under=under=0
    zero_cost=0
    for i in positions:
        terminal=[]
        for fill in bybar[i]:
            if fill["reason"]=="terminal_close":
                terminal.append(fill)
                continue
            assert D(fill["cash_before"])==cash
            cash=D(fill["cash_after"])
            delta=D(fill["quantity"])
            qty+=delta if fill["side"]=="buy" else -delta
            assert qty>=0
        intralow=float(cash+qty*D(str(frame[i][3])))
        worst_low=max(worst_low,100*max(0,1-intralow/peak))
        for fill in terminal:
            assert D(fill["cash_before"])==cash
            cash=D(fill["cash_after"])
            qty-=D(fill["quantity"])
        close=float(cash+qty*D(str(frame[i][4])))
        worst_close=max(worst_close,100*max(0,1-close/peak))
        peak=max(peak,close)
        under=under+1 if close<peak-1e-8 else 0
        max_under=max(max_under,under)
    assert not qty
    return {"close_dd_pct":worst_close,"low_bound_dd_pct":max(worst_low,worst_close),
            "underwater_days":max_under/6, "last_equity":float(cash)}

def main(inputs,ledger,results_path,dest):
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    frame=b["rows"]+e["rows"]
    assert hashlib.sha256(canonical(frame)).hexdigest()==SOURCE_DIGEST
    recorded={}
    with gzip.open(ledger,"rt",encoding="utf-8") as inp:
        for line in inp:
            x=json.loads(line);key=x["key"]
            if key["venue"]=="Bybit" and key["capital"]==10000 and key["window"] in START_END and key["profile"] in ("normal","stress"):
                recorded[(key["window"],key["case"],key["profile"])]=x
    result=json.loads((results_path).read_bytes())
    metrics={(m["window"],m["case"],m["profile"]):m for m in result["rows"]
             if m["venue"]=="Bybit" and m["capital"]==10000}
    checks=0;tables=[]
    for key,x in sorted(recorded.items()):
        window,case,profile=key
        audit=lower_bound(frame,x,window,10000)
        orig=metrics[key]
        assert abs(audit["close_dd_pct"]-orig["max_close_drawdown_pct"])<1e-7,(key,audit,orig)
        assert abs(audit["last_equity"]-10000-orig["net_pnl_usdt"])<1e-6,(key,audit,orig)
        assert abs(audit["underwater_days"]-orig["longest_underwater_days"])<1e-7,(key,audit,orig)
        tables.append({"window":window,"case":case,"profile":profile,
                       "net_pnl":round(orig["net_pnl_usdt"],2),
                       **{k:round(v,3) for k,v in audit.items() if k!="last_equity"}})
        checks+=1

    paired=[]
    for label in ("trim25at5","trim50at5","trim75at5","trim50at8","trim75at8"):
        b=recorded[("full","baseline","normal")]["positions"]
        a=recorded[("full",label,"normal")]["positions"]
        assert len(a)==len(b)==47
        for old,new in zip(b,a):
            assert old["entry"]["fill_ms"]==new["entry"]["fill_ms"]
        impacts=[]
        for old,new in zip(b,a):
            delta=new["net_pnl_usdt"]-old["net_pnl_usdt"]
            impacts.append({"entry_utc":datetime.fromtimestamp(old["entry"]["fill_ms"]/1000,timezone.utc).isoformat(),
                           "baseline_trade_pnl":round(old["net_pnl_usdt"],2),
                           "candidate_trade_pnl":round(new["net_pnl_usdt"],2),
                           "delta_usdt":round(delta,2),"trimmed":new["trimmed"]})
        paired.append({"case":label,"trimmed_positions":[x for x in impacts if x["trimmed"]],
                       "worst_deltas":sorted(impacts,key=lambda x:x["delta_usdt"])[:3],
                       "best_deltas":sorted(impacts,key=lambda x:x["delta_usdt"],reverse=True)[:3]})
    out={"schema":"mr40.partial-trim-risk-attribution.v1",
         "definition":"Intra-bar low equity vs previous peak of four-hour close equity, assuming open fills occur before candle low. A lower bound, not exact achievable drawdown; no tick path or depth. Annualized metrics not changed.",
         "frame_sha256":SOURCE_DIGEST,"model_digest":result["digest"],
         "ledger_sha256":hashlib.sha256((ledger).read_bytes()).hexdigest(),
         "account_checks":checks,"risk_table":tables,"paired_trades":paired}
    out["digest"]=hashlib.sha256(canonical(out)).hexdigest()
    if dest.exists():raise RuntimeError("refuse_overwrite")
    dest.write_bytes(canonical(out)+b"\n")
    print(json.dumps({"checks":checks,"digest":out["digest"],
       "risk_full_normal":[x for x in tables if x["window"]=="full" and x["profile"]=="normal"],
       "risk_eval_normal":[x for x in tables if x["window"]=="evaluation" and x["profile"]=="normal"],
       "trim75at8_event_details":paired[-1]["trimmed_positions"]},ensure_ascii=False),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("inputs","ledger","results_path","dest"):
        p.add_argument("--"+n.replace("_","-"),required=True,type=Path)
    main(**vars(p.parse_args()))