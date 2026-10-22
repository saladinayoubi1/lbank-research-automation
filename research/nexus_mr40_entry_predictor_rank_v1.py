"""Exact nonparametric rank stability of five frozen MR40 entry descriptors.
Labels are already observed trade outcomes. This diagnoses instability only.
NO strategy simulation, parameter sweep, predictive deployment or exchange API.
"""
from __future__ import annotations
import argparse,collections,hashlib,itertools,json,math
from pathlib import Path

SOURCE_DIGEST="f9576b4033ebe15d3485cd3fc65d3c0ada4f1a8bb676a9808105b467b374d614"
FEATURES=("short_drift6_pct","long_drift60_pct","trend180_pct","candle_body_pct","tr_to_prev_atr")
def canon(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def null_distribution(n,n_l):
    """Exact null distribution: enumerate every combination of loser ranks."""
    d=collections.Counter()
    offset=n_l*(n_l-1)//2
    for comb in itertools.combinations(range(n),n_l):
        u_l=sum(comb)-offset
        d[u_l]+=1
    if sum(d.values())!=math.comb(n,n_l):raise ValueError("combinatorial_distribution")
    return d
def audit(source,protocol,output):
    if output.exists():raise ValueError("refuse_overwrite")
    policy=json.loads(protocol.read_bytes()); x=json.loads(source.read_bytes())
    expected=x.pop("digest")
    if expected!=SOURCE_DIGEST or hashlib.sha256(canon(x)).hexdigest()!=SOURCE_DIGEST:
        raise ValueError("source_modified")
    if policy["schema"]!="mr40.entry-predictor-rank-stability.v1" or tuple(policy["predictors"])!=FEATURES or policy["windows"]!=["train","evaluation"]:
        raise ValueError("frozen_protocol_changed")
    rows=[];nulls={}
    for window in policy["windows"]:
        positions=x["windows"][window]["entries"]
        w=sum(bool(p["winner"]) for p in positions);n=len(positions);l=n-w
        if (window,w,l) not in (("train",19,6),("evaluation",18,4)):
            raise ValueError("unexpected_outcomes")
        distribution=null_distribution(n,l)
        nulls[window]={"N":n,"winners":w,"losers":l,"possible_labelings":sum(distribution.values())}
        for name in FEATURES:
            values=[(float(p[name]),bool(p["winner"])) for p in positions]
            values.sort(key=lambda z:z[0])
            if any(values[i][0]==values[i-1][0] for i in range(1,len(values))):
                raise ValueError("ties_need_conditional_permutation:"+window+":"+name)
            low_indices=[i for i,z in enumerate(values) if not z[1]]
            u_l=sum(low_indices)-l*(l-1)//2
            u=w*l-u_l
            centered=abs(2*u-w*l)
            numerator=sum(cnt for score,cnt in distribution.items() if abs(2*(w*l-score)-w*l)>=centered)
            denominator=sum(distribution.values())
            p_exact=numerator/denominator
            auc=u/(w*l)
            rows.append({"window":window,"feature":name,"winner_higher_auc":round(auc,8),
              "winner_over_loser_pairs":u,"all_pairs":w*l,
              "exact_two_sided_p":round(p_exact,8),
              "permutations_in_tail":numerator,"total_permutations":denominator})
    stability=[]
    for feat in FEATURES:
        a=next(z for z in rows if z["window"]=="train" and z["feature"]==feat)
        b=next(z for z in rows if z["window"]=="evaluation" and z["feature"]==feat)
        sign_ok=(a["winner_higher_auc"]-.5)*(b["winner_higher_auc"]-.5)>0
        passed=sign_ok and a["exact_two_sided_p"]<=.005 and b["exact_two_sided_p"]<=.005
        stability.append({"feature":feat,"same_direction":sign_ok,"both_p_below_adjusted_threshold":passed})
    out={"schema":"mr40.entry-predictor-rank-stability.results.v1",
         "source_logical_digest":SOURCE_DIGEST,
         "protocol_sha256":hashlib.sha256(protocol.read_bytes()).hexdigest(),
         "study":"Post hoc feature/outcome descriptive analysis, not unbiased forward validation.",
         "bonferroni_threshold":0.005,
         "baseline_counts":nulls,"rank_tests":rows,
         "stability":stability,
         "stable_significant_features":[p["feature"] for p in stability if p["both_p_below_adjusted_threshold"]],
         "promotion_allowed":False,"paper_changed":False}
    out["digest"]=hashlib.sha256(canon(out)).hexdigest()
    output.write_bytes(canon(out)+b"\n")
    print(json.dumps({"digest":out["digest"],"rank_tests":rows,"stable_significant_features":out["stable_significant_features"]},ensure_ascii=False),flush=True)

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("source","protocol","output"):parser.add_argument("--"+name,required=True,type=Path)
    audit(**vars(parser.parse_args()))
