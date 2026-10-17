"""V76 frozen Elliott legacy trading-funnel and cost attribution.

Recalculates all 24 original distinct candidate price events and all ten
paired simulated fills directly from unchanged SHA-pinned source trace.
Avoids optimizer suggestions: historical events were already inspected.
No Demo/Paper eligibility, no orders, no new market performance inference.
"""
from __future__ import annotations
import argparse,json
from collections import Counter,defaultdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

V37_RECEIPT_SHA="96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024"
PARTS=("train","validation","historically_inspected_test")
MARKETS=("BTCUSDT","ETHUSDT")
PROFILES=("conservative","stress")
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
NEW_PNL=None
TOLERANCE=Decimal("0.00000001")

def hashfile(p):
    h=sha256()
    with Path(p).open("rb") as f:
        for x in iter(lambda:f.read(1048576),b""):h.update(x)
    return h.hexdigest()

def read(p):
    return json.loads(Path(p).read_text(encoding="utf8"),parse_float=Decimal)

def D(x):
    if isinstance(x,bool):raise ValueError("BOOLEAN_ECONOMICS")
    n=Decimal(str(x))
    if not n.is_finite():raise ValueError("NONFINITE_ECONOMICS")
    return n

def trade_economics(t):
    qty=D(t["quantity"]);before=D(t["entry_reference"]);after=D(t["exit_reference"])
    executed_entry=D(t["entry_slipped"]);executed_exit=D(t["exit_slipped"])
    fees=D(t["entry_fee"])+D(t["exit_fee"])
    if qty<=0 or min(before,after,executed_entry,executed_exit)<=0 or fees<0:
        raise ValueError("NEGATIVE_OR_INVALID_TRADE_INPUT")
    gross=(after-before)*qty
    slipped=(executed_exit-executed_entry)*qty
    adverse_slippage=gross-slipped
    if adverse_slippage < -TOLERANCE:
        raise ValueError("FAVORABLE_SLIPPAGE_NOT_MODELED_IN_FROZEN_TRACE")
    net=slipped-fees
    if abs(net-D(t["net_pnl"]))>TOLERANCE:
        raise ValueError("TRADE_NET_NOT_REPRODUCED")
    return dict(
        gross=gross,slipped=slipped,slippage=adverse_slippage,
        fees=fees,net=net,reason=t["exit_reason"])

def aggregate(rows):
    acc=dict(trades=len(rows),wins=sum(x["net"]>0 for x in rows),
             losses=sum(x["net"]<0 for x in rows))
    for k in ("gross","slipped","slippage","fees","net"):
        acc[k]=sum((x[k] for x in rows),Decimal(0))
    if abs(acc["gross"]-acc["slippage"]-acc["fees"]-acc["net"])>TOLERANCE:
        raise ValueError("AGGREGATE_COST_DECOMPOSITION_INCONSISTENT")
    w=[x["net"] for x in rows if x["net"]>0]
    l=[x["net"] for x in rows if x["net"]<0]
    avg_win=sum(w,Decimal(0))/len(w) if w else None
    avg_loss_abs=-sum(l,Decimal(0))/len(l) if l else None
    breakeven_fraction=(avg_loss_abs/(avg_loss_abs+avg_win)
                        if avg_win is not None and avg_loss_abs is not None else None)
    acc["mean_win"]=avg_win
    acc["mean_loss_abs"]=avg_loss_abs
    acc["empirical_breakeven_win_fraction"]=breakeven_fraction
    acc["observed_win_fraction"]=(Decimal(len(w))/len(rows) if rows else None)
    acc["exit_counts"]=dict(Counter(x["reason"] for x in rows))
    return acc

def event_funnel(reference_rows):
    outcome=Counter();failures=Counter();bycell={}
    for row in reference_rows:
        key=(row["symbol"],row["part"])
        if key in bycell:raise ValueError("DUPLICATE_PARTITION_CELL")
        events=row["price_events"]
        attempts=row["entry_attempts"]
        trades=row["trades"]
        marks={}
        denials=Counter()
        for event in events:
            disposition=event["admission"]
            if disposition not in ("scheduled_next_open","signal_denied"):
                raise ValueError("UNKNOWN_SIGNAL_DISPOSITION")
            stamp=(int(event["bar_index"]),event["decision_at"])
            if stamp in marks:raise ValueError("DUPLICATE_EVENT_DECISION")
            reason=tuple(sorted(event.get("denial_fields") or ()))
            if disposition=="scheduled_next_open" and reason:
                raise ValueError("SCHEDULED_EVENT_WITH_DENIAL")
            if disposition=="signal_denied" and not reason:
                raise ValueError("DENIAL_HAS_NO_REASON")
            marks[stamp]=(disposition,reason)
            outcome[disposition]+=1
            if disposition=="signal_denied":
                denials.update(reason);failures.update(reason)
        scheduled={s for s,(disposition,_) in marks.items()
                   if disposition=="scheduled_next_open"}
        attempted={(int(a["decision"]["bar_index"]),a["decision"]["decision_at"])
                    for a in attempts}
        if (scheduled!=attempted or len(attempts)!=len(scheduled) or
            len(trades)!=len(scheduled) or
            any(a.get("disposition")!="filled" for a in attempts)):
            raise ValueError("EVENT_SCHEDULED_ATTEMPT_FILL_MISMATCH")
        bycell["|".join(key)]=dict(
            price_events=len(events),scheduled=len(scheduled),
            denied=len(events)-len(scheduled),denial_field_hits=dict(denials))
    if outcome["scheduled_next_open"]!=10 or outcome["signal_denied"]!=14:
        raise ValueError("LEGACY_EVENT_FUNNEL_CHANGED")
    if len(bycell)!=len(MARKETS)*len(PARTS):
        raise ValueError("PARTITION_CELLS_MISSING")
    return {"price_events":sum(outcome.values()),
            "scheduled":outcome["scheduled_next_open"],
            "denied":outcome["signal_denied"],
            "denial_field_hits":dict(failures),
            "denial_reasons_not_mutually_exclusive":True,
            "bycell":bycell}

def audit(trace_path,result_path,v37_path):
    if hashfile(v37_path)!=V37_RECEIPT_SHA:
        raise ValueError("FROZEN_LEGACY_REPORT_SHA_CHANGED")
    v37=read(v37_path)
    if hashfile(trace_path)!=v37["source_sha256"]["trace"] or hashfile(result_path)!=v37["source_sha256"]["result"]:
        raise ValueError("FROZEN_LEGACY_ORIGINAL_BYTES_CHANGED")
    trace=read(trace_path)
    if trace.get("live_enabled") is not False or v37["not_demo_evidence"] is not True:
        raise ValueError("NOT_FROZEN_RESEARCH_ONLY")
    rows=trace["rows"]
    indexed={(r["symbol"],r["part"],r["profile"]):r for r in rows}
    if len(rows)!=12 or len(indexed)!=12 or set(indexed)!={(s,p,f) for s in MARKETS for p in PARTS for f in PROFILES}:
        raise ValueError("FROZEN_12_SCENARIO_CELLS_MISSING")
    for s in MARKETS:
        for p in PARTS:
            base=indexed[s,p,"conservative"]
            stress=indexed[s,p,"stress"]
            ref=[(int(e["bar_index"]),e["decision_at"],e["admission"],
                  tuple(sorted(e.get("denial_fields") or ()))) for e in base["price_events"]]
            test=[(int(e["bar_index"]),e["decision_at"],e["admission"],
                   tuple(sorted(e.get("denial_fields") or ()))) for e in stress["price_events"]]
            if ref!=test:raise ValueError("COST_SCENARIO_CHANGED_FROZEN_PRICE_EVENTS")
            if [(x["decision"]["decision_at"],x["disposition"]) for x in base["entry_attempts"]]!=[
                  (x["decision"]["decision_at"],x["disposition"]) for x in stress["entry_attempts"]]:
                raise ValueError("COST_SCENARIO_CHANGED_ENTRY_ADMISSION")
    reference=[indexed[s,p,"conservative"] for s in MARKETS for p in PARTS]
    funnel=event_funnel(reference)
    perprofile={};perpartition={};pairing={}
    for profile in PROFILES:
        records=[]
        for sym in MARKETS:
            for part in PARTS:
                row=indexed[sym,part,profile]
                econ=[trade_economics(t) for t in row["trades"]]
                records.extend(econ)
                for t,calc in zip(row["trades"],econ):
                    key=(sym,part,int(t["trade_index"]))
                    if profile in pairing.setdefault(key,{}):
                        raise ValueError("DUPLICATE_COST_PROFILE_TRADE")
                    pairing[key][profile]=(t["exit_reason"],calc["net"])
                perpartition.setdefault(part,{})[profile]=perpartition.get(part,{}).get(profile,[])+econ
        combined=aggregate(records)
        expected=v37[profile+"_total"]
        if (len(records)!=10 or
            abs(combined["net"]-D(expected["net_pnl_usdt"]))>TOLERANCE or
            abs((combined["slippage"]+combined["fees"])-D(expected["modeled_reference_friction_usdt"]))>TOLERANCE):
            raise ValueError("COST_TOTAL_DISAGREES_WITH_INDEPENDENT_V37")
        perprofile[profile]=combined
    if len(pairing)!=10 or any(set(x)!=set(PROFILES) or
        x["conservative"][0]!=x["stress"][0] for x in pairing.values()):
        raise ValueError("UNPAIRED_EXITS_OR_COST_SCENARIOS")
    partitions={part:{profile:aggregate(rows)
                for profile,rows in profile_map.items()}
                for part,profile_map in perpartition.items()}
    for part,profile_map in partitions.items():
        for profile,g in profile_map.items():
            expected=v37["per_partition_profile"][part+"|"+profile]
            if abs(g["net"]-D(expected["net_pnl_usdt"]))>TOLERANCE or g["trades"]!=expected["trades"]:
                raise ValueError("COST_PARTITION_DIFFERS_FROM_V37")
    if perprofile["conservative"]["net"]>=0 or partitions["validation"]["conservative"]["net"]>=0:
        raise ValueError("WRONG_OLD_FAILURE_CLASSIFICATION")
    def encode(v):
        if isinstance(v,Decimal):return str(v)
        if isinstance(v,dict):return {k:encode(value) for k,value in v.items()}
        if isinstance(v,(list,tuple)):return [encode(x) for x in v]
        return v
    return encode({
        "schema":"nexus.elliott-v76-original-economics-causal-funnel-attribution.v1",
        "frozen_trace_sha256":hashfile(trace_path),
        "original_result_sha256":hashfile(result_path),
        "v37_receipt_sha256":hashfile(v37_path),
        "historically_inspected":True,
        "source_event_funnel":funnel,
        "distinct_historical_simulated_trades":len(pairing),
        "by_profile":perprofile,"by_partition":partitions,
        "no_promotion_reason":"VALIDATION_AND_TEST_NEGATIVE_LEGACY_EXPECTANCY",
        "not_source_bound_v52_future_score":True,
        "sample_too_small_for_strategy_profitability_claim":True,
        "not_independent_real_fill_evidence":True,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "new_pnl":None})

def main():
    ap=argparse.ArgumentParser()
    for name in ("trace","result","v37","output"):ap.add_argument("--"+name,required=True)
    a=ap.parse_args();f=Path(a.output)
    if f.exists():raise RuntimeError("REFUSE_TO_OVERWRITE_IMMUTABLE_AUDIT")
    obj=audit(a.trace,a.result,a.v37)
    f.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    c=obj["by_profile"]["conservative"]
    print(json.dumps({"state":obj["no_promotion_reason"],
        "events":obj["source_event_funnel"]["price_events"],
        "admitted":obj["source_event_funnel"]["scheduled"],
        "denied":obj["source_event_funnel"]["denied"],
        "reference_gross":c["gross"],"net":c["net"],
        "slippage":c["slippage"],"fees":c["fees"],
        "output_sha256":hashfile(f)},ensure_ascii=False))
if __name__=="__main__":main()
