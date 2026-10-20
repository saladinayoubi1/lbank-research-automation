"""Descriptive calendar/entry-context attribution of an immutable MR40 ledger."""
from __future__ import annotations
import argparse,hashlib,json,math,statistics
from datetime import datetime,timezone
from pathlib import Path
INPUT="fba66860376d9ad24af7a2388e878db0dfdbae16468de9381ef6a95f95563ffe"
BASE="44ea00e4528ccbe3e420bd999152a36b58450565f8a45bb9489a3c79fe4b4514"
STEP=14_400_000
LOOKBACK=180
def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def digest(value):return hashlib.sha256(canonical(value)).hexdigest()
def iso(ms):return datetime.fromtimestamp(ms/1000,timezone.utc).isoformat()
def verify(value,key,expected):
    if value[key]!=expected or digest({k:v for k,v in value.items() if k!=key})!=expected:raise ValueError("substituted "+key)
def calendar(months,kind):
    groups={}
    for row in months:
        year,month=map(int,row["month"].split("-"))
        key=str(year) if kind=="year" else f"{year}-H{1 if month<=6 else 2}"
        groups.setdefault(key,[]).append(row)
    out=[]
    for name,parts in sorted(groups.items()):
        pnl=math.fsum(x["pnl_usdt"] for x in parts)
        assert abs(pnl-(parts[-1]["end_equity"]-parts[0]["start_equity"]))<1e-7
        out.append({"period":name,"months":len(parts),"start_equity_usdt":parts[0]["start_equity"],
                    "end_equity_usdt":parts[-1]["end_equity"],"net_pnl_usdt":pnl,
                    "return_pct":100*(parts[-1]["end_equity"]/parts[0]["start_equity"]-1),
                    "positive_months":sum(x["pnl_usdt"]>0 for x in parts)})
    return out
def context(rows,trade):
    i=trade["entry_index"];j=i-1
    assert rows[i][0]==trade["entry_ms"] and j>=LOOKBACK
    assert rows[j][0]+STEP<=trade["entry_ms"]
    current=float(rows[j][4]);earlier=float(rows[j-LOOKBACK][4])
    ret=100*(current/earlier-1)
    return {"entry_utc":iso(trade["entry_ms"]),"last_feature_close_utc":iso(rows[j][0]+STEP),
            "lookback_start_close_utc":iso(rows[j-LOOKBACK][0]+STEP),
            "last_closed_price":current,"lookback_closed_price":earlier,
            "btc_previous_30d_return_pct":ret,"regime":"nonnegative_30d" if ret>=0 else "negative_30d"}
def summarize(trades):
    wins=sum(x["net_pnl_usdt"]>0 for x in trades)
    return {"positions":len(trades),"wins":wins,"losses":sum(x["net_pnl_usdt"]<0 for x in trades),
            "win_rate_pct":100*wins/len(trades) if trades else None,
            "sum_actual_position_pnl_usdt":math.fsum(x["net_pnl_usdt"] for x in trades),
            "mean_actual_position_pnl_usdt":statistics.mean(x["net_pnl_usdt"] for x in trades) if trades else None,
            "mean_position_return_pct":statistics.mean(x["return_pct"] for x in trades) if trades else None,
            "median_holding_hours":statistics.median(x["holding_hours"] for x in trades) if trades else None,
            "held_over_160h":sum(x["holding_hours"]>160 for x in trades)}
def run(root,output):
    inputs=json.loads((root/"prepared_inputs.json").read_text(encoding="utf-8"));verify(inputs,"input_digest",INPUT)
    source=root/"verified_results"/"results.json"
    if not source.exists():source=root/"recorded_results"/"results.json"
    baseline=json.loads(source.read_text(encoding="utf-8"));verify(baseline,"result_digest",BASE)
    rows=inputs["rows"]
    assert len(rows)==8400 and all(rows[i][0]-rows[i-1][0]==STEP for i in range(1,len(rows)))
    profiles=[];first_entries=None
    for result in baseline["results"]:
        if result["cohort"]!="retrospective_42_months":continue
        trades=[{**t,**context(rows,t)} for t in result["positions"]]
        entries=[t["entry_ms"] for t in trades]
        if result["execution_lag_bars"]==1:
            if first_entries is None:first_entries=entries
            assert entries==first_entries
        groups=[{"regime":label,**summarize([t for t in trades if t["regime"]==label])}
                for label in ("nonnegative_30d","negative_30d")]
        assert sum(x["positions"] for x in groups)==len(trades)==81
        assert abs(math.fsum(x["sum_actual_position_pnl_usdt"] for x in groups)-result["net_pnl_usdt"])<1e-7
        years=calendar(result["monthly_attribution"],"year");halves=calendar(result["monthly_attribution"],"half")
        assert sum(x["months"] for x in years)==sum(x["months"] for x in halves)==42
        assert abs(math.fsum(x["net_pnl_usdt"] for x in years)-result["net_pnl_usdt"])<1e-7
        profiles.append({"profile":result["profile"],"yearly":years,"half_yearly":halves,"entry_context_groups":groups,"positions":trades})
    assert len(profiles)==4
    report={"schema":"nexus.mr40-descriptive-attribution.v1","baseline_result_digest":BASE,"input_digest":INPUT,
            "classification":"ALREADY_SEEN_DESCRIPTIVE_ATTRIBUTION_NOT_A_FILTER_BACKTEST",
            "fixed_context_rule":"sign of BTC 30-day close return known at entry; 180 four-hour intervals ending at the last fully closed bar",
            "new_strategy_simulations":0,"parameter_search":False,"orders":0,"live_enabled":False,
            "calendar_basis":"continuous original account; monthly mark-to-market attribution, not independent yearly deposits",
            "subset_pnl_basis":"sum of original realized position PnL at original compounded entry cash; not a separately traded strategy",
            "source_script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"profiles":profiles}
    report["result_digest"]=digest(report)
    if output.exists():raise ValueError("refuse overwrite")
    output.write_text(json.dumps(report,ensure_ascii=False,separators=(",",":"))+"\n",encoding="utf-8",newline="\n")
    print(json.dumps({"digest":report["result_digest"],"profiles":4,"trades_each":81,"normal":{k:v for k,v in profiles[0].items() if k!="positions"}}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--base-root",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args();run(a.base_root,a.output)
