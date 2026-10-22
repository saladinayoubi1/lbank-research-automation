"""Research-only MR40 as-of volume diagnostic, not a trading strategy.

Two predeclared descriptive features are computed using <= CLOSED signal bar.
Historical win/loss labels are joined only after feature computation.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import itertools
import json
import math
import statistics
from decimal import Decimal as D
from pathlib import Path

ROWS_SHA="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
LEDGER_SHA="2c7115bac4ae81cc5c21b9bfc96319d5bee79baa746074c92c998125a834331e"
FEATURES=("relative_base_volume_30","signed_candle_volume_proxy")
COUNTS={"train":(19,6),"evaluation":(18,4)}


def canon(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()

def sha_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1048576),b""):h.update(chunk)
    return h.hexdigest()

def features_asof(rows,j):
    if not isinstance(j,int) or j<30 or j>=len(rows):raise ValueError("insufficient_or_invalid_index")
    cur=rows[j]
    if len(cur)!=6 or any(len(rows[k])!=6 for k in range(j-30,j)):
        raise ValueError("malformed_ohlcv")
    op,hi,lo,cl,vol=[D(str(x)) for x in cur[1:6]]
    prior=[D(str(rows[k][5])) for k in range(j-30,j)]
    if any(not x.is_finite() or x<=0 for x in prior+[vol,op,hi,lo,cl]) or hi<=lo:
        raise ValueError("nonpositive_or_invalid_market_data")
    if hi<max(op,cl) or lo>min(op,cl):
        raise ValueError("invalid_ohlc")
    ref=statistics.median(prior)
    if ref<=0:raise ValueError("zero_prior_volume")
    ratio=vol/ref
    flow=ratio*(cl-op)/(hi-lo)
    return dict(relative_base_volume_30=float(ratio),signed_candle_volume_proxy=float(flow))

def exact_rank(winners,losers):
    """Exact 2-sided rank-label test, including ties, through permutations.

    This is hypothesis description only, not model selection.
    """
    vals=[(float(x),True) for x in winners]+[(float(x),False) for x in losers]
    vals.sort(key=lambda z:z[0])
    n=len(vals);w=len(winners);l=len(losers)
    assert (n,w,l) in ((25,19,6),(22,18,4))
    rank2=[]
    pos=0
    while pos<n:
        j=pos+1
        while j<n and vals[j][0]==vals[pos][0]:j+=1
        # Average ranks (0-indexed), scaled by 2.
        rank2.extend([pos+j-1]*(j-pos))
        pos=j
    l_idx=[i for i,x in enumerate(vals) if not x[1]]
    u_l2=sum(rank2[i] for i in l_idx)-l*(l-1)
    auc=(2*w*l-u_l2)/(2*w*l)
    obs_abs=abs(u_l2-w*l)
    tail=0
    trials=0
    for comb in itertools.combinations(range(n),l):
        score=sum(rank2[z] for z in comb)-l*(l-1)
        if abs(score-w*l)>=obs_abs:tail+=1
        trials+=1
    if trials!=math.comb(n,l):raise ValueError("enumeration_count")
    return {"winner_higher_auc":round(auc,8),"exact_two_sided_p":round(tail/trials,8),
            "tail_permutations":tail,"all_permutations":trials,
            "feature_ties_present":len({x[0] for x in vals})!=n}

def run(inputs,ledger,protocol,output):
    if output.exists():raise ValueError("refuse_overwrite")
    pol=json.loads(protocol.read_bytes())
    if (pol["schema"]!="nexus.mr40.entry-volume-microstructure-descriptive.v1"
        or tuple(x["id"] for x in pol["asof_descriptors"])!=FEATURES
        or any(x.get("lookback",30)!=30 for x in pol["asof_descriptors"])
        or pol["no_new_backtest"] is not True
        or pol["safety"]["promote"] is not False):
        raise ValueError("protocol_drift")
    if sha_file(ledger)!=LEDGER_SHA:raise ValueError("ledger_sha_drift")
    rows=(json.loads((inputs/"bybit_prepared_inputs.json").read_bytes())["rows"]+
          json.loads((inputs/"bybit_october_input_extension.json").read_bytes())["rows"])
    if hashlib.sha256(canon(rows)).hexdigest()!=ROWS_SHA:raise ValueError("OHLCV_sha_drift")
    refs={}
    with gzip.open(ledger,"rt",encoding="utf8") as f:
        for line in f:
            rec=json.loads(line);k=rec["key"]
            if (k["venue"],k["capital"],k["profile"],k["case"])!=("Bybit",10000,"normal","baseline") or k["window"] not in COUNTS:continue
            if k["window"] in refs:raise ValueError("duplicate_window")
            refs[k["window"]]=rec
    if set(refs)!=set(COUNTS):raise ValueError("missing_baseline")
    out_w={}
    for win,(expected_w,expected_l) in COUNTS.items():
        records=[]
        trades=refs[win]["positions"]; decisions=refs[win]["decisions"]
        if len(trades)!=expected_w+expected_l or len(trades)!=len(decisions):
            raise ValueError("baseline_trade_count_drift")
        for i,(p,d) in enumerate(zip(trades,decisions)):
            j=p["entry"]["signal_index"]
            if not d["allowed"] or j!=d["signal_index"] or rows[j+1][0]!=p["entry"]["fill_ms"]:
                raise ValueError("entry_time_out_of_alignment")
            # Historical realized PnL never passed into feature generator.
            feat=features_asof(rows,j)
            pnl=float(p["net_pnl_usdt"])
            if pnl==0:raise ValueError("unexpected_zero_trade")
            records.append({"entry_ms":p["entry"]["fill_ms"],"signal_index":j,
                            **{k:round(feat[k],8) for k in FEATURES},
                            "realized_pnl_usdt":round(pnl,8),
                            "realized_winner":pnl>0})
        winners=[p for p in records if p["realized_winner"]]
        losers=[p for p in records if not p["realized_winner"]]
        if (len(winners),len(losers))!=(expected_w,expected_l):
            raise ValueError("classification_drift")
        stats={}
        for name in FEATURES:
            w=[p[name] for p in winners];l=[p[name] for p in losers]
            stats[name]={"winner_median":round(statistics.median(w),8),
                         "loser_median":round(statistics.median(l),8),
                         **exact_rank(w,l)}
        out_w[win]={"positions":len(records),"winners":len(winners),"losers":len(losers),
                    "features":stats,"entries":records}
    comparisons=[]
    for name in FEATURES:
        a=out_w["train"]["features"][name];b=out_w["evaluation"]["features"][name]
        same=(a["winner_higher_auc"]-.5)*(b["winner_higher_auc"]-.5)>0
        eligible=(same and a["exact_two_sided_p"]<=.0125 and b["exact_two_sided_p"]<=.0125)
        comparisons.append({"feature":name,"same_direction":same,
                            "both_adjusted_exact_p_pass":eligible})
    report={"schema":"nexus.mr40.entry-volume-descriptive.results.v1",
            "source_row_sha256":ROWS_SHA,"source_ledger_sha256":LEDGER_SHA,
            "protocol_sha256":sha_file(protocol),
            "seen_data":True,"real_l2_flow_observed":False,
            "future_oos_available":False,
            "windows":out_w,"stability":comparisons,
            "candidate_entry_filter_authorized":False,
            "shadow_hypothesis_supported":any(x["both_adjusted_exact_p_pass"] for x in comparisons),
            "paper_changed":False,"real_orders":0,"promote":False}
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":report["digest"],"shadow_hypothesis_supported":report["shadow_hypothesis_supported"],
                      "stability":comparisons,
                      "windows":{k:{"winners":v["winners"],"losers":v["losers"],"features":v["features"]} for k,v in out_w.items()}},
                     ensure_ascii=False))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for arg in ("inputs","ledger","protocol","output"):p.add_argument("--"+arg,required=True,type=Path)
    run(**vars(p.parse_args()))
