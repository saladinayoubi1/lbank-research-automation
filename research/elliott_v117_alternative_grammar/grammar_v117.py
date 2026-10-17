"""V117 prospective causal necessary-grammar ABSTENTION experiment.

Baseline V106/V107 is immutable and is the sole control. Two strictly
predeclared ALTERNATIVE fine interior pivot COUNT sets are applied only
to the causal *same exact* six coarse events and same original observable
fine stream. Every non-count rejection remains hard. A necessary-screen
pass is NOT an Elliott count certification, trading entry or economic
outcome; cannot claim greater passes are better.

No July 2024 historical calibration/evaluation in this module and no
premature Nov 2026 Bybit future-source reads. Post-window research must
pass original dual offline source audit before deriving source pivots.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v104_independent_challenger import challenger_v104 as v104
from research.elliott_v106_early_partial import early_v106 as v106
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v116_failure_taxonomy import taxonomy_v116 as v116

SCHEMA="nexus.elliott-v117-prospective-unchanged-control-vs-even-subdivision-candidates.v1"
PARENT_COMMIT="a0196e1f3b5b9f107d67045db5bd1a54d423c817"
PARENT_REL="docs/evidence/elliott-v116-rejection-taxonomy-20261017/V116_FROZEN_REJECTION_CAUSES_RULEBOOK.json"
PARENT_SHA="0dab31a3f68086ae7c31fe880eae1543db081312afb03cb32c8b562ebf71bbe7"
COUNT_CODES=(
    "WAVE1_UNPRUNED_FINE_COUNT_NOT_PREDECLARED",
    "WAVE2_UNPRUNED_FINE_COUNT_NOT_PREDECLARED",
)
# Even-only interior counts retain strict alternating source-kind parity
# between observed LOW->HIGH / HIGH->LOW original fine-scale endpoints.
# No equality/overlapping price or other causal constraints are relaxed.
ARMS=(
    ("LOCKED_V106_EXACT_4_2",(4,),(2,)),
    ("EXPLORATORY_EVEN_NEAR_W1_2_4_6_W2_2_4",(2,4,6),(2,4)),
    ("EXPLORATORY_EVEN_BROAD_W1_2_4_6_8_W2_2_4_6",(2,4,6,8),(2,4,6)),
)
RESEARCH_ONLY=True
ORDER_ADAPTER=None
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
V52_UNCHANGED=True


def protocol()->dict:
    return {
        "schema":SCHEMA,
        "status":"PROSPECTIVELY_LOCKED_BEFORE_NOV_2026_BYBIT_SOURCE",
        "previous_v116_commit":PARENT_COMMIT,
        "previous_v116_frozen_SHA256":PARENT_SHA,
        "control_unchanged":True,
        "two_exploratory_families_fixed_a_priori":True,
        "source_bybit_public_spot_only_after_frozen_period":True,
        "frozen_source_start":v101.WINDOW_START_UTC,
        "frozen_source_end_exclusive":v101.WINDOW_END_EXCLUSIVE_UTC,
        "alternative_family_motivated_by_v116_old_source_failure_taxonomy":True,
        "historical_july_2024_market_returns_not_used_to_choose_alternatives":True,
        "scales":[str(x) for x in v99.TRAILING_MEDIAN_MULTIPLIERS],
        "all_original_consecutive_six_coarse_events_preserved":True,
        "all_non_fine_count_v106_rejections_hard_for_all_arms":True,
        "only_two_mutable_necessary_reasons":list(COUNT_CODES),
        "even_fine_counts_preserve_source_extremum_kind_parity":True,
        "no_pivot_deletion_or_relabeling":True,
        "fine_events_cutoff_at_original_w2_right_confirmation":True,
        "all_prior_context_origin_breach_fine_boundary_source_gates_preserved":True,
        "all_arms_original_same_candidate_denominator":True,
        "exploratory_multi_arm_selection_not_allowed_without_new_holdout":True,
        "report_counts_not_elliott_waves_or_signals":True,
        "no_independent_market_elliott_truth_labels":True,
        "no_realized_returns_win_rate_or_statistical_significance_claim":True,
        "future_archive_two_parsers_same_bytes_not_signed_by_venue":True,
        "arms":[{"name":name,
                 "allowed_wave1_unpruned_fine_interior":list(w1),
                 "allowed_wave2_unpruned_fine_interior":list(w2),
                 "decision":"ALL_OTHER_CAUSAL_HARD_GATES_STILL_MUST_PASS"}
                for name,w1,w2 in ARMS],
        "source_market_candles_examined_during_v117":0,
        "orders":0,"paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"v52_unchanged":True,
    }


def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit rulebook path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    witness=v93.immutable_receipt(
        PARENT_REL,PARENT_SHA,PARENT_COMMIT,v116.SCHEMA)
    if (witness["orders"]!=0 or
        witness["no_gate_relaxed_or_reordered"] is not True or
        witness["future_v101_bybit_window_not_accessed"] is not True):
        raise ValueError("V116 original unchanged necessary screen lost")
    raw=(json.dumps(protocol(),sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V117 PROSPECTIVE RULEBOOK CHANGED")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"sha256":sha256(raw).hexdigest(),
            "state":"ALTERNATIVE_ARMS_FROZEN_NO_MARKET_OUTCOMES",
            "market_rows":0,"orders":0}


def compare_one(
    six:list[v99.ObservedSwing],
    fine_observable:list[v99.ObservedSwing],
    asof:int,
)->dict:
    """All non-count gates are copied unchanged from V106 one-event result.

    This is a causal *necessary-condition* ABSTENTION classification only.
    Caller-supplied fine must be complete (source adapter enforces).
    """
    prior=v106.inspect_partial(six,fine_observable,asof)
    originals=list(prior["rejections"])
    observed=prior["observed_unpruned_counts"]
    if (len(observed)!=2 or any(type(x) is not int or x<0 for x in observed)):
        raise ValueError("original V106 exact two-leg fine count unavailable")
    invariant=[r for r in originals if r not in COUNT_CODES]
    answer={}
    for name,wave1,wave2 in ARMS:
        # Preserve the exact fixed V106 order of all failure codes.
        # Alternate arms may ONLY suppress an original fine COUNT failure.
        # They may NEVER clear a contextual, price or causal-boundary fault.
        bad=[
            reason for reason in originals
            if reason not in COUNT_CODES or
               (reason==COUNT_CODES[0] and observed[0] not in wave1) or
               (reason==COUNT_CODES[1] and observed[1] not in wave2)
        ]
        if name==ARMS[0][0]:
            if bad!=originals or (not bad)!=(not originals):
                raise ValueError("original frozen V106 strict control diverged")
        answer[name]={
            "necessary_partial_geometry_pass":not bad,
            "all_noncount_hard_failures":list(invariant),
            "observed_unpruned_wave1_wave2":list(observed),
            "failure_codes":bad,
            "wave_degree_certified":False,"entry_signal":False,
            "paper_eligible":False,
        }
    return {
        "schema":"nexus.elliott-v117-one-causal-candidate-arms.v1",
        "original_w2_confirmation_ms":asof,
        "original_six_coarse_sha256":prior["all_prefix_coarse_digest"],
        "predecision_complete_fine_sha256":prior["all_observable_fine_digest"],
        "original_v106_all_failures":originals,
        "original_v106_control_pass":not originals,
        "arms":answer,
        "certified_elliott_wave":False,"paper_eligible":False,
        "entry_signal":False,"live_enabled":False,
    }


def compare_all(
    fine:list[v99.ObservedSwing],
    coarse:list[v99.ObservedSwing],
    asof:int,
)->dict:
    """Every original consecutive six-coarse window, no favorable pruning.

    Calls original V107 first and validates full original row fingerprints.
    Each arm has same immutable denominator. No price outcomes or PnL.
    """
    original=v107.enumerate_event_prefixes(fine,coarse,asof)
    visible_confirmed=[e.confirmed_ms for e in fine]
    if visible_confirmed!=sorted(visible_confirmed):
        raise ValueError("nonchronological fine source")
    from bisect import bisect_right
    arm_pass=Counter()
    arm_pair=Counter()
    ledger=[]
    for i,reference in enumerate(original["candidate_ledger"]):
        end=reference["decision_asof_ms"]
        known=fine[:bisect_right(visible_confirmed,end)]
        outcome=compare_one(coarse[i:i+6],known,end)
        if (outcome["original_six_coarse_sha256"]!=reference[
             "coarse_window_sha256"] or
            outcome["predecision_complete_fine_sha256"]!=reference[
             "visible_fine_stream_sha256"] or
            outcome["original_v106_all_failures"]!=reference["rejections"] or
            outcome["original_v106_control_pass"]!=reference[
             "necessary_partial_skeleton_pass"]):
            raise ValueError("original 100%-denominator frozen V107 ledger differs")
        decision={}
        for name,_,_ in ARMS:
            hit=outcome["arms"][name]["necessary_partial_geometry_pass"]
            arm_pass[name]+=int(hit)
            decision[name]=hit
        arm_pair["|".join(name for name in decision if decision[name]) or
                 "ALL_ARMS_REJECTED"]+=1
        ledger.append({
            "original_coarse_window_ordinal":i,
            "decision_at_original_w2_confirmation_ms":end,
            "coarse_sha256":reference["coarse_window_sha256"],
            "predecision_fine_sha256":reference[
                "visible_fine_stream_sha256"],
            "original_fine_counts":outcome["arms"][ARMS[0][0]][
                "observed_unpruned_wave1_wave2"],
            "original_noncount_hard_failures":outcome["arms"][ARMS[0][0]][
                "all_noncount_hard_failures"],
            "original_control_pass":reference[
                "necessary_partial_skeleton_pass"],
            "predeclared_arm_necessary_passes":decision,
            "not_an_order_or_market_elliott_truth":True,
        })
    n=original["all_consecutive_six_coarse_windows"]
    if (len(ledger)!=n or sum(arm_pair.values())!=n or
        arm_pass[ARMS[0][0]]!=original[
           "necessary_partial_skeleton_passes"] or
        any(arm_pass[a[0]]>arm_pass[b[0]] for a,b in zip(ARMS[1:],ARMS[2:]))):
        raise ValueError("predeclared arm census not identical original denominator")
    # Controls subset of exploratory near; near subset of exploratory broad.
    if not all(
        row["predeclared_arm_necessary_passes"][ARMS[0][0]]<=
        row["predeclared_arm_necessary_passes"][ARMS[1][0]]<=
        row["predeclared_arm_necessary_passes"][ARMS[2][0]]
        for row in ledger):
        raise ValueError("original/alternate pass-set inclusion violated")
    fingerprint=sha256(json.dumps(ledger,sort_keys=True,
        ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    return {
        "schema":SCHEMA,
        "source_status":"PURE_SOURCE_EVENTS_NOT_PROVIDER_AUTHENTICATED",
        "all_original_unpruned_six_event_windows":n,
        "original_v107_necessary_passes":original[
            "necessary_partial_skeleton_passes"],
        "each_arm_same_denominator":True,
        "all_predeclared_arm_necessary_passes":{
            name:arm_pass[name] for name,_,_ in ARMS},
        "mutually_exclusive_arm_pass_combinations":dict(sorted(
            arm_pair.items())),
        "original_decision_no_price_output_digest":fingerprint,
        "all_original_candidate_arms":ledger,
        "no_trading_performance_measurements":True,
        "elliott_degree_certificates":0,"orders":0,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"net_pnl":None,
    }


def evaluate_future_sealed_archive(folder:Path)->dict:
    """AFTER the untouched November future period, offline ONLY.

    Require original V107 42-response complete two-parser archived-source
    gate, then independently reopen all seven physical fields and exact
    original fine/coarse streams before evaluating predeclared arms.
    Return all arms with no choose-a-winner step or broker order.
    """
    if not isinstance(folder,Path):
        raise ValueError("explicit original complete Bybit archive Path required")
    period_end=v102.locked_range()[1]
    if int(datetime.now(timezone.utc).timestamp()*1000)<period_end:
        raise ValueError("NOV_2026_FUTURE_WINDOW_INCOMPLETE_NO_ARCHIVE_READ")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    v93.immutable_receipt(PARENT_REL,PARENT_SHA,PARENT_COMMIT,v116.SCHEMA)
    original=v107.evaluate_future_sealed_archive(folder)
    output={
        "schema":"nexus.elliott-v117-postwindow-two-parser-prospective-arm-census.v1",
        "source_limitation":"TWO_OFFLINE_PARSERS_SAME_ARCHIVE_NO_BYBIT_PAYLOAD_SIGNATURE",
        "original_v107_source_gate_preserved":True,
        "arms_fixed_pre_source":list(name for name,_,_ in ARMS),
        "all_pairs":{},
        "no_elliott_market_ground_truth_or_profit":True,
        "orders":0,"entry_signal":False,
        "paper_eligible":False,"live_enabled":False,"net_pnl":None,
    }
    for symbol in v101.PAIRS:
        seven=[]
        for spec in v104.descriptors():
            if spec["symbol"]!=symbol:
                continue
            raw=(folder/(spec["stem"]+".raw.json")).read_bytes()
            sidecar=(folder/(spec["stem"]+".receipt.json")).read_bytes()
            seven.extend(v104.validate_independent_page(spec,raw,sidecar)[
                "candles"])
        if len(seven)!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR:
            raise ValueError("future archived Bybit one-minute series incomplete")
        digest=sha256(json.dumps(
            seven,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        witness=original["symbol_ledger"][symbol]
        if digest!=witness["complete_source_sha256"]:
            raise ValueError("physical seven-field source changed after original audit")
        physical=[v102.Candle(int(r[0]),*(Decimal(n) for n in r[1:]))
                  for r in seven]
        from research.elliott_v108_forward_outcomes import outcomes_v108 as v108
        if v108.validate_physical_candles(physical)!=v102.locked_range():
            raise ValueError("different physical future source interval")
        closes=[v99.CloseMinute(bar.ms,bar.close) for bar in physical]
        fine=v99.observe_scale(closes,v101.FINE_SCALE,period_end)
        coarse=v99.observe_scale(closes,v101.COARSE_SCALE,period_end)
        original_census=v107.enumerate_event_prefixes(fine,coarse,period_end)
        if (original_census["candidate_ledger"]!=witness["candidate_ledger"] or
            v100.digest_events(fine)!=witness["all_fine_events_sha256"] or
            v100.digest_events(coarse)!=witness["all_coarse_events_sha256"]):
            raise ValueError("frozen V107 original complete source events revised")
        comparative=compare_all(fine,coarse,period_end)
        if (comparative["all_original_unpruned_six_event_windows"]!=
            original_census["all_consecutive_six_coarse_windows"] or
            comparative["original_v107_necessary_passes"]!=
            original_census["necessary_partial_skeleton_passes"]):
            raise ValueError("prospective all-arm denominator deviated from control")
        comparative["original_physical_7field_SHA256"]=digest
        comparative["original_closed_1m_source_rows"]=len(physical)
        comparative["provider_signature_verified"]=False
        output["all_pairs"][symbol]=comparative
    return output


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("status","future-offline-census"),default="status")
    p.add_argument("--archive",type=Path)
    args=p.parse_args()
    if args.mode=="status":
        result={"schema":SCHEMA,
                "status":"ALTERNATIVE_ARMS_FROZEN_NO_PROSPECTIVE_OBSERVATIONS",
                "actual_market_rows":0,"orders":0,"paper_eligible":False,
                "live_enabled":False}
    else:
        if args.archive is None:
            p.error("original complete prospective Bybit archive required")
        result=evaluate_future_sealed_archive(args.archive)
    print(json.dumps(result,sort_keys=True,indent=2))
