"""V116 audit WHY V106/V107 necessary Elliott screens reject 99% of windows.

Historical July 2024 Binance Spot is ALREADY INSPECTED research data.
All 1,212 original 6-coarse-event windows retained with exact rejection
reasons, first-reason and overlapping counts, purely descriptive. No
parameter fitting, no substituted market source, no Elliott certificate,
no actual win rate, PnL, trade, Bybit or runner changes.
"""
from __future__ import annotations
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import time
from decimal import Decimal

from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v106_early_partial import early_v106 as v106
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v115_historical_profile import profile_v115 as v115

SCHEMA="nexus.elliott-v116-unchanged-necessary-screen-full-rejection-taxonomy.v1"
PARENT_COMMIT="b33faed4036f6bf0f5b10887333233ee49d3beb9"
PARENT_REL="docs/evidence/elliott-v115-old-source-full-pipeline-20261017/V115_FROZEN_OLD_SOURCE_PROFILE_RULEBOOK.json"
PARENT_SHA="5f4947ff76bcb4888e0591940fb1346906a3808d9c804f84f4ea08043b74332a"
SOURCE_REL="docs/evidence/elliott-v115-old-source-full-pipeline-20261017/V115_MEASURED_PREINSPECTED_BINANCE_FULL_PIPELINE.json"
SOURCE_SHA="0889548b2b4e713e618115345e76e467f7114a8f2ed762083bf208d2f099a1e9"
CATEGORIES={
    "MISSING_ALTERNATING_CONTEXT":"prior_context",
    "PRIOR_TREND_LOWER_HIGH_NOT_ATTESTED":"prior_context",
    "PRIOR_TREND_LOWER_LOW_NOT_ATTESTED":"prior_context",
    "WAVE1_NO_POSITIVE_DIRECTIONAL_MOVE":"wave_price_geometry",
    "WAVE2_BREACHES_OR_TOUCHES_WAVE0_ORIGIN":"wave_price_geometry",
    "WAVE2_NOT_A_STRICT_RETRACE_OF_WAVE1":"wave_price_geometry",
    "WAVE1_UNPRUNED_FINE_COUNT_NOT_PREDECLARED":"fine_subdivision_exact_counts",
    "WAVE2_UNPRUNED_FINE_COUNT_NOT_PREDECLARED":"fine_subdivision_exact_counts",
    "WAVE1_FINE_CONFIRMATION_UNAVAILABLE_AT_LEG_END":"confirmation_availability",
    "WAVE2_FINE_CONFIRMATION_UNAVAILABLE_AT_LEG_END":"confirmation_availability",
    "WAVE1_LEFT_CAUSAL_FINE_BOUNDARY_MISMATCH":"fine_boundary_causality",
    "WAVE1_RIGHT_CAUSAL_FINE_BOUNDARY_MISMATCH":"fine_boundary_causality",
    "WAVE2_LEFT_CAUSAL_FINE_BOUNDARY_MISMATCH":"fine_boundary_causality",
    "WAVE2_RIGHT_CAUSAL_FINE_BOUNDARY_MISMATCH":"fine_boundary_causality",
}
RESEARCH_ONLY=True
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True

def rules()->dict:
    return {
        "schema":SCHEMA,
        "status":"DESCRIPTIVE_OLD_SOURCE_ONLY_NEVER_MARKET_PROSPECTIVE_VALIDATION",
        "previous_v115_commit":PARENT_COMMIT,
        "previous_v115_locked_rulebook_sha256":PARENT_SHA,
        "historical_measured_output":SOURCE_REL,
        "historical_source":"BINANCE_SPOT_2024_07_01_TO_07_15_EXCLUSIVE",
        "historical_already_inspected_not_independent_holdout":True,
        "future_v101_bybit_window_not_accessed":True,
        "all_six_consecutive_coarse_pivot_candidates_counted":True,
        "original_v99_scales_preserved":True,
        "original_v106_fine_counts_preserved":list(v106.EARLY_LEG_FINE_COUNTS),
        "no_gate_relaxed_or_reordered":True,
        "all_overlapping_and_mutually_exclusive_rejection_reasons_counted":True,
        "first_rejection_only_is_ordered_not_unique_causal_explanation":True,
        "reason_categories_fixed_before_analysis":dict(sorted(CATEGORIES.items())),
        "descriptive_exact_one_reason_not_counterfactual_strategy":True,
        "rejection_fraction_not_false_positive_rate":True,
        "acceptance_not_certified_elliott_or_trade":True,
        "real_winrate_or_profit_not_computed":True,
        "no_threshold_optimization_or_posthoc_selection":True,
        "output_contains_no_individual_source_prices":True,
        "orders":0,"entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"v52_unchanged":True,
    }

def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit immutable frozen rulebook path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    witness=v93.immutable_receipt(PARENT_REL,PARENT_SHA,PARENT_COMMIT,v115.SCHEMA)
    if (witness.get("orders")!=0 or
        witness.get("no_trading_return_or_pnl") is not True or
        witness.get("source_exchange")!="BINANCE_SPOT_NOT_BYBIT"):
        raise ValueError("V115 old-source research gate modified")
    raw=(json.dumps(rules(),sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V116 FROZEN TAXONOMY PROTOCOL REWRITTEN")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"sha256":sha256(raw).hexdigest(),
            "status":"ORIGINAL_REJECTION_TAXONOMY_LOCKED",
            "new_market_source_rows":0,"orders":0}


def count_census(census:dict)->dict:
    if (type(census) is not dict or census.get("schema")!=v107.SCHEMA):
        raise ValueError("only complete original unfiltered V107 source census")
    events=census.get("all_observed_coarse_confirmed_events")
    rows=census.get("candidate_ledger")
    if (type(events) is not int or type(rows) is not list
        or len(rows)!=max(0,events-v107.WINDOW_SIZE+1)
        or census.get("all_consecutive_six_coarse_windows")!=len(rows)):
        raise ValueError("missing original complete V107 six-event denominator")
    primary=Counter()
    all_reasons=Counter()
    categories=Counter()
    combination=Counter()
    only_one=Counter()
    passes=0
    previous_cutoff=-1
    individual=[]
    for idx,row in enumerate(rows):
        if type(row) is not dict or row.get("window_ordinal")!=idx or row.get(
            "coarse_event_indices_in_original_stream")!=[
                idx,idx+v107.WINDOW_SIZE-1]:
            raise ValueError("historical candidate deleted/reordered")
        cutoff=row.get("decision_asof_ms")
        if type(cutoff) is not int or cutoff%v99.MINUTE or cutoff<=previous_cutoff:
            raise ValueError("historical right confirmation not monotonic")
        previous_cutoff=cutoff
        reasons=row.get("rejections")
        allowed=row.get("necessary_partial_skeleton_pass")
        if (type(reasons) is not list or len(reasons)!=len(set(reasons))
            or type(allowed) is not bool or allowed==bool(reasons)
            or any(type(x) is not str or x not in CATEGORIES for x in reasons)
            or row.get("certified_elliott_wave") is not False
            or row.get("order_eligible") is not False):
            raise ValueError("original V106 source failure list unrecognized or contradicted")
        if allowed:
            passes+=1
        else:
            primary[reasons[0]]+=1
            all_reasons.update(reasons)
            groups=sorted({CATEGORIES[r] for r in reasons})
            categories.update(groups)
            combination["+".join(groups)]+=1
            if len(reasons)==1:
                only_one[reasons[0]]+=1
        individual.append({"ordinal":idx,
                           "decision_asof_ms":cutoff,
                           "original_gate_pass":allowed,
                           "all_rejection_reasons":reasons,
                           "wave_coarse_sha256":row["coarse_window_sha256"],
                           "observable_fine_sha256":row["visible_fine_stream_sha256"]})
    refused=len(rows)-passes
    if (passes!=census.get("necessary_partial_skeleton_passes") or
        refused!=census.get("necessary_partial_skeleton_rejections") or
        dict(sorted(primary.items()))!=census.get(
            "first_rejection_mutually_exclusive_counts") or
        dict(sorted(all_reasons.items()))!=census.get(
            "all_rejection_reasons_overlapping_counts") or
        sum(primary.values())!=refused or
        sum(combination.values())!=refused):
        raise ValueError("original V107 all-rejections source tally changed")
    raw=json.dumps(individual,sort_keys=True,ensure_ascii=False,
                   separators=(",",":")).encode()
    return {
        "original_full_six_coarse_windows":len(rows),
        "original_necessary_passes":passes,
        "original_necessary_rejections":refused,
        "original_rejection_fraction":(
            f"{refused}/{len(rows)}" if rows else "0/0"),
        "first_rejection_mutually_exclusive_counts":dict(sorted(primary.items())),
        "all_rejection_reasons_overlapping_counts":dict(sorted(all_reasons.items())),
        "rejected_candidates_with_each_fixed_category":dict(sorted(categories.items())),
        "overlapping_category_combinations":dict(sorted(combination.items())),
        "single_exact_rejection_reason_cases":dict(sorted(only_one.items())),
        "rejection_reason_count_sum_not_unique_denominator":sum(all_reasons.values()),
        "all_original_candidate_outcomes_sha256":sha256(raw).hexdigest(),
        "actual_elliott_waves_certified":0,
        "real_source_profit_or_loss":None,
        "orders":0,
    }


def historical_source_rejection_audit()->dict:
    """Reopen original archived Binance data; no HTTP, no new source."""
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    witness=v93.immutable_receipt(PARENT_REL,PARENT_SHA,PARENT_COMMIT,v115.SCHEMA)
    if witness.get("orders")!=0:
        raise ValueError("V115 no-order lineage altered")
    saved=(Path(__file__).resolve().parents[2]/SOURCE_REL).read_bytes()
    if sha256(saved).hexdigest()!=SOURCE_SHA:
        raise ValueError("V115_ORIGINAL_MEASURED_SHA256_CHANGED")
    previous=json.loads(saved)
    if (previous.get("schema")!=v115.SCHEMA or
        previous.get("not_independent_holdout") is not True or
        previous.get("orders")!=0 or
        previous.get("source_period")!="2024-07-01-to-2024-07-15-exclusive-UTC"):
        raise ValueError("original V115 measured historical output altered")
    locked,receipt=v90.verify_locked_receipts()
    begin=time.perf_counter_ns()
    result={}
    for symbol in v115.SYMBOLS:
        physical=v115.historical_seven_fields(symbol,locked,receipt)
        from research.elliott_v108_forward_outcomes import outcomes_v108 as v108
        start,end=v108.validate_physical_candles(physical)
        original=[v99.CloseMinute(b.ms,b.close) for b in physical]
        fine=v99.observe_scale(original,v99.TRAILING_MEDIAN_MULTIPLIERS[0],end)
        coarse=v99.observe_scale(original,v99.TRAILING_MEDIAN_MULTIPLIERS[1],end)
        previous_events=previous["by_symbol_source_events"][symbol]
        from research.elliott_v100_scale_context import context_v100 as v100
        if (len(coarse)!=previous_events["coarse_confirmed"] or
            len(fine)!=previous_events["fine_confirmed"] or
            v100.digest_events(coarse)!=previous_events["coarse_SHA256"] or
            v100.digest_events(fine)!=previous_events["fine_SHA256"]):
            raise ValueError("original V115 source/candidate SHA256 mismatch")
        original_census=v107.enumerate_event_prefixes(fine,coarse,end)
        out=count_census(original_census)
        if out["original_full_six_coarse_windows"]!=previous_events[
            "all_coarse_candidate_windows"]:
            raise ValueError("V115 original event denominator not preserved")
        result[symbol]=out
    combined=Counter()
    for sym in result:
        combined.update(result[sym]["all_rejection_reasons_overlapping_counts"])
    passes=sum(v["original_necessary_passes"] for v in result.values())
    refused=sum(v["original_necessary_rejections"] for v in result.values())
    if (passes+refused != previous["full_two_week_source_to_capacity"][
            "all_original_six_coarse_windows"] or
        passes != sum(previous["full_two_week_source_to_capacity"][
            "reference_screen_counts"].get(k,0)
            for k in ("SOURCE_CAUSAL_SPOT_LONG_REFERENCE_ONLY",
                      "BARRIER_TOUCHED_BEFORE_CLOSED_REFERENCE",
                      "BEAR_CANNOT_OPEN_SPOT_SHORT"))):
        raise ValueError("previous complete V115 acceptance census contradicts source")
    return {
        "schema":SCHEMA,
        "source_kind":"PREINSPECTED_BINANCE_SPOT_JULY_2024_NOT_BYBIT",
        "independent_holdout":False,
        "source_archive_receipt_sha256":v90.SOURCE_RECEIPT_SHA,
        "previous_measured_full_pipeline_commit":PARENT_COMMIT,
        "previous_full_source_event_sha256":{
            s:previous["by_symbol_source_events"][s]["coarse_SHA256"]
            for s in result},
        "original_denominator":passes+refused,
        "accepted_necessary_hypotheses_not_wave_certificates":passes,
        "rejected_necessary_hypotheses_not_false_positives":refused,
        "historical_rejection_fraction":f"{refused}/{passes+refused}",
        "by_symbol":result,
        "combined_overlapping_rejection_causes":dict(sorted(combined.items())),
        "measured_single_run_ms":round((time.perf_counter_ns()-begin)/1e6,3),
        "no_threshold_or_selection_change":True,
        "no_real_PnL_or_bybit_orders":True,
        "live_enabled":False,"paper_eligible":False,
        "orders":0,"real_net_pnl":None,
    }


def write_once(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit measured old-data research file required")
    result=historical_source_rejection_audit()
    raw=(json.dumps(result,sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V116_EVIDENCE_IMMUTABILITY_VIOLATION")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"state":"COMPLETE_OLD_DATA_CANDIDATE_CAUSE_AUDIT",
            "sha256":sha256(raw).hexdigest(),
            "all_source_candidates":result["original_denominator"],
            "necessary_screen_passes":result[
                "accepted_necessary_hypotheses_not_wave_certificates"],
            "orders":0}


if __name__=="__main__":
    import argparse
    a=argparse.ArgumentParser()
    a.add_argument("--mode",choices=("status","recount"),default="status")
    a.add_argument("--out",type=Path)
    args=a.parse_args()
    if args.mode=="status":
        print(json.dumps({"schema":SCHEMA,
            "data":"ALREADY_INSPECTED_BINANCE_ONLY","orders":0},indent=2))
    else:
        if args.out is None:
            a.error("--out required")
        print(json.dumps(write_once(args.out),indent=2,sort_keys=True))
