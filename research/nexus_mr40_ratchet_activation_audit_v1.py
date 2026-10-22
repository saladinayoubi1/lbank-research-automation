"""Read-only concentration and activation coverage audit for frozen MR40 trigger/ratchet.

Uses only previously hash-pinned market frames and recorded account fills.
Does not run a strategy simulation or change the Paper account.
"""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
from collections import defaultdict
from decimal import Decimal as D
from pathlib import Path

EXPECTED_FRAME = "a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
EXPECTED_LEDGER = "11d951fb67afbfaf39e6cf83d5f76a6d2c277a8f972f25e4f3266e41a14e63e8"
EXPECTED_RESULT_DIGEST = "56623e1509ccc3a88a1fba1bb47d1a87a699cf953d8a661b71e49db4e18cd5b3"
BAR_MS = 14400000

def canonical(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",",":"), allow_nan=False).encode()
def date(ms):
    return dt.datetime.fromtimestamp(ms/1000,dt.timezone.utc).isoformat()
def main(inputs, ledger, results, output):
    if output.exists():raise ValueError("no_overwrite")
    if hashlib.sha256(ledger.read_bytes()).hexdigest()!=EXPECTED_LEDGER:raise ValueError("ledger_hash")
    b=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())
    e=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())
    rows=b["rows"]+e["rows"]
    if hashlib.sha256(canonical(rows)).hexdigest()!=EXPECTED_FRAME:raise ValueError("frame_hash")
    report=json.loads(results.read_bytes())
    if report["digest"]!=EXPECTED_RESULT_DIGEST:raise ValueError("result_hash")
    observed={}
    with gzip.open(ledger,"rt",encoding="utf-8") as f:
        for line in f:
            obj=json.loads(line);k=obj["key"]
            if k["venue"]=="Bybit" and k["capital"]==10000 and k["window"] in ("train","evaluation","full") and k["profile"] in ("normal","stress"):
                observed[(k["window"],k["profile"],k["case"])]=obj
    # Position-level attribution is an arithmetic difference between two
    # differently compounded account paths, NOT equal-cash causal impact.
    comparisons=[]
    for window in ("train","evaluation","full"):
        for profile in ("normal","stress"):
            baseline=observed[(window,profile,"baseline")]["positions"]
            candidate=observed[(window,profile,"arm2_be")]["positions"]
            assert len(baseline)==len(candidate)
            records=[]
            for a,bp in zip(baseline,candidate):
                assert a["entry"]["fill_ms"]==bp["entry"]["fill_ms"]
                ap=D(str(a["net_pnl_usdt"])); bpnl=D(str(bp["net_pnl_usdt"]))
                records.append({"entry_utc":date(a["entry"]["fill_ms"]),
                    "baseline_pnl":float(ap),"ratchet_pnl":float(bpnl),
                    "delta_pnl":float(bpnl-ap),"stop":bool(bp["stopped"]),
                    "baseline_holding_h":a["holding_hours"],"ratchet_holding_h":bp["holding_hours"],
                    "original_entry_fill_ms":a["entry"]["fill_ms"]})
            normal_total=sum(z["delta_pnl"] for z in records)
            base_metric=next(z for z in report["rows"] if z["venue"]=="Bybit" and z["capital"]==10000 and z["window"]==window and z["profile"]==profile and z["case"]=="baseline")
            cand_metric=next(z for z in report["rows"] if z["venue"]=="Bybit" and z["capital"]==10000 and z["window"]==window and z["profile"]==profile and z["case"]=="arm2_be")
            official_delta=cand_metric["net_pnl_usdt"]-base_metric["net_pnl_usdt"]
            if abs(normal_total-official_delta)>0.000001:raise ValueError("delta_identity")
            top=sorted(records,key=lambda z:z["delta_pnl"],reverse=True)
            changed=[z for z in records if abs(z["delta_pnl"])>0.005]
            direct=[z for z in records if z["stop"]]
            comparisons.append({"window":window,"profile":profile,"positions":len(records),
                "official_pnl_delta":round(official_delta,6),
                "top_single_delta":round(top[0]["delta_pnl"],6),
                "top_single_pct_of_net_delta":round(100*top[0]["delta_pnl"]/official_delta,2) if official_delta else None,
                "largest_contributors":[{k:z[k] for k in ("entry_utc","baseline_pnl","ratchet_pnl","delta_pnl","stop")} for z in top[:7]],
                "stop_event_deltas_sum":round(sum(z["delta_pnl"] for z in direct),6),
                "other_trade_deltas_sum":round(sum(z["delta_pnl"] for z in records if not z["stop"]),6),
                "stop_count":len(direct),"changed_trade_count":len(changed),
                "stops":[{k:z[k] for k in ("entry_utc","delta_pnl","baseline_pnl","ratchet_pnl","baseline_holding_h","ratchet_holding_h")} for z in direct]})
    # Trace all baseline losing entries: maximum COMPLETED-CLOSE favourable move
    # following entry, before historical final exit. No HIGH, no future signal.
    close_coverage=[]
    for window in ("train","evaluation"):
        group=observed[(window,"normal","baseline")]["positions"]
        for pos in group:
            entry=pos["entry"];ex=pos["exit"]
            start_ms=entry["fill_ms"];end_ms=ex["fill_ms"]
            # First permissible future close is after the executed entry open.
            possible=[(r[0],D(str(r[4]))) for r in rows if
                start_ms<=r[0] and r[0]+BAR_MS<=end_ms]
            entryprice=D(str(entry["price"]))
            maxfavorable=max(((cl/entryprice)-1 for ts,cl in possible),default=D("-99"))
            first_arm=next((ts+BAR_MS for ts,cl in possible if cl>=entryprice*D("1.02")),None)
            close_coverage.append({
                "window":window,"entry_utc":date(start_ms),"exit_utc":date(end_ms),
                "baseline_pnl":round(float(pos["net_pnl_usdt"]),3),
                "max_completed_close_gain_pct":round(100*float(maxfavorable),3),
                "hit_arm2_close":first_arm is not None,
                "first_arm_close_utc":date(first_arm) if first_arm else None,
                "holding_h":pos["holding_hours"]
            })
    losses=[x for x in close_coverage if x["baseline_pnl"]<0]
    summary={}
    for w in ("train","evaluation"):
        arr=[x for x in losses if x["window"]==w]
        summary[w]={"losers":len(arr),"losers_without_2pct_closed_trigger":sum(not x["hit_arm2_close"] for x in arr),
             "loser_pnl_sum":round(sum(x["baseline_pnl"] for x in arr),3),
             "unarmed_loser_pnl_sum":round(sum(x["baseline_pnl"] for x in arr if not x["hit_arm2_close"]),3),
             "worst_unarmed":[x for x in sorted(arr,key=lambda z:z["baseline_pnl"]) if not x["hit_arm2_close"]][:5]}
    out={"schema":"mr40.trigger-ratchet-audit.v1",
      "protocol":"already-observed historical/accounting descriptive diagnostics only",
      "source_frame_sha256":EXPECTED_FRAME,"ledger_sha256":EXPECTED_LEDGER,
      "result_digest":EXPECTED_RESULT_DIGEST,
      "caveat":"Account paths are separately compounded; paired-trade dollar deltas include previous capital divergence and cannot prove equal-capital causal effect.",
      "comparisons":comparisons,"unarmed_loss_coverage":summary}
    out["digest"]=hashlib.sha256(canonical(out)).hexdigest()
    output.write_bytes(canonical(out)+b"\n")
    print(json.dumps({"digest":out["digest"],"comparisons":[{k:x[k] for k in ("window","profile","official_pnl_delta","top_single_delta","top_single_pct_of_net_delta","stop_count","stop_event_deltas_sum","other_trade_deltas_sum","changed_trade_count")} for x in comparisons],"unarmed_loss_coverage":summary},ensure_ascii=False),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("inputs","ledger","results","output"):p.add_argument("--"+n,required=True,type=Path)
    main(**vars(p.parse_args()))
