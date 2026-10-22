"""Descriptive entry-state comparison; NEVER selects/tunes filters or reruns strategy."""
import datetime as dt
import gzip,hashlib,json,statistics,os
from decimal import Decimal as D
from pathlib import Path

ROOT=Path(os.environ.get("MR40_ENTRY_AUDIT_ROOT",r"E:\NEXUS-Research\MR40-Entry-Quality-20261022"))
DATA=Path(os.environ.get("MR40_ENTRY_AUDIT_INPUTS",r"E:\NEXUS-Research\MR40-Staged-Entry-20261022\source\inputs"))
rows=json.loads((DATA/"bybit_prepared_inputs.json").read_bytes())["rows"]+json.loads((DATA/"bybit_october_input_extension.json").read_bytes())["rows"]
sha=hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
assert sha=="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
base={}
with gzip.open(ROOT/"results"/"ledger.jsonl.gz","rt",encoding="utf-8") as f:
 for line in f:
  x=json.loads(line);k=x["key"]
  if k["venue"]=="Bybit" and k["capital"]==10000 and k["profile"]=="normal" and k["case"]=="baseline" and k["window"] in ("train","evaluation"):
   base[k["window"]]=x
def med(v):
 return round(statistics.median(v),3) if v else None
def feat(j):
 op,hi,lo,cl=[float(v) for v in rows[j][1:5]]
 cp=float(rows[j-1][4])
 tr=max(hi-lo,abs(hi-cp),abs(lo-cp))
 atr=sum(max(float(rows[k][2])-float(rows[k][3]),abs(float(rows[k][2])-float(rows[k-1][4])),abs(float(rows[k][3])-float(rows[k-1][4]))) for k in range(j-14,j))/14
 return {"short_drift6_pct":100*(cl/float(rows[j-6][4])-1),
         "long_drift60_pct":100*(cl/float(rows[j-60][4])-1),
         "trend180_pct":100*(cl/float(rows[j-180][4])-1),
         "candle_body_pct":100*(cl/op-1),
         "tr_to_prev_atr":tr/atr}
out={"schema":"mr40.entry-quality.entry-conditions-audit.v1",
     "input_rows_sha256":sha,"source_ledger_sha256":"2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e",
     "limitation":"Labels realized from future holding outcomes. Descriptive only; no inferred causal entry filter and no truly unseen forward data.",
     "windows":{}}
for win in ("train","evaluation"):
 items=[]
 for p in base[win]["positions"]:
  j=p["entry"]["signal_index"];f=feat(j)
  pnl=float(p["net_pnl_usdt"])
  items.append({"entry_utc":dt.datetime.fromtimestamp(p["entry"]["fill_ms"]/1000,dt.timezone.utc).isoformat(),"pnl":round(pnl,2),"winner":pnl>0,**{k:round(v,4) for k,v in f.items()}})
 groups={}
 for name,condition in (("winners",True),("losers",False)):
  subset=[x for x in items if x["winner"]==condition]
  groups[name]={"count":len(subset),"pnl_sum":round(sum(x["pnl"] for x in subset),2),
      "median_conditions":{k:med([v[k] for v in subset]) for k in ("short_drift6_pct","long_drift60_pct","trend180_pct","candle_body_pct","tr_to_prev_atr")}}
 out["windows"][win]={"groups":groups,"entries":items}
out["digest"]=hashlib.sha256(json.dumps(out,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
path=Path(os.environ.get("MR40_ENTRY_AUDIT_OUTPUT",str(ROOT/"entry_conditions_audit.json")))
assert not path.exists()
path.write_text(json.dumps(out,sort_keys=True,separators=(",",":"),ensure_ascii=False)+"\n",encoding="utf8")
print(json.dumps({"digest":out["digest"],"summary":{k:v["groups"] for k,v in out["windows"].items()},
"worst_eval":sorted(out["windows"]["evaluation"]["entries"],key=lambda x:x["pnl"])[:4]},ensure_ascii=False),flush=True)
