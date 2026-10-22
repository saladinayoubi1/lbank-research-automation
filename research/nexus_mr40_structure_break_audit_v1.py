"""One locked retrospective MR40 30-bar structure-break diagnostic.

Never used as a live entry filter. The label is separated from ex-ante
feature construction; tests and output cannot turn this into an order.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from decimal import Decimal as D
from math import comb
from pathlib import Path

OHLC_SHA = "a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LEDGER_SHA = "2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
LOOKBACK = 30
WINDOWS = {"train":(19,6),"evaluation":(18,4)}


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def sha_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for blk in iter(lambda:f.read(1024*1024),b""):
            h.update(blk)
    return h.hexdigest()


def new_low_break(rows,signal_index):
    """Signal-bar close below previous 30 completed 4h bars' LOW, strict <.

    Critically does not read any values later than signal_index. Caller must
    ensure the signal candle itself has been fully confirmed closed.
    """
    j=signal_index
    if not isinstance(j,int) or j<LOOKBACK:
        raise ValueError("insufficient_prior_closed_bars")
    low=min(D(str(rows[k][3])) for k in range(j-LOOKBACK,j))
    close=D(str(rows[j][4]))
    if not all(x.is_finite() and x>0 for x in (low,close)):
        raise ValueError("bad_market_values")
    return close<low


def fisher_loss_enrichment(winner_flagged,loser_flagged,total_winners,total_losers):
    """One-sided exact hypergeometric p (exploratory, no causal inference)."""
    n=winner_flagged+loser_flagged
    N=total_winners+total_losers
    if n<0 or n>N or n==0:return 1.0
    p=0
    for loser_hits in range(loser_flagged,min(total_losers,n)+1):
        wins=n-loser_hits
        if 0<=wins<=total_winners:
            p+=comb(total_losers,loser_hits)*comb(total_winners,wins)
    return p/comb(N,n)


def run(inputs,ledger,protocol,output):
    if output.exists(): raise ValueError("refuse_overwrite")
    p=json.loads(protocol.read_bytes())
    if (p["schema"]!="nexus.mr40.pre_entry_structure_break_audit.v1"
        or p["feature_definition"]["lookback_bars"]!=LOOKBACK
        or p["feature_definition"]["name"]!="prior_30_low_break"
        or p["safety"]["promote"] is not False):
        raise ValueError("protocol_changed")
    if sha_file(ledger)!=LEDGER_SHA:
        raise ValueError("frozen_ledger_drift")
    a=json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())["rows"]
    b=json.loads((inputs/"bybit_october_input_extension.json").read_bytes())["rows"]
    rows=a+b
    if hashlib.sha256(canonical(rows)).hexdigest()!=OHLC_SHA:
        raise ValueError("ohlc_rows_modified")
    ref={}
    with gzip.open(ledger,"rt",encoding="utf-8") as f:
        for line in f:
            x=json.loads(line);k=x["key"]
            if (k["venue"],k["capital"],k["profile"],k["case"])!=("Bybit",10000,"normal","baseline") or k["window"] not in WINDOWS:
                continue
            if k["window"] in ref:raise ValueError("duplicate_baseline")
            ref[k["window"]]=x
    if set(ref)!=set(WINDOWS):raise ValueError("missing_baseline")
    windows={}
    for w,(winners,losers) in WINDOWS.items():
        rec=ref[w]
        positions=rec["positions"]
        if len(positions)!=winners+losers or len(rec["decisions"])!=len(positions):
            raise ValueError("baseline_counts_changed")
        if any(not d["allowed"] for d in rec["decisions"]):
            raise ValueError("baseline_veto_detected")
        flags=[]
        for i,pos in enumerate(positions):
            signal_index=pos["entry"]["signal_index"]
            if signal_index!=rec["decisions"][i]["signal_index"]:
                raise ValueError("entry_episode_alignment")
            if rows[signal_index+1][0]!=pos["entry"]["fill_ms"]:
                raise ValueError("entry_fill_timestamp_not_next_open")
            pnl=D(str(pos["net_pnl_usdt"]))
            if pnl==0:raise ValueError("unknown_zero_trade_label")
            flag=new_low_break(rows,signal_index)
            flags.append({
                "entry_utc_ms":int(pos["entry"]["fill_ms"]),
                "signal_index":signal_index,
                "prior_30_low_break":flag,
                "realized_historical_baseline_pnl_usdt":float(pnl),
                "label":("winner" if pnl>0 else "loser"),
            })
        wins=[f for f in flags if f["label"]=="winner"]
        losses=[f for f in flags if f["label"]=="loser"]
        if (len(wins),len(losses))!=(winners,losers):
            raise ValueError("outcome_count_modified")
        wf=[x for x in wins if x["prior_30_low_break"]]
        lf=[x for x in losses if x["prior_30_low_break"]]
        win_profit=D(str(sum(x["realized_historical_baseline_pnl_usdt"] for x in wins)))
        # Counts and financial attribution are descriptive on the FROZEN
        # compounded baseline account; NEVER substitute for new portfolio PNL.
        lost_winner=D(str(sum(x["realized_historical_baseline_pnl_usdt"] for x in wf)))
        retained_fraction=float(1-lost_winner/win_profit) if win_profit else 1
        loss_recall=len(lf)/len(losses)
        win_exclusion=len(wf)/len(wins)
        gate=(loss_recall>=.5 and win_exclusion<=.2 and retained_fraction>=.8)
        windows[w]={
            "baseline_winners":len(wins),
            "baseline_losers":len(losses),
            "flagged_winners":len(wf),
            "flagged_losers":len(lf),
            "flagged_total":len(wf)+len(lf),
            "loss_capture_fraction":round(loss_recall,8),
            "winner_exclusion_fraction":round(win_exclusion,8),
            "baseline_winning_pnl_usdt":round(float(win_profit),8),
            "baseline_winning_pnl_sacrificed_usdt":round(float(lost_winner),8),
            "baseline_winning_pnl_retained_fraction":round(retained_fraction,8),
            "flagged_baseline_trade_pnl_sum_usdt":round(sum(x["realized_historical_baseline_pnl_usdt"] for x in flags if x["prior_30_low_break"]),8),
            "fisher_one_sided_loss_enrichment_p_exploratory":round(fisher_loss_enrichment(len(wf),len(lf),winners,losers),8),
            "preregistered_descriptive_gate_pass":gate,
            "entry_records":flags,
        }
    all_pass=all(x["preregistered_descriptive_gate_pass"] for x in windows.values())
    out={
        "schema":"nexus.mr40.pre_entry_structure_break_audit.results.v1",
        "source_ohlc_sha256":OHLC_SHA,"source_ledger_sha256":LEDGER_SHA,
        "protocol_sha256":sha_file(protocol),
        "feature":"signal closed below prior 30 closed 4h LOW; not a fill",
        "windows":windows,
        "all_descriptive_gates_pass":all_pass,
        "candidate_backtest_authorized":all_pass,
        "historically_seen":True,
        "truly_unseen_oos":False,
        "paper_changed":False,"real_orders":0,"promote":False,"merge":False,
        "pnl_attribution_is_not_recompounded_counterfactual":True,
    }
    out["digest"]=hashlib.sha256(canonical(out)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"dig":out["digest"],"all_pass":all_pass,
      "windows":{key:{k:v for k,v in value.items() if k!="entry_records"} for key,value in windows.items()}},
      ensure_ascii=False))


if __name__=="__main__":
    ap=argparse.ArgumentParser()
    for name in ("inputs","ledger","protocol","output"):
        ap.add_argument("--"+name,required=True,type=Path)
    run(**vars(ap.parse_args()))
