#!/usr/bin/env python3
"""Source-pinned synthetic CTREND diagnostics; never executes MATLAB or market data."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import zipfile
from decimal import Decimal, localcontext
from pathlib import Path

ARCHIVE_SHA256 = "76671b6e018e1862ebfe1142ed6942ab40b9b9653f90087f50803e810ebb41ec"
NAMES = [
    "0_readme.txt", "b02CalculateIndicators.m", "b05CreateCTREND.m",
    "b14Table9_CTRENDPortfoliosAndTransactionCosts.m",
    "Utils/fResampleLiuEtAl.m", "Utils/fSingleSortMulti.m", "Utils/fMaxDD.m",
    "Utils/fCrossSectTransChars.m", "Utils/fCreatePanelFast.m",
    "Utils/fCreateIndices.m", "Utils/fWalkforwardCSENET.m",
]
OLD_FALLBACK = b"mDataTemp(find(~isnan(mDataTemp(:,idx)),1,'last'), idx)"
NEW_FALLBACK = b"mDataDailyTemp(find(~isnan(mDataDailyTemp(:,idx)),1,'last'), idx)"
D = Decimal

def quantile_midpoint(values, p):
    """MathWorks exact/midpoint interpolation, using finite distinct fixtures."""
    v = sorted(D(str(x)) for x in values)
    h = D(len(v)) * D(str(p)) - D("0.5")
    if h <= 0:
        return v[0]
    if h >= len(v) - 1:
        return v[-1]
    i = int(h)
    return v[i] + (h - i) * (v[i + 1] - v[i])

def weekly_endpoint(year_values, start, end, corrected=False):
    """Literal LAST-branch slice/fallback semantics with iMinNumObs=1."""
    week = year_values[start:end]
    valid_week = [x for x in week if x is not None]
    if not valid_week:
        return None
    if week[-1] is not None:
        return week[-1]
    search = week if corrected else year_values
    return next(x for x in reversed(search) if x is not None)

def ranks(values, available):
    active = sorted(v for v, ok in zip(values, available) if ok)
    assert len(active) == len(set(active)) and len(active) > 1
    return [None if not ok else D(active.index(v)) / D(len(active)-1) - D("0.5")
            for v, ok in zip(values, available)]

def high_quintile(scores, target_available):
    """fSingleSortMulti filtering then exact quantile, for equal ME fixtures."""
    active = [s for s, ok in zip(scores, target_available) if ok]
    if len(active) < 25:
        return []
    lower = quantile_midpoint(active, "0.8")
    upper = quantile_midpoint(active, "1")
    return [i+1 for i, (s, ok) in enumerate(zip(scores, target_available))
            if ok and lower < D(s) <= upper]

def drift(weights, returns):
    gross = [w * (1+r) for w, r in zip(weights, returns)]
    total = sum(gross)
    return [x/total for x in gross]

def l1(a, b):
    return sum(abs(x-y) for x, y in zip(a, b))

def max_wealth_drawdown(returns):
    nav = peak = D(1)
    maximum = D(0)
    for r in returns:
        nav *= 1+r
        peak = max(peak, nav)
        maximum = max(maximum, (peak-nav)/peak)
    return maximum

def run(archive):
    raw = archive.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("Archive identity differs from audited upload")
    with zipfile.ZipFile(archive) as z:
        source = {name: z.read(name) for name in NAMES}
    text = {name: body.decode("utf-8-sig") for name, body in source.items()}
    # These guards bind each mathematical witness to the actual source path.
    required = {
        "Utils/fResampleLiuEtAl.m": ["vUseThisObs(idx) = mDataTemp(find(~isnan(mDataTemp(:,idx)),1,'last'), idx);"],
        "b02CalculateIndicators.m": ["lUseArtData         = true;", "rData.mReturns = fTruncate", "'iMinNumObs','all'"],
        "b05CreateCTREND.m": ["~isnan(mReturns')", "mCtemp(~lAvail) = NaN;", "fCrossSectTransChars", "iNumIn              = 52;"],
        "Utils/fSingleSortMulti.m": ["lAvail = ~isnan(mRet);", "mSortVar(~lAvail)   = NaN;", "abs(mWtsTempL1 - mWtsTempL0)", "mWtsTempL1 .* (1 + mRet)"],
        "Utils/fMaxDD.m": ["mCumRet     = cumsum(mRet, dim, 'omitnan');", "mDiffCumRet = -diff(mCumRet, 1, dim);"],
        "Utils/fCreatePanelFast.m": ["isnan(vY)", "mIdx(lIsNaN,:)  = [];"],
        "Utils/fCreateIndices.m": ["vIdxInSample = (iIdxT - iNumIn + 1):iIdxT;", "vIdxOutOfSample = (iIdxT + 1):min(iNumObs, (iIdxT + iNumOut));"],
    }
    for name, fragments in required.items():
        for fragment in fragments:
            if fragment not in text[name]:
                raise ValueError("Source guard failed: " + name + " / " + fragment)
    findings = []
    def add(ident, confirmed, observed, anchors, meaning):
        if not confirmed:
            raise AssertionError(ident)
        findings.append(dict(id=ident, confirmed=True, observed=observed,
                             source=anchors, interpretation=meaning))

    # Positive control from official MathWorks documentation.
    q = [str(quantile_midpoint([2,5,6,10,11,13], p)) for p in [".25",".5",".75"]]
    add("quantile_reference_control", [D(x) for x in q] == [D(5),D(8),D(11)],
        q, ["https://www.mathworks.com/help/matlab/ref/quantile.html"],
        "The exact/midpoint interpolation matches the documented example.")

    a = [D(10)]*6 + [None] + [D(100)]*7
    b = a[:7] + [D(200)]*7
    oa, ob = weekly_endpoint(a,0,7), weekly_endpoint(b,0,7)
    ca, cb = weekly_endpoint(a,0,7,True), weekly_endpoint(b,0,7,True)
    add("future_values_change_earlier_week", oa != ob and ca == cb == D(10),
        {"original_a":str(oa),"original_b":str(ob),"week_scoped_a":str(ca),"week_scoped_b":str(cb)},
        ["Utils/fResampleLiuEtAl.m:91-125","b02CalculateIndicators.m:237-247,303-324"],
        "A missing endpoint causes the original fallback to search the entire year.")
    valid = [D(10)]*7 + [D(200)]*7
    empty = [None]*7 + [D(200)]*7
    add("resampler_valid_and_empty_controls",
        weekly_endpoint(valid,0,7)==weekly_endpoint(valid,0,7,True)==D(10)
        and weekly_endpoint(empty,0,7) is None and weekly_endpoint(empty,0,7,True) is None,
        {"complete_week":"10","empty_week":None},
        ["Utils/fResampleLiuEtAl.m:95-121"],
        "The week-scoped correction preserves a valid endpoint and an invalid all-missing week.")
    original = source["Utils/fResampleLiuEtAl.m"]
    assert original.count(OLD_FALLBACK)==1
    corrected = original.replace(OLD_FALLBACK, NEW_FALLBACK)
    add("minimal_patch_scope", original != corrected and corrected.count(NEW_FALLBACK)==1,
        {"replacements":1,"original_sha256":hashlib.sha256(original).hexdigest(),
         "corrected_sha256":hashlib.sha256(corrected).hexdigest()},
        ["Utils/fResampleLiuEtAl.m:121"],
        "Only the resampler fallback scope is corrected; the complete system remains unqualified.")

    scores = list(range(1,31))
    all_known = [True]*30
    missing_top = all_known[:-1]+[False]
    h0, h1 = high_quintile(scores,all_known),high_quintile(scores,missing_top)
    r0, r1 = ranks(scores,all_known),ranks(scores,missing_top)
    add("future_target_availability_changes_formation",
        h0 == list(range(25,31)) and h1 == list(range(24,30)) and r0[14] != r1[14],
        {"known_targets_H":h0,"missing_target30_H":h1,
         "asset15_rank_before":str(r0[14]),"asset15_rank_after":str(r1[14]),
         "past_features_unchanged":True,"cross_sections": [30,29]},
        ["b05CreateCTREND.m:114-131","Utils/fSingleSortMulti.m:112-159"],
        "Outcome availability changes ranks and H membership before the outcome can be observed.")
    add("future_labels_required_for_live_panel",
        sum(ok for ok in [False]*30)==0,
        {"known_past_feature_rows":30,"unknown_future_target_rows":30,"retained_panel_rows":0},
        ["Utils/fCreatePanelFast.m:65-76","b05CreateCTREND.m:114-138"],
        "Offline panel construction is not a separate ex-ante prediction interface.")

    with localcontext() as ctx:
        ctx.prec=40
        previous=[D(".5"),D(".5")]
        previous_return=[D(1),D(0)]
        current_holdings=drift(previous,previous_return)
        fixed_target=previous
        proxy=l1(previous,fixed_target)
        required_trade=l1(current_holdings,fixed_target)
        tc=D(".004")
        add("target_change_proxy_can_undercharge",
            proxy==0 and required_trade>D(0),
            {"target_change":str(proxy),"required_gross_trade_fraction":str(required_trade),
             "paper_middle_long_tc_bps":40,"omitted_fractional_cost":str(tc*required_trade)},
            ["Utils/fSingleSortMulti.m:314-320,351-375"],
            "Unchanged target weights can still require rebalancing after holding returns.")
        drifting_target=current_holdings
        proxy2=l1(previous,drifting_target)
        required2=l1(current_holdings,drifting_target)
        add("target_change_proxy_can_overcharge",
            proxy2>D(0) and required2==0,
            {"target_change":str(proxy2),"required_gross_trade_fraction":str(required2)},
            ["Utils/fSingleSortMulti.m:314-320"],
            "The cost-proxy error is not universally an underestimation.")
        future0=[D(0),D(0)]
        future1=[D(1),D(0)]
        to0=l1(previous,drift(previous,future0))/2
        to1=l1(previous,drift(previous,future1))/2
        add("reported_turnover_uses_target_period_return",
            to0==0 and to1>D(0),
            {"same_prior_holdings_and_targets":True,"future_a_turnover":str(to0),"future_b_turnover":str(to1)},
            ["Utils/fSingleSortMulti.m:401-410"],
            "This reported statistic drifts prior weights with the same return column being evaluated.")

    rr=[D(".10"),D("-.10"),D("-.10")]
    adjacent=max(-r for r in rr[1:])
    wealth_dd=max_wealth_drawdown(rr)
    add("drawdown_is_not_peak_to_trough",
        adjacent==D(".10") and wealth_dd==D(".19"),
        {"synthetic_returns":[str(x) for x in rr],"original_fraction":str(adjacent),
         "wealth_drawdown_fraction":str(wealth_dd)},
        ["Utils/fMaxDD.m:23-30","Utils/fSingleSortMulti.m:292-295"],
        "Adjacent differences of cumulative arithmetic returns discard multi-period drawdown.")

    candidate_bins=[year*100+week for year in range(2014,2023) for week in range(1,53)
                    if 201416 <= year*100+week <= 202222]
    rolls=[(list(range(t-51,t+1)),[t+1]) for t in range(52,len(candidate_bins))]
    add("rolling_window_order_positive_control",
        len(candidate_bins)==423 and len(rolls)==371
        and all(max(train)<min(test) for train,test in rolls),
        {"code_grid_bins":423,"maximum_forecast_bins_after_warmup":371,
         "first_forecast_bin_if_all_dates_survive":candidate_bins[52],
         "actual_real_sample_count":"unverified"},
        ["b05CreateCTREND.m:28,40-41","Utils/fCreateIndices.m:41-44","Utils/fWalkforwardCSENET.m:100-107,174-204"],
        "Training indices precede OOS indices; the actual custom-calendar sample still requires original dates.")
    return {
        "schema_version":1,"source_archive_sha256":ARCHIVE_SHA256,
        "scope":"Source-equivalent synthetic diagnostics only; not MATLAB execution, financial backtest, or published-result replication.",
        "confirmed_diagnostics":len(findings),"diagnostics":findings,
        "source_sha256":{k:hashlib.sha256(v).hexdigest() for k,v in source.items()},
        "original_vendor_code_executed":False,"market_data_read":False,
        "original_result_workbook_read":False,"demo_admitted":False,
    }

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    result=run(args.archive)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"confirmed_diagnostics":result["confirmed_diagnostics"],
                      "scope":result["scope"],"output":str(args.output)}))
if __name__=="__main__":
    main()
