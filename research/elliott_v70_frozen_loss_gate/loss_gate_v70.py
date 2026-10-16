"""V70 historical Elliott legacy loss audit from actual source trace.

This is NOT prospective V52 evidence and never promotes a strategy.
Exact SHA-pinned V37 receipt, independent QA and physical original trace
must agree before per-partition costs and training-vs-validation are evaluated.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping

V37_SHA="96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024"
PROFILES=("conservative","stress")
PARTITIONS=("train","validation","historically_inspected_test")
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
AUTO_DEMO=False
LIVE_ENABLED=False
FILLED_DEMO_TRADES=0

def digest(path):
    h=sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"),parse_float=Decimal)

def dec(value):
    if isinstance(value,(bool,float)):raise ValueError("NON_EXACT_DECIMAL")
    try:d=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError) as exc:raise ValueError("BAD_DECIMAL") from exc
    if not d.is_finite():raise ValueError("NONFINITE_DECIMAL")
    return d

def summarize_by_partition(trace:Mapping,receipt:Mapping,qa:Mapping):
    if (receipt.get("schema")!="nexus.elliott-v37-legacy-frozen-loss-attribution.v1" or
        receipt.get("status")!="PASS_FROZEN_LEGACY_ECONOMICS_ATTRIBUTION" or
        receipt.get("historical_original_frozen") is not True or
        receipt.get("historically_inspected_not_pristine") is not True or
        receipt.get("not_demo_evidence") is not True or
        receipt.get("not_new_strategy") is not True or
        receipt.get("no_reoptimization") is not True):
        raise ValueError("LEGACY_RESEARCH_ONLY_RECEIPT_REQUIRED")
    if not isinstance(trace.get("rows"),list):raise ValueError("MISSING_SOURCE_TRACE")
    totals=defaultdict(list)
    bysymbol=defaultdict(list)
    paired=defaultdict(dict)
    for block in trace["rows"]:
        sym,part,profile=block["symbol"],block["part"],block["profile"]
        if sym not in ("BTCUSDT","ETHUSDT") or part not in PARTITIONS or profile not in PROFILES:
            raise ValueError("UNREGISTERED_SYMBOL_OR_PARTITION")
        for t in block["trades"]:
            key=(sym,part,t["trade_index"])
            if profile in paired[key]:raise ValueError("DUPLICATE_SCENARIO_TRADE")
            q=dec(t["quantity"]);at=dec(t["entry_reference"]);ex=dec(t["exit_reference"])
            net=dec(t["net_pnl"])
            fees=dec(t["entry_fee"])+dec(t["exit_fee"])
            gross=(ex-at)*q
            friction=gross-net
            if q<=0 or at<=0 or ex<=0 or fees<0 or friction<0:
                raise ValueError("INVALID_SOURCE_ECONOMICS")
            record=dict(net=net,friction=friction,fees=fees,
                        exit_reason=t["exit_reason"])
            totals[(part,profile)].append(record)
            bysymbol[(sym,profile)].append(record)
            paired[key][profile]=record
    if not paired or any(set(x)!=set(PROFILES) for x in paired.values()):
        raise ValueError("MISSING_PAIRED_COST_SCENARIO")
    if any(pair["conservative"]["exit_reason"]!=pair["stress"]["exit_reason"]
           for pair in paired.values()):
        raise ValueError("SCENARIO_EXIT_REASONS_DIVERGED")
    def metric(rows):
        return dict(trades=len(rows),
                    wins=sum(r["net"]>0 for r in rows),
                    losses=sum(r["net"]<0 for r in rows),
                    net=sum((r["net"] for r in rows),Decimal(0)),
                    friction=sum((r["friction"] for r in rows),Decimal(0)),
                    fees=sum((r["fees"] for r in rows),Decimal(0)))
    def compare(source,expected):
        got=metric(source)
        tolerance=Decimal("0.00000001")  # Decimal context/order rounding, not strategy slack
        if (got["trades"]!=expected["trades"] or
            got["wins"]!=expected["wins"] or
            got["losses"]!=expected["losses"] or
            abs(got["net"]-dec(expected["net_pnl_usdt"]))>tolerance or
            abs(got["friction"]-dec(expected["modeled_reference_friction_usdt"]))>tolerance or
            abs(got["fees"]-dec(expected["explicit_fees_usdt"]))>tolerance):
            raise ValueError("ORIGINAL_TRADE_TRACE_DOES_NOT_MATCH_V37_SUMMARY")
        return got
    bypart={}
    for (part,profile),rows in totals.items():
        name=part+"|"+profile
        bypart[name]=compare(rows,receipt["per_partition_profile"][name])
    if set(bypart)!={p+"|"+s for p in PARTITIONS for s in PROFILES}:
        raise ValueError("PARTITION_DATA_MISSING")
    for key,rows in bysymbol.items():
        compare(rows,receipt["per_symbol_profile"]["|".join(key)])
    total={}
    for profile in PROFILES:
        allrows=[rec for (part,p),rows in totals.items() if p==profile for rec in rows]
        total[profile]=compare(allrows,receipt[profile+"_total"])
    for profile in PROFILES:
        vals=[x for x in qa["groups"] if x["profile"]==profile]
        for qarec in vals:
            key=(qarec["symbol"],profile)
            got=metric(bysymbol[key])
            if (got["trades"]!=qarec["closed_trades"] or
                abs(got["net"]-dec(qarec["partition_sum_usdt"]))>dec("0.000001")):
                raise ValueError("INDEPENDENT_DECIMAL_QA_DISAGREES")
    return bypart,total,len(paired)

def assess_legacy_economics(bypart,total,paired_trades):
    """Fail-closed: a profitable train row cannot overrule negative validation."""
    train=bypart["train|conservative"]["net"]
    validation=bypart["validation|conservative"]["net"]
    inspected=bypart["historically_inspected_test|conservative"]["net"]
    if validation<0 or inspected<0:
        status="REJECT_PROMOTION_OUT_OF_SAMPLE_HISTORICAL_LOSSES"
    elif any(total[s]["net"]<=0 for s in PROFILES):
        status="REJECT_PROMOTION_AFTER_MODELED_COSTS"
    else:
        status="REQUIRES_UNSEEN_PROSPECTIVE_VALIDATION_NOT_ELIGIBLE"
    return dict(status=status,train_net=train,validation_net=validation,
                inspected_net=inspected,paired_trades=paired_trades,
                conservative_net=total["conservative"]["net"],
                stress_net=total["stress"]["net"],
                additional_stress_drag=total["conservative"]["net"]-total["stress"]["net"],
                conservative_friction=total["conservative"]["friction"],
                stress_friction=total["stress"]["friction"])

def audit_files(trace_path,result_path,qa_path,receipt_path):
    if digest(receipt_path)!=V37_SHA:raise ValueError("IMMUTABLE_V37_REPORT_HASH_MISMATCH")
    receipt=load(receipt_path)
    original=receipt["source_sha256"]
    if (digest(trace_path)!=original["trace"] or
        digest(result_path)!=original["result"]):
        raise ValueError("ORIGINAL_TRACE_OR_RESULT_HASH_MISMATCH")
    qa=load(qa_path)
    if (qa.get("trace_sha256")!=original["trace"] or
        qa.get("result_sha256")!=original["result"]):
        raise ValueError("INDEPENDENT_QA_SOURCE_LINEAGE_MISMATCH")
    bypart,total,paired=summarize_by_partition(load(trace_path),receipt,qa)
    result=assess_legacy_economics(bypart,total,paired)
    output={k:(str(v) if isinstance(v,Decimal) else v)
            for k,v in result.items()}
    output.update({
        "schema":"nexus.elliott-v70-frozen-legacy-economic-promotion-veto.v1",
        "source_receipt_sha256":digest(receipt_path),
        "historically_inspected":True,"prospective_v52":False,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"filled_demo_trades":0,"new_pnl":None})
    return output

def main():
    p=argparse.ArgumentParser()
    for key in ("trace","result","qa","receipt","output"):
        p.add_argument("--"+key,required=True)
    arg=p.parse_args()
    dst=Path(arg.output)
    if dst.exists():raise RuntimeError("IMMUTABLE_AUDIT_ALREADY_EXISTS")
    report=audit_files(arg.trace,arg.result,arg.qa,arg.receipt)
    dst.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps(dict(status=report["status"],
       trades=report["paired_trades"],train=report["train_net"],
       validation=report["validation_net"],inspected_test=report["inspected_net"],
       conservative=report["conservative_net"],stress=report["stress_net"],
       report_sha256=digest(dst)),ensure_ascii=False))
if __name__=="__main__":main()
