"""V107 exhaustive causal-prefix early Elliott hypothesis census.

Every SIX CONSECUTIVE confirmed coarse swings is a candidate and judged
at the sixth event's original right-confirmation time. Fine events are
filtered to confirmed<=THAT moment, not a full-sample future state.
This is a diagnostic research hypothesis census, NOT independent proof of
pattern identity, false-positive rate, profitability or a trading signal.
Actual future source (if later available) is admitted ONLY after both
V103 and V104 offline archived-source audits agree, and the V101 fixed
period completes; no HTTP or execution adapters exist in this module.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import hashlib
import json

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v103_tls_capture import capture_v103 as v103
from research.elliott_v104_independent_challenger import challenger_v104 as v104
from research.elliott_v106_early_partial import early_v106 as v106

SCHEMA="nexus.elliott-v107-complete-closed-prefix-early-contour-census.v1"
V106_REL="docs/evidence/elliott-v106-early-partial-20261017/V106_FROZEN_EARLY_PARTIAL.json"
V106_SHA="b5621cc22df287ea16e1cbcfaf0b94da4a6bb0a682b9ed3962ec69f08508b948"
V106_COMMIT="82cf2694dc99d40e2b6d3f09e25bdebe4409f0c7"
WINDOW_SIZE=v106.EXPECTED_COARSE_EVENTS
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True
ACTUAL_WAVE_CERTIFICATES=0


def rulebook()->dict:
    return {
        "schema":SCHEMA,
        "state":"FROZEN_EXHAUSTIVE_PREFIX_CENSUS_NOT_PROSPECTIVELY_EVALUATED",
        "v106_upstream_commit":V106_COMMIT,
        "v106_upstream_sha256":V106_SHA,
        "v101_future_start":v101.WINDOW_START_UTC,
        "v101_future_end_exclusive":v101.WINDOW_END_EXCLUSIVE_UTC,
        "fixed_bybit_public_spot_symbols":list(v101.PAIRS),
        "two_independent_close_swings":["3","8"],
        "all_consecutive_coarse_window_size":WINDOW_SIZE,
        "candidate_selection":"NO_SKIPS_ALL_SLIDING_WINDOWS_WITH_SIX_COARSE_EVENTS",
        "first_five_coarse_events_context_only":True,
        "decision_at_last_coarse_event_confirmation_not_center":True,
        "fine_source_confirmation_cutoff_at_each_candidate":True,
        "unknown_latest_pivot_never_counted":True,
        "eligible_fine_events_unpruned":True,
        "all_hard_rejection_reasons_recorded":True,
        "primary_rejection_is_first_fixed_source_grammar_reason":True,
        "ledger_denominator_includes_every_six_event_window":True,
        "coarse_windows_before_six_pivots_not_candidates":True,
        "not_measured_outcomes":["false_positive_rate","prediction_precision",
                                 "winning_rate","net_pnl","bybit_fills"],
        "only_future_complete_archived_source_may_enter_production_census":True,
        "source_must_pass_both_v103_and_v104_auditors":True,
        "two_parsers_same_archive_not_two_independent_exchanges":True,
        "future_source_not_read_or_fetched_during_v107":True,
        "no_broker_or_order_adapter":True,
        "real_market_census_evaluated":False,
        "paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"orders":0,"v52_unchanged":True,
    }


def bytes_rulebook()->bytes:
    return (json.dumps(rulebook(),sort_keys=True,indent=2,ensure_ascii=False)+"\n").encode()


def freeze_rulebook(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit research rulebook path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    witness=v93.immutable_receipt(
        V106_REL,V106_SHA,V106_COMMIT,v106.SCHEMA)
    if (witness["market_data_fetched_during_v106"]!=0 or
        witness["orders"]!=0 or
        witness["wave3_wave4_wave5_not_available_or_consulted"] is not True):
        raise ValueError("immutable upstream V106 research-only lineage changed")
    raw=bytes_rulebook()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V107 preregistered research rulebook modified")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {
        "status":"EXHAUSTIVE_PREFIX_RULES_FROZEN_NO_FUTURE_SOURCE_READ",
        "sha256":hashlib.sha256(raw).hexdigest(),
        "real_source_rows":0,"trades":0,
    }


def enumerate_event_prefixes(
    fine:list[v99.ObservedSwing],
    coarse:list[v99.ObservedSwing],
    asof:int,
)->dict:
    """Pure deterministic predecision-event replay, synthetic tests only.

    A future production caller MUST derive these streams itself from
    V99 and V103/V104 accepted complete physical close records. This pure
    helper alone cannot authenticate caller-supplied events. An additional
    candidate's future data can never revise an older candidate outcome.
    """
    if (type(fine) is not list or type(coarse) is not list or
        type(asof) is not int or asof%v99.MINUTE):
        raise ValueError("typed, complete-minute source streams required")
    if len(coarse)>=2:
        v100.causal_relationships(fine,coarse,asof)
    elif fine or coarse:
        # Require complete source-time validation even for too-short streams;
        # V100 supports >=2 coarse swings, so do not silently accept an
        # unverified single-pivot source claim in this research helper.
        for e in fine+coarse:
            v100._serial(e)
            if (e.confirmed_ms>asof or
                e.confirmed_ms!=e.center_ms+
                   (e.confirmed_index-e.center_index+1)*v99.MINUTE):
                raise ValueError("unseen or forged source stream before warmup")
    confirmed=[e.confirmed_ms for e in fine]
    complete=[]
    primary=Counter()
    each_reason=Counter()
    for offset in range(max(0,len(coarse)-WINDOW_SIZE+1)):
        window=coarse[offset:offset+WINDOW_SIZE]
        cutoff=window[-1].confirmed_ms
        cut=bisect_right(confirmed,cutoff)
        observed_fine=fine[:cut]
        decision=v106.inspect_partial(window,observed_fine,cutoff)
        reasons=decision["rejections"]
        if reasons:
            primary[reasons[0]]+=1
            for why in reasons:
                each_reason[why]+=1
        record={
            "window_ordinal":offset,
            "coarse_event_indices_in_original_stream":[offset,offset+WINDOW_SIZE-1],
            "decision_asof_ms":cutoff,
            "fine_confirmed_by_decision":cut,
            "coarse_window_sha256":decision["all_prefix_coarse_digest"],
            "visible_fine_stream_sha256":decision["all_observable_fine_digest"],
            "wave0_center_ms":decision["original_wave0_center_ms"],
            "wave2_center_ms":decision["wave2_center_ms"],
            "necessary_partial_skeleton_pass":decision[
                "partial_skeleton_and_context_necessary_pass"],
            "rejections":reasons,
            "certified_elliott_wave":False,
            "order_eligible":False,
        }
        complete.append(record)
    accepted=sum(e["necessary_partial_skeleton_pass"] for e in complete)
    if (accepted+sum(primary.values())!=len(complete)
        or len(complete)!=max(0,len(coarse)-5)):
        raise ValueError("exhaustive window denominator/rejection tally mismatch")
    return {
        "schema":SCHEMA,
        "source_status":"CALLER_EVENT_STREAM_NOT_SOURCE_AUTHENTICATED",
        "source_cutoff_ms":asof,
        "all_observed_coarse_confirmed_events":len(coarse),
        "all_observed_fine_confirmed_events":len(fine),
        "insufficient_initial_coarse_context_events":min(len(coarse),5),
        "all_consecutive_six_coarse_windows":len(complete),
        "necessary_partial_skeleton_passes":accepted,
        "necessary_partial_skeleton_rejections":len(complete)-accepted,
        "first_rejection_mutually_exclusive_counts":dict(sorted(primary.items())),
        "all_rejection_reasons_overlapping_counts":dict(sorted(each_reason.items())),
        "candidate_ledger":complete,
        "real_world_false_positive_rate":None,
        "predictive_success_rate":None,
        "net_pnl":None,
        "complete_elliott_degree_proven":False,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"orders":0,
    }


def utc_ms()->int:
    return int(datetime.now(timezone.utc).timestamp()*1000)


def evaluate_future_sealed_archive(folder:Path)->dict:
    """OFFLINE ONLY, fully postwindow, 2-parser source-bound research census.

    A future operator must separately collect 42 Bybit public archives with
    V103. Never called by V107 tests or during its preregistration, and
    cannot run before the frozen period ends. The two offline verifiers
    are NOT independent observations nor an exchange signature.
    """
    if not isinstance(folder,Path):
        raise ValueError("explicit future source archive path required")
    start,end=v102.locked_range()
    if utc_ms()<end:
        raise ValueError("FUTURE_WINDOW_NOT_CLOSED_NO_ARCHIVE_READ")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    v93.immutable_receipt(V106_REL,V106_SHA,V106_COMMIT,v106.SCHEMA)
    challenger=v104.audit_archive_independent(folder)
    primary=v103.audit_directory(folder)
    agreement=v104.compare_with_primary(challenger,primary)
    if (not agreement["independent_parsers_agree_on_raw_and_sidecar_bytes"]
        or agreement["bybit_cryptographic_source_authenticity_proven"]):
        raise ValueError("source provenance overstated or source disagreement")
    report={
        "schema":"nexus.elliott-v107-postwindow-all-prefixes-diagnostic.v1",
        "v101_source_window_start":start,
        "v101_source_window_end_exclusive":end,
        "v106_preregistered_sha256":V106_SHA,
        "source": "BYBIT_PUBLIC_SPOT_CLAIM_TWO_OFFLINE_PARSERS_AGREE",
        "exchange_payload_cryptographically_signed":False,
        "external_independent_market_collection":False,
        "source_origin_risk_remains":True,
        "source_complete_by_two_offline_parsers":True,
        "symbol_ledger":{},
        "no_exchange_orders":True,
        "entry_signal":False,
        "paper_eligible":False,
        "live_enabled":False,
        "net_pnl":None,
    }
    source_members={(x["symbol"],x["page"]):x for x in challenger["page_evidence"]}
    if len(source_members)!=42:
        raise ValueError("duplicate or missing original source member receipts")
    for symbol in v101.PAIRS:
        # Re-open each exact V104 independently parsed original archive row
        # and do not trust an externally supplied list of events/choices.
        observed=[]
        seven_fields=[]
        for spec in v104.descriptors():
            if spec["symbol"]!=symbol:
                continue
            raw=(folder/(spec["stem"]+".raw.json")).read_bytes()
            meta=(folder/(spec["stem"]+".receipt.json")).read_bytes()
            sealed=source_members[(symbol,spec["index"])]
            if (hashlib.sha256(raw).hexdigest()!=sealed["raw_sha256"] or
                hashlib.sha256(meta).hexdigest()!=sealed["receipt_sha256"]):
                raise ValueError("original archive mutated between two audits")
            piece=v104.validate_independent_page(spec,raw,meta)
            seven_fields.extend(piece["candles"])
            observed.extend(v99.CloseMinute(row[0],Decimal(row[4]))
                            for row in piece["candles"])
        serialized=json.dumps(seven_fields,ensure_ascii=False,separators=(",",":")).encode()
        if (hashlib.sha256(serialized).hexdigest()!=challenger[
                "per_symbol_7field_canonical_sha256"][symbol]):
            raise ValueError("full physical rows changed after source audit")
        verified=v99.validate_closed_prefix(observed,end)
        if (len(verified)!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR
            or verified[0].ms!=start or verified[-1].ms+v99.MINUTE!=end):
            raise ValueError("incomplete future source invalidates all candidates")
        fine=v99.observe_scale(verified,v101.FINE_SCALE,end)
        coarse=v99.observe_scale(verified,v101.COARSE_SCALE,end)
        split=start+(end-start)//2
        for scale,events in ((v101.FINE_SCALE,fine),(v101.COARSE_SCALE,coarse)):
            early=v99.observe_scale(verified,scale,split)
            if early!=[e for e in events if e.confirmed_ms<=split]:
                raise ValueError("source-derived future Week-A prefix was revised")
        ledger=enumerate_event_prefixes(fine,coarse,end)
        ledger["source_status"]="ARCHIVE_FULLY_AUDITED_TWO_PARSERS_NOT_EXCHANGE_SIGNED"
        ledger["original_close_candles"]=len(verified)
        ledger["complete_source_sha256"]=challenger[
            "per_symbol_7field_canonical_sha256"][symbol]
        ledger["all_fine_events_sha256"]=v100.digest_events(fine)
        ledger["all_coarse_events_sha256"]=v100.digest_events(coarse)
        ledger["first_week_prefix_invariant"]=True
        report["symbol_ledger"][symbol]=ledger
    return report


def static_status()->dict:
    return {
        "status":"V107_PREREGISTERED_NO_ACTUAL_WINDOW_CENSUS",
        "v107_source_data_fetched":0,
        "real_market_patterns_tested":0,
        "wave2_decisions_backdated":0,
        "entry_signal":False,
        "live_enabled":False,
        "orders":0,
    }


if __name__=="__main__":
    import argparse
    arg=argparse.ArgumentParser()
    arg.add_argument("--mode",choices=("status","future-offline-audit"),
                     default="status")
    arg.add_argument("--archive",type=Path)
    args=arg.parse_args()
    if args.mode=="status":
        result=static_status()
    else:
        if args.archive is None:
            arg.error("future audit requires original Bybit archive directory")
        result=evaluate_future_sealed_archive(args.archive)
    print(json.dumps(result,sort_keys=True,indent=2))
