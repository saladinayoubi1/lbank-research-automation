"""MR40 stopped-position capital-normalized audit using immutable saved fills only.

Every trade's return is normalized by its OWN account's cash-before-entry.
Summed log-return differences explain compounded terminal wealth precisely.
Excluding an event from the SUM of recorded log-return differences is purely an
accounting decomposition, not a counterfactual backtest or leave-one-out refit.
"""
from __future__ import annotations
import argparse
import datetime as dt
import gzip
import hashlib
import json
import math
from decimal import Decimal as D
from pathlib import Path

LEDGER_SHA="11d951fb67afbfaf39e6cf83d5f76a6d2c277a8f972f25e4f3266e41a14e63e8"
RESULT_DIGEST="56623e1509ccc3a88a1fba1bb47d1a87a699cf953d8a661b71e49db4e18cd5b3"
FOCUS="2024-08-01T04:00:00+00:00"

def canon(v):
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def iso(ms):
    return dt.datetime.fromtimestamp(ms/1000,tz=dt.timezone.utc).isoformat()
def audit(ledger,results,output):
    if output.exists():raise ValueError("no_overwrite")
    assert hashlib.sha256(ledger.read_bytes()).hexdigest()==LEDGER_SHA
    with gzip.open(results,"rt",encoding="utf-8") as file:
        report=json.load(file)
    assert report["digest"]==RESULT_DIGEST
    assert report["runs"]==144 and report["paper_changed"] is False
    pairs={}
    with gzip.open(ledger,"rt",encoding="utf-8") as f:
        for line in f:
            a=json.loads(line);k=a["key"]
            if (k["venue"]=="Bybit" and k["capital"]==10000 and
                k["window"] in ("train","evaluation","full") and
                k["profile"] in ("normal","stress") and
                k["case"] in ("baseline","arm2_be")):
                pairs[(k["window"],k["profile"],k["case"])]=a
    reports=[]
    for w in ("train","evaluation","full"):
        for profile in ("normal","stress"):
            base=pairs[(w,profile,"baseline")]["positions"]
            alternative=pairs[(w,profile,"arm2_be")]["positions"]
            assert len(base)==len(alternative)
            entries=[]
            for b,a in zip(base,alternative):
                be=b["entry"];ae=a["entry"]
                assert be["fill_ms"]==ae["fill_ms"]
                bs=D(be["cash_before"]);bf=D(b["exit"]["cash_after"])
                cs=D(ae["cash_before"]);cf=D(a["exit"]["cash_after"])
                assert bs>0 and bf>0 and cs>0 and cf>0
                assert abs(float(bf-bs)-b["net_pnl_usdt"])<0.000001
                assert abs(float(cf-cs)-a["net_pnl_usdt"])<0.000001
                rb=float(bf/bs-1);rc=float(cf/cs-1)
                logdiff=math.log1p(rc)-math.log1p(rb)
                entries.append({"entry_utc":iso(be["fill_ms"]),"stopped":bool(a["stopped"]),
                    "baseline_return_pct":100*rb,"candidate_return_pct":100*rc,
                    "difference_percentage_points":100*(rc-rb),
                    "log_wealth_difference":logdiff})
            total=sum(x["log_wealth_difference"] for x in entries)
            def terminal(ps):
                return float(D(ps[-1]["exit"]["cash_after"])/D(ps[0]["entry"]["cash_before"]))
            exact_ratio=terminal(alternative)/terminal(base)
            if abs(math.exp(total)-exact_ratio)>0.00000000001:
                raise ValueError("not_exact_compounded_decomposition")
            selected=next((x for x in entries if x["entry_utc"]==FOCUS),None)
            exc=None
            if selected:
                exc=math.expm1(total-selected["log_wealth_difference"])*100
            reports.append({"window":w,"profile":profile,"positions":len(entries),
                "relative_terminal_wealth_gain_pct":100*(exact_ratio-1),
                "total_log_wealth_advantage":total,
                "focus_event":selected,
                "focus_log_contribution_pct":100*selected["log_wealth_difference"]/total if selected and total else None,
                "rest_of_recorded_trades_relative_wealth_pct":exc,
                "stop_event_normalized_log_sum":sum(x["log_wealth_difference"] for x in entries if x["stopped"]),
                "other_normalized_log_sum":sum(x["log_wealth_difference"] for x in entries if not x["stopped"]),
                "worst_normalized_differences":sorted(entries,key=lambda x:x["log_wealth_difference"])[:3]})
    result={"schema":"mr40.trigger-ratchet.equal-cash-normalized-accounting.v1",
            "source_ledger_sha256":LEDGER_SHA,
            "canonical_result_digest":RESULT_DIGEST,
            "caveat":"Subtracting an event from recorded log-return contributions is NOT a rerun with that event absent, does not adjust future decisions/capital and is not an out-of-sample test.",
            "windows":reports}
    result["digest"]=hashlib.sha256(canon(result)).hexdigest()
    output.write_bytes(canon(result)+b"\n")
    print(json.dumps({"digest":result["digest"],"comparisons":[{
        "window":a["window"],"profile":a["profile"],
        "terminal_relative_wealth_gain_pct":round(a["relative_terminal_wealth_gain_pct"],4),
        "focus_event_log_contribution_pct":round(a["focus_log_contribution_pct"],2) if a["focus_log_contribution_pct"] is not None else None,
        "remaining_recorded_trades_relative_wealth_pct":round(a["rest_of_recorded_trades_relative_wealth_pct"],4) if a["rest_of_recorded_trades_relative_wealth_pct"] is not None else None,
        "normalized_focus_diff_percentage_points":round(a["focus_event"]["difference_percentage_points"],4) if a["focus_event"] else None,
        "stop_count":sum(bool(x["stopped"]) for x in pairs[(a["window"],a["profile"],"arm2_be")]["positions"])
        } for a in reports]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for key in ("ledger","results","output"):p.add_argument("--"+key,required=True,type=Path)
    a=p.parse_args();audit(a.ledger,a.results,a.output)
