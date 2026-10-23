"""Exact, tie-aware exploratory signal-time regime audit on 47 SEEN MR40 trades.

NOT model selection, candidate strategy, statistically independent validation,
or an order/market-data client. Input features chosen after seeing medians.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
from math import comb
from pathlib import Path

from research.nexus_mr40_independent_closed_signal_v1 import canon

PROTOCOL="mr40_exploratory_regime_discrimination_protocol_20261023.json"
SOURCE="mr40_signal_time_regime_matrix_20261023.json"
OUTPUT="mr40_exploratory_regime_discrimination_20261023.json"
SHA="5ee377c2be5a954891052fba567cb2a67cb1528661d2696a696766da7ef4081d"
DIGEST="791b3edce8fc1959a35302fad0cca0e197315729107e7467cf49c0db53913550"
FEATURES=("ATR14_pct","return_180_closed_bars_pct")


def file_sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for x in iter(lambda:f.read(1<<20),b""):
            h.update(x)
    return h.hexdigest()


def exact_auc_test(features, winners):
    """Exact 2-sided permutation test, with paired, averaged midranks for ties.

    AUC is P(feature winner > feature loser) + 0.5 P(tie).
    High numerical feature value is the FIXED winner direction.
    """
    n=len(features)
    k=sum(not w for w in winners)
    if n!=len(winners) or not 0<k<n:
        raise ValueError("bad_binary_cohort")
    if n>25:
        raise ValueError("exact_enumeration_limit")
    if any(not isinstance(v,(int,float)) for v in features):
        raise ValueError("not_a_numeric_feature")
    from math import isfinite
    if not all(isfinite(v) for v in features):
        raise ValueError("nonfinite_feature")
    ranked=sorted(range(n),key=lambda i:features[i])
    rank2=[0]*n
    i=0
    while i<n:
        j=i+1
        while j<n and features[ranked[j]]==features[ranked[i]]:
            j+=1
        for a in ranked[i:j]:
            rank2[a]=i+j+1   # twice the mean one-based rank
        i=j
    pairs=k*(n-k)
    def u2(idxs):
        return sum(rank2[v] for v in idxs)-k*(k+1)
    lost_indices=[i for i,w in enumerate(winners) if not w]
    observed=u2(lost_indices)
    if not 0<=observed<=2*pairs:
        raise ValueError("rank_u_out_of_range")
    observed_extreme=abs(observed-pairs)
    tail=0
    total=comb(n,k)
    for subset in itertools.combinations(range(n),k):
        if abs(u2(subset)-pairs)>=observed_extreme:
            tail+=1
    return {
        "n":n,"winners":n-k,"losers":k,
        "auc_winner_higher":round(1-observed/(2*pairs),8),
        "exact_two_sided_p":round(tail/total,8),
        "permutations":total,
        "extreme_permutations":tail
    }


def inspect(root):
    ppath=root/"research"/PROTOCOL
    spec=json.loads(ppath.read_bytes())
    expected=spec["source"]
    if (spec.get("schema")!="nexus.mr40.exploratory_regime_discrimination.protocol.v1"
        or tuple(spec["features"])!=FEATURES
        or expected.get("SHA256")!=SHA or expected.get("logical_digest")!=DIGEST
        or spec.get("selection_bias","").find("after looking")<0
        or spec.get("safety",{}).get("promote") is not False):
        raise ValueError("predeclared_exploratory_test_changed")
    path=root/"results"/SOURCE
    if file_sha(path)!=SHA:
        raise ValueError("source_SHA256_drift")
    result=json.loads(path.read_bytes())
    digest=result.pop("digest",None)
    if digest!=DIGEST or hashlib.sha256(canon(result)).hexdigest()!=DIGEST:
        raise ValueError("source_logical_digest_changed")
    rows=result["per_position"]
    if len(rows)!=47:
        raise ValueError("expected_47_seen_positions")
    out=[]
    for cohort,nn,nw,nl in (("train",25,19,6),("evaluation",22,18,4)):
        s=[r for r in rows if r["window"]==cohort]
        if len(s)!=nn or sum(r["historical_label_after_exit_only"]=="winner" for r in s)!=nw or sum(r["historical_label_after_exit_only"]=="loser" for r in s)!=nl:
            raise ValueError("frozen_cohort_label_count_drift")
        if len(set(r["signal_index"] for r in s))!=nn:
            raise ValueError("duplicate_signal")
        wins=[r["historical_label_after_exit_only"]=="winner" for r in s]
        for feature in FEATURES:
            values=[float(r["features_at_completed_signal_close"][feature]) for r in s]
            stats=exact_auc_test(values,wins)
            stats.update({
                "feature":feature,"cohort":cohort,
                "multiplicity_corrected_p_4_tests":round(min(1,stats["exact_two_sided_p"]*4),8),
                "after_seen_data_feature_selection_exploratory_only":True
            })
            out.append(stats)
    result={
        "schema":"nexus.mr40.exploratory_regime_discrimination.v1",
        "observations":"previously_seen_47_not_future_OOS",
        "source_SHA256":SHA,
        "source_logical_digest":DIGEST,
        "protocol_sha256":file_sha(ppath),
        "locked_comparison_count":4,
        "results":out,
        "candidate_filter_authorized":False,
        "predictive_edge_verified":False,
        "paper_changed":False,
        "orders":0,
        "decision":"EXPLORATORY_NO_PROMOTE",
    }
    result["digest"]=hashlib.sha256(canon(result)).hexdigest()
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    a=p.parse_args()
    report=inspect(a.root)
    dest=a.root/"results"/OUTPUT
    created=False
    try:
        with dest.open("xb") as f:
            created=True
            f.write(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False).encode())
            f.write(b"\n")
    except OSError:
        if created and dest.exists():
            dest.unlink()
        raise
    print(json.dumps({"report_sha256":file_sha(dest),"digest":report["digest"],
                      "comparisons":report["results"]},sort_keys=True))


if __name__=="__main__":
    main()
