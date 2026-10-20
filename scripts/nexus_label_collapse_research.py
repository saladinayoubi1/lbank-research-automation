"""One preregistered raw-label research diagnostic; no network, orders or admission."""
from __future__ import annotations
import argparse, csv, gzip, hashlib, json, math, time, unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import numpy as np
import pandas as pd

STEP=14_400_000
SYMBOLS=("BTCUSDT","ETHUSDT")
PROFILES={"conservative":(10,5),"stress":(15,10),"severe":(25,15)}
CAPTURE="edbf345dc3bc1094f7595aebefb191181f8ca878e9dc0f8d6fb19c5562ccbc98"
SOURCE_QA="1141ba15a6bed8fb5388e2ef390c01dc563cd874916dd89d986dfd768e0ae5f0"

def digest(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda:f.read(1024*1024),b""): h.update(part)
    return h.hexdigest()
def save(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n",encoding="utf-8")
    tmp.replace(path)
def read(path): return json.loads(Path(path).read_text(encoding="utf-8-sig"))
def checked_json(path,expected):
    obj=read(path)
    assert obj["digest"]==expected==digest({k:v for k,v in obj.items() if k!="digest"})
    return obj
def feature_float(path,start):
    buckets=[{"buy_quote":0.0,"sell_quote":0.0,"volume":0.0,"trades":0} for _ in range(6)]
    previous_id=previous_ms=-1;count=0
    for frame in pd.read_csv(path,compression="gzip",chunksize=250_000,
          dtype={"id":"int64","timestamp":"int64","price":"float64","volume":"float64","side":"string","rpi":"int8"}):
        assert list(frame.columns)==["id","timestamp","price","volume","side","rpi"]
        ids=frame.id.to_numpy();ms=frame.timestamp.to_numpy()
        p=frame.price.to_numpy();v=frame.volume.to_numpy();side=frame.side.to_numpy()
        assert len(ids) and ids[0]>previous_id and ms[0]>=previous_ms
        assert (np.diff(ids)>0).all() and (np.diff(ms)>=0).all()
        assert ((ms>=start)&(ms<start+6*STEP)).all()
        assert np.isfinite(p).all() and np.isfinite(v).all() and (p>0).all() and (v>0).all()
        assert frame.side.isin(["buy","sell"]).all() and frame.rpi.isin([0,1]).all()
        bucket=(ms-start)//STEP;q=p*v
        for i in range(6):
            mask=bucket==i
            if not mask.any():continue
            b=buckets[i];pp=p[mask];vv=v[mask];mm=ms[mask]
            if not b["trades"]:b.update(open=float(pp[0]),high=float(pp.max()),low=float(pp.min()),first_trade_ms=int(mm[0]))
            else:b["high"]=max(b["high"],float(pp.max()));b["low"]=min(b["low"],float(pp.min()))
            b["close"]=float(pp[-1]);b["last_trade_ms"]=int(mm[-1])
            b["volume"]+=float(vv.sum());b["trades"]+=int(mask.sum())
            b["buy_quote"]+=float(q[mask&(side=="buy")].sum())
            b["sell_quote"]+=float(q[mask&(side=="sell")].sum())
        previous_id=int(ids[-1]);previous_ms=int(ms[-1]);count+=len(ids)
    assert all(b["trades"] for b in buckets)
    return buckets,count
def feature_decimal(path,start):
    # Separate scalar csv/Decimal implementation; no producer arrays or group-by.
    totals=[[Decimal(0),Decimal(0),0] for _ in range(6)]
    with gzip.open(path,"rt",encoding="utf-8",newline="") as f:
        r=csv.reader(f);assert next(r)==["id","timestamp","price","volume","side","rpi"]
        for fields in r:
            assert len(fields)==6 and fields[4] in ("buy","sell")
            number=(int(fields[1])-start)//STEP;assert 0<=number<6
            p=Decimal(fields[2]);v=Decimal(fields[3])
            assert p.is_finite() and v.is_finite() and p>0 and v>0
            totals[number][0 if fields[4]=="buy" else 1]+=p*v
            totals[number][2]+=1
    return totals
def build_features(contract_path,root,out,budget=600):
    c=read(contract_path);scope=c["scope"]
    assert scope["end_exclusive_utc"]=="2026-10-19T00:00:00Z" and c["authority"]["live_enabled"] is False
    assert c["candidate_id"]=="label_collapse_reclaim_4h_v1"
    summary=checked_json(root/"capture-summary.json",CAPTURE)
    source=checked_json(root/"independent-source-qa.json",SOURCE_QA)
    assert summary["completed_files"]==158 and summary["raw_trade_rows"]==70815420
    assert summary["end_exclusive_utc"]==scope["end_exclusive_utc"]
    assert source["verified_files"]==158 and source["all_daily_bars_independently_reconstructed"] is True
    start_date=datetime(2026,8,1,tzinfo=timezone.utc)
    expected=[(s,(start_date+timedelta(days=i)).date().isoformat()) for i in range(79) for s in SYMBOLS]
    assert [(r["symbol"],r["date"]) for r in summary["files"]]==expected
    manifest=[]
    for item in summary["files"]:
        name=item["symbol"]+"_"+item["date"];raw=root/"raw"/(name+".csv.gz")
        receipt=root/"receipts"/(name+".json")
        assert not raw.is_symlink() and not receipt.is_symlink()
        assert sha(raw)==item["raw_file_sha256"] and sha(receipt)==item["receipt_sha256"]
        cell=read(receipt)
        assert cell["digest"]==digest({k:v for k,v in cell.items() if k!="digest"})
        assert cell["raw_file_sha256"]==item["raw_file_sha256"]
        manifest.append((item,raw,cell))
    inputs={"contract_sha256":sha(contract_path),"producer_sha256":sha(__file__),
            "capture_digest":CAPTURE,"source_qa_digest":SOURCE_QA}
    bars={s:[] for s in SYMBOLS};began=time.monotonic();count=0;new=0
    for item,raw,cell in manifest:
        name=item["symbol"]+"_"+item["date"];checkpoint=out/"daily"/(name+".json")
        if checkpoint.exists():
            part=read(checkpoint);assert part["inputs"]==inputs and part["raw_sha256"]==item["raw_file_sha256"]
            assert part["digest"]==digest({k:v for k,v in part.items() if k!="digest"})
        else:
            start=int(datetime.fromisoformat(item["date"]).replace(tzinfo=timezone.utc).timestamp()*1000)
            made,n=feature_float(raw,start);decimal=feature_decimal(raw,start)
            assert n==item["raw_trade_rows"]==sum(d[2] for d in decimal)
            offset=len(bars[item["symbol"]])
            for i,(b,d) in enumerate(zip(made,decimal)):
                known=source["bars"][item["symbol"]][offset+i]
                assert datetime.fromisoformat(known["timestamp"]).timestamp()*1000==start+i*STEP
                for f in ("open","high","low","close"):
                    assert abs(b[f]-float(known[f]))<=1e-8
                assert math.isclose(b["volume"],float(known["volume"]),rel_tol=1e-10,abs_tol=1e-6)
                receipt_bar=cell["fully_observed_4h_bars"][i]
                assert all(b[k]==receipt_bar[k] for k in ("trades","first_trade_ms","last_trade_ms"))
                assert b["trades"]==d[2]
                for key,value in zip(("buy_quote","sell_quote"),d[:2]):
                    assert math.isclose(b[key],float(value),rel_tol=2e-12,abs_tol=1e-5)
                    b[key+"_decimal"]=str(value)
                total=b["buy_quote"]+b["sell_quote"]
                b["imbalance"]=abs(b["buy_quote"]-b["sell_quote"])/total
                exact=abs(d[0]-d[1])/(d[0]+d[1])
                assert abs(b["imbalance"]-float(exact))<=1e-12
                assert (b["imbalance"]>=.20)==(exact>=Decimal(".20"))
                assert (b["imbalance"]<=.05)==(exact<=Decimal(".05"))
                b["timestamp"]=start+i*STEP;b["source_raw_sha256"]=item["raw_file_sha256"]
            part={**{"inputs":inputs,"raw_sha256":item["raw_file_sha256"],"raw_rows":n,"bars":made}}
            part["digest"]=digest(part);save(checkpoint,part);new+=1
        bars[item["symbol"]].extend(part["bars"]);count+=part["raw_rows"]
        save(out/"progress.json",{"phase":"features","completed_files":sum(len(v) for v in bars.values())//6,
             "expected_files":158,"new_files_this_process":new,"elapsed_seconds":time.monotonic()-began,"financial_result_ready":False})
        if time.monotonic()-began>budget and sum(len(v) for v in bars.values())<948:
            return False
    assert count==70815420 and all(len(bars[s])==474 for s in SYMBOLS)
    assert [b["timestamp"] for b in bars["BTCUSDT"]]==[b["timestamp"] for b in bars["ETHUSDT"]]
    result={"schema":"nexus.label-collapse-features.v1","inputs":inputs,"bars":bars,"raw_trade_rows":count,
            "all_raw_decimal_checked":True,"verified_bars":948,"protected_prices_read":False,"downloads":0}
    result["digest"]=digest(result);save(out/"features.json",result);return True

def signal(bars,i,flow):
    if i<2:return False
    e,t=bars[i-2],bars[i-1]
    return e["close"]<e["open"] and t["close"]>e["high"] and (
        not flow or (e["imbalance"]>=.20 and t["imbalance"]<=.05))

def run_book(bars,profile,flow):
    fee,slip=[x/10000 for x in PROFILES[profile]]
    cash=500.;pos=None;fills=[];marks=[];trades=[];fees=0.;peak=500.;dd=0.
    n=len(bars[SYMBOLS[0]])
    def sell(index,ref,reason,precision):
        nonlocal cash,pos,fees
        b=bars[pos["symbol"]][index];p=ref*(1-slip);value=pos["quantity"]*p;f=value*fee
        cash+=value-f;fees+=f
        fills.append({"bar_index":index,"symbol":pos["symbol"],"side":"sell","reason":reason,
          "reference_price":ref,"fill_price":p,"quantity":pos["quantity"],"fee":f,"cash_after":cash,
          "decision_time_ms":b["last_trade_ms"] if precision=="last_trade" else b["timestamp"],
          "execution_time_ms":b["first_trade_ms"] if precision=="first_trade" else b["last_trade_ms"] if precision=="last_trade" else None,
          "time_precision":precision})
        trades.append({"entry_index":pos["entry_index"],"exit_index":index,"symbol":pos["symbol"],
          "entry_price":pos["entry_price"],"exit_price":p,"quantity":pos["quantity"],
          "entry_fee":pos["entry_fee"],"exit_fee":f,
          "net_pnl_usdt":pos["quantity"]*(p-pos["entry_price"])-pos["entry_fee"]-f,
          "reason":reason})
        pos=None
    for i in range(n):
        held_at_open=pos is not None
        if held_at_open:
            b=bars[pos["symbol"]][i]
            if b["open"]<=pos["stop"]:sell(i,b["open"],"stop_gap","first_trade")
            elif b["open"]>=pos["target"]:sell(i,pos["target"],"target_gap","first_trade")
            elif i>=pos["entry_index"]+6:sell(i,b["open"],"time","first_trade")
        if not held_at_open and pos is None:
            for s in SYMBOLS:
                bb=bars[s];b=bb[i]
                if not signal(bb,i,flow):continue
                entry=b["open"]*(1+slip);stop=min(bb[i-2]["low"],bb[i-1]["low"])
                distance=(entry-stop)/entry
                if not .01<=distance<=.04:continue
                risk_unit=entry*(1+fee)-stop*(1-slip)*(1-fee)
                assert risk_unit>0
                q=min(250/entry,2.5/risk_unit,cash/(entry*(1+fee)))
                if q<=0:continue
                f=q*entry*fee;cash-=q*entry+f;fees+=f
                if abs(cash)<1e-10:cash=0.
                assert cash>=-1e-8
                pos={"symbol":s,"quantity":q,"entry_price":entry,"entry_fee":f,"entry_index":i,
                     "stop":stop,"target":entry+2*(entry-stop)}
                fills.append({"bar_index":i,"symbol":s,"side":"buy","reason":"entry",
                  "reference_price":b["open"],"fill_price":entry,"quantity":q,"fee":f,"cash_after":cash,
                  "decision_time_ms":b["timestamp"],"execution_time_ms":b["first_trade_ms"],"time_precision":"first_trade"})
                assert b["first_trade_ms"]>=bb[i-1]["timestamp"]+STEP
                break
        if pos is not None:
            b=bars[pos["symbol"]][i]
            if b["low"]<=pos["stop"]:sell(i,pos["stop"],"stop","4h_interval")
            elif b["high"]>=pos["target"]:sell(i,pos["target"],"target","4h_interval")
        if i==n-1 and pos is not None:sell(i,bars[pos["symbol"]][i]["close"],"terminal","last_trade")
        equity=cash+(pos["quantity"]*bars[pos["symbol"]][i]["close"] if pos else 0)
        peak=max(peak,equity);dd=max(dd,1-equity/peak)
        marks.append({"bar_index":i,"timestamp":bars[SYMBOLS[0]][i]["timestamp"]+STEP,
          "cash":cash,"quantity":pos["quantity"] if pos else 0,"symbol":pos["symbol"] if pos else None,"equity":equity})
    assert pos is None and math.isclose(sum(t["net_pnl_usdt"] for t in trades),cash-500,abs_tol=1e-7)
    return {"cash":cash,"net_pnl_usdt":cash-500,"fees_usdt":fees,"max_close_drawdown_fraction":dd,
       "closed_trades":len(trades),"fills":fills,"marks":marks,"trades":trades,
       "monthly_pnl_usdt":monthly(marks),"mean_net_pnl_per_closed_trade":(cash-500)/len(trades) if trades else None}

def monthly(marks):
    result={};prior=500.
    for m in marks:
        # A close exactly on month boundary belongs to the just-closed bar.
        key=datetime.fromtimestamp((m["timestamp"]-1)/1000,timezone.utc).strftime("%Y-%m")
        result[key]=m["equity"]
    for k,ending in list(result.items()):result[k]=ending-prior;prior=ending
    return result

def passive(bars,profile,key):
    fee,slip=[x/10000 for x in PROFILES[profile]];cash=500.;hold={};fees=0.;marks=[];peak=500.;dd=0.
    specs={key:500} if key in SYMBOLS else {"BTCUSDT":250,"ETHUSDT":250} if key=="full_50_50" else {"BTCUSDT":125,"ETHUSDT":125} if key=="capped_50_50" else {}
    for s,budget in specs.items():
        entry=bars[s][0]["open"]*(1+slip)
        q=budget/entry if key=="capped_50_50" else budget/(entry*(1+fee))
        cost=q*entry;f=cost*fee;cash-=cost+f;fees+=f;hold[s]=q
    if abs(cash)<1e-10:cash=0.
    n=len(bars[SYMBOLS[0]])
    for i in range(n):
        if i==n-1:
            for s,q in hold.items():
                value=q*bars[s][i]["close"]*(1-slip);f=value*fee;cash+=value-f;fees+=f
            hold={}
        equity=cash+sum(q*bars[s][i]["close"] for s,q in hold.items())
        peak=max(peak,equity);dd=max(dd,1-equity/peak)
        marks.append({"bar_index":i,"timestamp":bars[SYMBOLS[0]][i]["timestamp"]+STEP,"cash":cash,"equity":equity})
    return {"cash":cash,"net_pnl_usdt":cash-500,"fees_usdt":fees,"max_close_drawdown_fraction":dd,
      "marks":marks,"monthly_pnl_usdt":monthly(marks)}

def replay(contract_path,out):
    f=read(out/"features.json")
    assert f["digest"]==digest({k:v for k,v in f.items() if k!="digest"})
    assert f["inputs"]["contract_sha256"]==sha(contract_path) and f["inputs"]["producer_sha256"]==sha(__file__)
    assert f["all_raw_decimal_checked"] is True
    bars=f["bars"]
    assert all(len(bars[s])==474 for s in SYMBOLS)
    assert all(b["timestamp"]<1792368000000 for s in SYMBOLS for b in bars[s]) # Oct19 00:00Z
    books={name:{p:run_book(bars,p,flow) for p in PROFILES} for name,flow in (("candidate",True),("price_only",False))}
    bench={p:{k:passive(bars,p,k) for k in (*SYMBOLS,"full_50_50","capped_50_50","cash")} for p in PROFILES}
    a=books["candidate"];control=books["price_only"]["stress"];b=bench["stress"]["capped_50_50"]
    gates={"all_three_costs_positive":all(a[p]["net_pnl_usdt"]>0 for p in PROFILES),
      "stress_beats_no_flow":a["stress"]["net_pnl_usdt"]>control["net_pnl_usdt"],
      "stress_beats_capped_passive":a["stress"]["net_pnl_usdt"]>b["net_pnl_usdt"],
      "stress_dd_no_worse_capped_passive":a["stress"]["max_close_drawdown_fraction"]<=b["max_close_drawdown_fraction"]}
    result={"schema":"nexus.label-collapse-development-result.v1","inputs":f["inputs"],
      "features_digest":f["digest"],"books":books,"passive":bench,"decision_gates":gates,
      "exploratory_pass":all(gates.values()),"outcome":"exploratory_lead_only" if all(gates.values()) else "terminal_negative_no_retune",
      "inspection_classification":"already_inspected_development_not_OOS",
      "independent_financial_qa_ready":False,"paper_eligible":False,"live_enabled":False,"orders":0,"protected_prices_read":False}
    result["digest"]=digest(result);save(out/"result.json",result);return result

def fixture(n=10):
    start=int(datetime(2026,8,1,tzinfo=timezone.utc).timestamp()*1000)
    b=[]
    for i in range(n):
        row={"timestamp":start+i*STEP,"first_trade_ms":start+i*STEP+100,"last_trade_ms":start+(i+1)*STEP-100,
          "open":101.,"high":101.5,"low":100.5,"close":101.,"imbalance":0.}
        b.append(row)
    b[0].update(open=100.,high=100.5,low=99.,close=99.5,imbalance=.3)
    b[1].update(open=99.5,high=101.2,low=99.2,close=100.8,imbalance=0.)
    return {s:[dict(x) for x in b] for s in SYMBOLS}
class Checks(unittest.TestCase):
    def test_time_and_priority(self):
        r=run_book(fixture(),"conservative",True);self.assertEqual(r["trades"][0]["exit_index"],8)
        self.assertEqual(r["trades"][0]["reason"],"time");self.assertEqual(r["trades"][0]["symbol"],"BTCUSDT")
    def test_both_hit_and_inclusive_risk(self):
        b=fixture();b["BTCUSDT"][2].update(high=110.,low=98.)
        r=run_book(b,"severe",True);self.assertEqual(r["trades"][0]["reason"],"stop")
        self.assertLessEqual(-r["trades"][0]["net_pnl_usdt"],2.50000001)
    def test_gap_can_exceed_budget(self):
        b=fixture();b["BTCUSDT"][3].update(open=95.,high=96.,low=94.,close=95.)
        r=run_book(b,"stress",True);self.assertEqual(r["trades"][0]["reason"],"stop_gap")
        self.assertGreater(-r["trades"][0]["net_pnl_usdt"],2.5)
    def test_target_gap_no_improvement(self):
        b=fixture();b["BTCUSDT"][3].update(open=110.,high=112.,low=109.,close=111.)
        r=run_book(b,"conservative",True);self.assertEqual(r["trades"][0]["reason"],"target_gap")
        self.assertLess(r["fills"][1]["reference_price"],110.)
    def test_terminal(self):
        r=run_book(fixture(5),"conservative",True);self.assertEqual(r["trades"][0]["reason"],"terminal")
    def test_ablation_changes_only_flow(self):
        b=fixture()
        for s in SYMBOLS:b[s][0]["imbalance"]=.1
        self.assertEqual(run_book(b,"stress",True)["closed_trades"],0)
        self.assertEqual(run_book(b,"stress",False)["closed_trades"],1)
    def test_side_flip(self):
        for x,y in ((12.,3.),(1.,1.),(.01,2.)):
            self.assertEqual(abs(x-y)/(x+y),abs(y-x)/(y+x))
    def test_no_current_close_entry_leak(self):
        b=fixture();r1=run_book(b,"conservative",True)
        b["BTCUSDT"][2]["close"]=101.2;r2=run_book(b,"conservative",True)
        self.assertEqual(r1["fills"][0],r2["fills"][0])
    def test_distance_and_shared_cash(self):
        b=fixture()
        for s in SYMBOLS:b[s][2]["open"]=120.
        self.assertEqual(run_book(b,"severe",True)["closed_trades"],0)
        r=run_book(fixture(),"severe",True)
        self.assertTrue(all(x["cash"]>=-1e-8 for x in r["marks"]))
        self.assertLessEqual(r["fills"][0]["quantity"]*r["fills"][0]["fill_price"],250.0000001)

if __name__=="__main__":
    if not __debug__:raise RuntimeError("Assertions must be enabled.")
    p=argparse.ArgumentParser();p.add_argument("--phase",choices=["test","features","replay"],required=True)
    p.add_argument("--contract",type=Path);p.add_argument("--capture-root",type=Path);p.add_argument("--output",type=Path)
    p.add_argument("--budget-seconds",type=int,default=600);args=p.parse_args()
    if args.phase=="test":unittest.main(argv=["self-test"])
    elif args.phase=="features":
        done=build_features(args.contract,args.capture_root,args.output,args.budget_seconds)
        print(json.dumps({"features_complete":done}),flush=True)
    else:
        r=replay(args.contract,args.output)
        print(json.dumps({"outcome":r["outcome"],"decision_gates":r["decision_gates"],"net":{k:{p:v["net_pnl_usdt"] for p,v in x.items()} for k,x in r["books"].items()}}),flush=True)
