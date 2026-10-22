"""MR40 Phase 2: fixed-trade adverse/favorable excursion and initial-stop overlap.

Read-only audit of previously simulated positions and pinned four-hour OHLC.
Historical future paths are OUTCOMES, not permitted entry-time predictors.
No strategies are replayed, tuned, or promoted. No private exchange access.
"""
from __future__ import annotations
import argparse,collections,datetime as dt,gzip,hashlib,json,statistics
from pathlib import Path

FRAME_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
QUALITY_LEDGER_SHA="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
ENTRY_STOP_LEDGER_SHA="138beb278daf2d0f83f015e06b9be80eac406f590b28a0581d3341e8dc2f52e3"
STEP=14_400_000

def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def iso(t):return dt.datetime.fromtimestamp(t/1000,dt.timezone.utc).isoformat()
def median(v):return round(statistics.median(v),4) if v else None

def load_ledger(path,expected):
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError("ledger_changed")
    out={}
    with gzip.open(path,"rt",encoding="utf8") as fh:
        for line in fh:
            x=json.loads(line);key=x["key"]
            if key["venue"]=="Bybit" and key["capital"]==10000 and key["profile"]=="normal" and key["window"] in ("train","evaluation") and key["case"] in ("baseline","entry_stop_4"):
                out[(key["window"],key["case"])]=x
    return out

def main(inputs,quality_ledger,stop_ledger,dest):
    if dest.exists():raise ValueError("no_overwrite")
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    ext=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    rows=b["rows"]+ext["rows"]
    if hashlib.sha256(canon(rows)).hexdigest()!=FRAME_SHA:raise ValueError("market_changed")
    q=load_ledger(quality_ledger,QUALITY_LEDGER_SHA)
    s=load_ledger(stop_ledger,ENTRY_STOP_LEDGER_SHA)
    by_window={}
    for window in ("train","evaluation"):
        baseline=q[(window,"baseline")]["positions"]
        original=s[(window,"baseline")]["positions"]
        stopped=s[(window,"entry_stop_4")]["positions"]
        assert len(original)==len(stopped)==len(baseline)
        assert [a["entry"]["fill_ms"] for a in baseline]==[x["entry"]["fill_ms"] for x in original]
        assert [a["entry"]["fill_ms"] for a in baseline]==[x["entry"]["fill_ms"] for x in stopped]
        report=[]
        for base,with_stop in zip(baseline,stopped):
            buy=base["entry"];sell=base["exit"]
            idx=buy["bar_index"];end=sell["bar_index"]
            if sell["reason"]=="terminal_close":end+=1
            if not(idx<end<=len(rows)):raise ValueError("bad_holding_range")
            price=float(buy["price"]);barlist=rows[idx:end]
            assert rows[idx][0]==buy["fill_ms"]
            minlow=min(float(r[3]) for r in barlist)
            cl=[float(r[4]) for r in barlist]
            lowest_idx=min(range(idx,end),key=lambda k:float(rows[k][3]))
            first_4pct=next((k for k in range(idx,end) if float(rows[k][3])<=price*.96),None)
            first_close_2pct=next((k for k in range(idx,end) if float(rows[k][4])>=price*1.02),None)
            eligible_arm_bar=None if first_close_2pct is None else first_close_2pct+1
            if eligible_arm_bar is not None and eligible_arm_bar>=end:eligible_arm_bar=None
            first24=rows[idx:min(end,idx+6)]
            early_mae=100*(1-min(float(r[3]) for r in first24)/price)
            early_best=100*(max(float(r[2]) for r in first24)/price-1)
            p=base["net_pnl_usdt"]
            filtered_stop=with_stop["exit"]["reason"] in ("stop_hit","stop_gap")
            record={"entry_utc":iso(buy["fill_ms"]),"exit_utc":iso(sell["fill_ms"]),
                "baseline_pnl_usdt":round(p,4),"winner":p>0,
                "entry_price":price,"holding_bars":end-idx,
                "minimum_low_pct_from_entry":round(100*(minlow/price-1),4),
                "max_adverse_low_pct":round(100*(1-minlow/price),4),
                "largest_low_drawdown_utc":iso(rows[lowest_idx][0]),
                "first_day_max_adverse_low_pct":round(early_mae,4),
                "first_day_max_favorable_high_pct":round(early_best,4),
                "reached_minus4_low":first_4pct is not None,
                "minus4_first_utc":iso(rows[first_4pct][0]) if first_4pct is not None else None,
                "reached_plus2_closed":first_close_2pct is not None,
                "plus2_close_utc":iso(rows[first_close_2pct][0]+STEP) if first_close_2pct is not None else None,
                "usable_plus2_stop_start_utc":iso(rows[eligible_arm_bar][0]) if eligible_arm_bar is not None else None,
                "minus4_before_usable_plus2":first_4pct is not None and (eligible_arm_bar is None or first_4pct<eligible_arm_bar),
                "observed_entry4_stop_hit":filtered_stop,
                "entry4_position_pnl_usdt":round(with_stop["net_pnl_usdt"],4)}
            if filtered_stop and not record["reached_minus4_low"]:raise ValueError("recorded_stop_not_in_bar")
            report.append(record)
        groups={}
        for name,subset in (("all",report),("baseline_winners",[r for r in report if r["winner"]]),("baseline_losers",[r for r in report if not r["winner"]])):
            groups[name]={"positions":len(subset),
              "minus4_seen":sum(r["reached_minus4_low"] for r in subset),
              "minus4_before_plus2_arming":sum(r["minus4_before_usable_plus2"] for r in subset),
              "recorded_stop4_exits":sum(r["observed_entry4_stop_hit"] for r in subset),
              "plus2_reached_by_close":sum(r["reached_plus2_closed"] for r in subset),
              "plus2_usable_to_protect":sum(r["usable_plus2_stop_start_utc"] is not None for r in subset),
              "median_first_day_adverse_pct":median([r["first_day_max_adverse_low_pct"] for r in subset]),
              "median_full_holding_adverse_pct":median([r["max_adverse_low_pct"] for r in subset]),
              "baseline_pnl_sum":round(sum(r["baseline_pnl_usdt"] for r in subset),2)}
        by_window[window]={"groups":groups,"positions":report}
    o={"schema":"mr40.entry-vs-initial-stop.excursion-audit.v1",
       "evidence":{"market_rows_digest":FRAME_SHA,"quality_ledger_sha256":QUALITY_LEDGER_SHA,"entry_stop_ledger_sha256":ENTRY_STOP_LEDGER_SHA},
       "method":"Descriptive original held-position 4h OHLC extremes, 24h and full duration; fixed previously-studied -4% low and +2% close levels. Entry4 stop events borrowed from already-run ledger, no simulation.",
       "limitation":"Future outcome labels and intrabar Low/HIGH cannot be used as entry predictors; same-bar ordering unknown; noncausal paired portfolio amounts.",
       "windows":by_window}
    o["digest"]=hashlib.sha256(canon(o)).hexdigest()
    dest.write_bytes(canon(o)+b"\n")
    print(json.dumps({"digest":o["digest"],"windows":{w:t["groups"] for w,t in by_window.items()},
    "worst_evaluation":sorted(by_window["evaluation"]["positions"],key=lambda x:x["baseline_pnl_usdt"])[:4]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("inputs","quality_ledger","stop_ledger","dest"):p.add_argument("--"+name.replace("_","-"),required=True,type=Path)
    main(**vars(p.parse_args()))
