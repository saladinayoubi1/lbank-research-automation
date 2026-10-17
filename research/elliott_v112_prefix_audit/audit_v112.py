"""V112 deterministic no-hindsight full-prefix portfolio audit; no orders.

Independent TIME-PREFIX challenge of V111. It reconstructs as-of event
streams from exactly those original events known at each selected complete
minute and replays the entire source->V110 synthetic capacity pipeline.
It verifies original admissions and log rows never change with later
physical OHLC, and that release after later bar close cannot rewrite a
past budget decision.

Every relevant event cutoff is checked, not a convenience sample. Audit
complexity may be large; if source exceeds a declared cap, fail closed
rather than claim an exhaustive result. No HTTP or trading adapters.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime,timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v99_causal_scale import scale_v99 as v99
from research.elliott_v100_scale_context import context_v100 as v100
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v104_independent_challenger import challenger_v104 as v104
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v108_forward_outcomes import outcomes_v108 as v108
from research.elliott_v111_source_capacity import bridge_v111 as v111

SCHEMA="nexus.elliott-v112-every-causal-checkpoint-portfolio-invariance-audit.v1"
PARENT_COMMIT="f7058b34367954d808303db4c6c61019889de54b"
PARENT_REL="docs/evidence/elliott-v111-source-capacity-20261017/V111_FROZEN_SOURCE_CAPACITY_BRIDGE.json"
PARENT_SHA="7625ab91721981be3b4bdc2337ff3daba504aae7b5970faad0510806365d6f17"
MAX_MANDATORY_CHECKPOINTS=4096
RESEARCH_ONLY=True
ORDER_ADAPTER=None
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
V52_UNCHANGED=True

def rulebook()->dict:
    return {
        "schema":SCHEMA,
        "state":"FROZEN_REPLAY_VERIFIER_SYNTHETIC_ONLY_ZERO_MARKET_EVALUATION",
        "v111_git_commit":PARENT_COMMIT,
        "v111_frozen_source_sha256":PARENT_SHA,
        "frozen_bybit_spot_start":v101.WINDOW_START_UTC,
        "frozen_bybit_spot_end_exclusive":v101.WINDOW_END_EXCLUSIVE_UTC,
        "symbols":list(v101.PAIRS),
        "original_coarse_and_fine_are_close_right_confirmed_only":True,
        "checkpoints":"ALL_ORIGINAL_WAVE2_RIGHT_CONFIRMATIONS_PLUS_SECOND_CLOSED_MINUTE_PLUS_CAPACITY_ADMISSION_AND_RELEASE_INSTANTS_PLUS_LAST_MINUTE",
        "checkpoint_event_must_be_complete_1m_closed":True,
        "prefix_has_no_pivot_confirmed_after_asof":True,
        "prefix_has_no_OHLC_bar_unclosed_by_asof":True,
        "all_candidate_decisions_causally_recomputed_at_each_checkpoint":True,
        "no_cutoff_sampling_or_random_skipping":True,
        "max_mandatory_checkpoints_before_explicit_block":MAX_MANDATORY_CHECKPOINTS,
        "full_prior_cash_event_ledger_must_be_byte_semantically_identical":True,
        "every_old_admission_status_never_changes_with_future_prices":True,
        "matured_reference_gate_never_changes_after_second_bar_close":True,
        "later_known_exit_can_only_append_ledger_event":True,
        "rejected_and_bearish_original_candidates_remain_accounted":True,
        "shared_cash_risk_budget_must_stay_within_v110_limits":True,
        "not_realized_profit_no_broker_min_order_sizes":True,
        "actual_source_available_today":False,
        "future_source_read_during_V112":0,
        "orders":0,"entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"v52_unchanged":True,
    }

def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit frozen rulebook path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    parent=v93.immutable_receipt(
        PARENT_REL,PARENT_SHA,PARENT_COMMIT,v111.SCHEMA)
    if (parent["orders"]!=0
        or parent["all_v107_consecutive_six_coarse_windows_retained"] is not True
        or parent["no_retroactive_release_or_revaluation_of_old_admission"] is not True):
        raise ValueError("source-bound upstream V111 contract broken")
    raw=(json.dumps(rulebook(),sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("FROZEN_V112_RULEBOOK_MUTATED")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"status":"V112_PREFIX_AUDIT_FROZEN_NO_SOURCE",
            "sha256":hashlib.sha256(raw).hexdigest(),
            "market_rows_evaluated":0,"actual_orders":0}


def _original_series(series:dict)->tuple[int,int]:
    if type(series) is not dict or not series or any(
        symbol not in v101.PAIRS for symbol in series):
        raise ValueError("original fixed Bybit Spot symbol streams required")
    endpoints=set()
    beginnings=set()
    for symbol,record in series.items():
        if type(record) is not tuple or len(record)!=3:
            raise ValueError("typed (coarse,fine,physical) original stream required")
        coarse,fine,bars=record
        begin,end=v108.validate_physical_candles(bars)
        if type(coarse) is not list or type(fine) is not list:
            raise ValueError("complete original source-confirmed swing streams required")
        v107.enumerate_event_prefixes(fine,coarse,end)
        endpoints.add(end)
        beginnings.add(begin)
    if len(endpoints)!=1 or len(beginnings)!=1:
        raise ValueError("cross-symbol original source period start/end disagree")
    return beginnings.pop(),endpoints.pop()


def complete_checkpoint_set(series:dict,full:dict)->list[int]:
    start,end=_original_series(series)
    points={start+v99.MINUTE,end}
    for symbol,record in series.items():
        coarse,fine,physical=record
        for event in coarse[5:]:
            ts=event.confirmed_ms
            if start<ts<=end:
                points.add(ts)
            if start<ts+2*v99.MINUTE<=end:
                points.add(ts+2*v99.MINUTE)
    for row in full["cash_capacity_v110"]["append_only_causal_event_ledger"]:
        known=row["known_at_ms"]
        if type(known) is not int or known%v99.MINUTE or not start<=known<=end:
            raise ValueError("invalid original cash event known-at timestamp")
        if known>start:
            points.add(known)
    ordered=sorted(points)
    if len(ordered)>MAX_MANDATORY_CHECKPOINTS:
        raise ValueError("MANDATORY_PREFIX_AUDIT_TOO_LARGE_FAIL_CLOSED")
    if not ordered or ordered[-1]!=end:
        raise ValueError("incomplete chronological source audit schedule")
    return ordered


def prefix_series_at(series:dict,when:int)->dict:
    original_start,original_end=_original_series(series)
    if (type(when) is not int or when%v99.MINUTE or
        not original_start<when<=original_end):
        raise ValueError("out-of-period or unclosed one-minute cutoff")
    result={}
    for symbol,(coarse,fine,bars) in series.items():
        upto=(when-original_start)//v99.MINUTE
        prefix_bars=bars[:upto]
        prefix_fine=[e for e in fine if e.confirmed_ms<=when]
        prefix_coarse=[e for e in coarse if e.confirmed_ms<=when]
        if (prefix_bars[-1].ms+v99.MINUTE!=when or
            any(e.confirmed_ms>when for e in prefix_fine+prefix_coarse)):
            raise ValueError("prefix looked into original source future")
        result[symbol]=(prefix_coarse,prefix_fine,prefix_bars)
    return result


def audit_every_causal_checkpoint(series:dict,provided_final:dict|None=None)->dict:
    """Differential prefix-vs-full source audit (synthetic/caller supplied).

    Never marks a portfolio order valid; each checkpoint replays V111 only
    using original event/bar prefixes. Source authenticity is still a
    separate late-year sealed-market concern.
    """
    start,end=_original_series(series)
    final=v111.portfolio_census_from_source_streams(series)
    if provided_final is not None and final!=provided_final:
        raise ValueError("V111_FINAL_CANDIDATE_OR_CAPACITY_LEDGER_TAMPERED")
    timeline=complete_checkpoint_set(series,final)
    final_cash=final["cash_capacity_v110"]
    last_original_statuses=final_cash["original_admission_outcomes"]
    full_events=final_cash["append_only_causal_event_ledger"]
    global_matured={
        (x["symbol"],x["original_v107_ordinal"]):x
        for x in final["all_original_candidate_reference_screens"]
    }
    checkpoints=[]
    for when in timeline:
        snapshot=v111.portfolio_census_from_source_streams(
            prefix_series_at(series,when))
        cash=snapshot["cash_capacity_v110"]
        expected_events=[event for event in full_events if event["known_at_ms"]<=when]
        if cash["append_only_causal_event_ledger"]!=expected_events:
            raise ValueError("FUTURE_PRICE_REWROTE_EARLIER_CAPACITY_EVENTS")
        for candidate,admission in cash["original_admission_outcomes"].items():
            if last_original_statuses.get(candidate)!=admission:
                raise ValueError("FUTURE_PRICE_REWROTE_PRIOR_ADMISSION")
        for screen in snapshot["all_original_candidate_reference_screens"]:
            # Before the two postconfirmation bars, its status is
            # intentionally provisional "right censored". Once those
            # two original bars CLOSE, it becomes immutable.
            mature=screen["original_v107_decision_asof_ms"]+2*v99.MINUTE
            if mature<=when and global_matured.get((
                screen["symbol"],screen["original_v107_ordinal"]))!=screen:
                raise ValueError("FUTURE_DATA_REVISED_MATURED_REFERENCE_SCREEN")
        if (Decimal(cash["reserved_usdt"])>Decimal("500")
            or Decimal(cash["unreserved_cash_usdt"])<0
            or Decimal(cash["stressed_gapless_risk_reserve_usdt"])>Decimal("5")):
            raise ValueError("historical hypothetical shared capacity exceeded")
        checkpoints.append({
            "source_cutoff_ms":when,
            "source_closed_minutes_per_symbol":(when-start)//v99.MINUTE,
            "observable_cash_events":len(expected_events),
            "original_v107_candidates_seen":snapshot["all_v107_candidate_windows"],
            "hypothetical_reference_intents_seen":snapshot[
                "all_source_reference_proposals"],
            "open_reservations_at_cutoff":len(cash["open_symbol_reservations"]),
            "replay_events_sha256":hashlib.sha256(json.dumps(
                expected_events,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            "prior_decisions_unchanged":True,
            "real_trade_count":0,
        })
    return {
        "schema":SCHEMA,
        "source_status":"CALLER_PROVIDED_STREAMS_SYNTHETIC_DIFFERENTIAL_ONLY",
        "source_1m_minutes_per_symbol":(end-start)//v99.MINUTE,
        "all_mandatory_causal_checkpoints":len(timeline),
        "no_checkpoint_omitted":True,
        "all_original_candidate_windows":final["all_v107_candidate_windows"],
        "all_final_hypothetical_reference_proposals":final[
            "all_source_reference_proposals"],
        "final_portfolio_event_count":len(full_events),
        "differential_asof_ledger_checks":checkpoints,
        "final_v111_event_log_digest":hashlib.sha256(json.dumps(
            full_events,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        "source_authenticity_not_proven":True,
        "market_prediction_or_profitability_not_established":True,
        "trade_count":0,"entry_signal":False,
        "paper_eligible":False,"live_enabled":False,"net_pnl":None,
    }


def verify_sealed_v111_source_overlay(sealed:dict,baseline:dict)->None:
    """Permit ONLY three authenticated-archive flags and one known status.

    Every other original candidate/admission/exit record, source hash and
    budget must be the SAME value as rederived from the original physical
    dataset. This cannot validate a forged TLS receipt's exchange origin.
    """
    if type(sealed) is not dict or type(baseline) is not dict:
        raise ValueError("V111 source overlay must be typed records")
    expected_extra={
        "exchange_payload_cryptographically_authenticated",
        "two_parser_agreement_is_not_independent_venue_observation",
        "original_complete_1m_rows_per_symbol",
    }
    if (set(sealed)-set(baseline)!=expected_extra or
        set(baseline)-set(sealed) or
        any(sealed[k]!=v for k,v in baseline.items() if k!="source_status")
        or sealed.get("source_status")!=
           "AFTER_FROZEN_PERIOD_TWO_PARSERS_SAME_ARCHIVE"
        or sealed.get("exchange_payload_cryptographically_authenticated") is not False
        or sealed.get("two_parser_agreement_is_not_independent_venue_observation") is not True
        or sealed.get("original_complete_1m_rows_per_symbol")!=20160):
        raise ValueError("reconstructed future original V111 ledger disagrees")


def evaluate_future_sealed_archive(folder:Path)->dict:
    """Future-only source-bound V112 audit. No HTTP or order endpoints.

    No archival IO until completion of frozen V101 source period. All
    original Bybit-shaped market rows must first pass V103/V104 through
    V111 source adapter, then re-opened seven-field rows must reproduce
    the exact same original V111 candidate screens and reserve event log.
    """
    if not isinstance(folder,Path):
        raise ValueError("explicit original archived source Path required")
    finish=v102.locked_range()[1]
    if int(datetime.now(timezone.utc).timestamp()*1000)<finish:
        raise ValueError("FUTURE_WINDOW_INCOMPLETE_NO_ARCHIVE_READ")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    v93.immutable_receipt(PARENT_REL,PARENT_SHA,PARENT_COMMIT,v111.SCHEMA)
    prior=v111.evaluate_future_sealed_archive(folder)
    streams={}
    for symbol in v101.PAIRS:
        original=[]
        for spec in v104.descriptors():
            if spec["symbol"]!=symbol:
                continue
            raw=(folder/(spec["stem"]+".raw.json")).read_bytes()
            sidecar=(folder/(spec["stem"]+".receipt.json")).read_bytes()
            original.extend(v104.validate_independent_page(spec,raw,sidecar)[
                "candles"])
        bars=[v102.Candle(int(r[0]),*(Decimal(n) for n in r[1:]))
              for r in original]
        start,end=v108.validate_physical_candles(bars)
        if ((start,end)!=v102.locked_range()
            or len(bars)!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR):
            raise ValueError("future complete physical source not preserved")
        closes=[v99.CloseMinute(c.ms,c.close) for c in bars]
        fine=v99.observe_scale(closes,v101.FINE_SCALE,end)
        coarse=v99.observe_scale(closes,v101.COARSE_SCALE,end)
        streams[symbol]=(coarse,fine,bars)
    fresh=v111.portfolio_census_from_source_streams(streams)
    verify_sealed_v111_source_overlay(prior,fresh)
    audited=audit_every_causal_checkpoint(streams,fresh)
    audited["source_status"]="POSTWINDOW_TWO_OFFLINE_PARSERS_SAME_ARCHIVE"
    audited["source_provider_signature_verified"]=False
    audited["all_original_source_rows"]=40320
    audited["independent_exchange_collection_evidence"]=False
    return audited


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--mode",choices=("status","future-offline-prefix-audit"),
                        default="status")
    parser.add_argument("--archive",type=Path)
    args=parser.parse_args()
    if args.mode=="status":
        report={
            "schema":SCHEMA,
            "status":"V112_FROZEN_SCIENTIFIC_AUDITOR_NO_MARKET_SOURCE_OBSERVED",
            "real_market_rows_evaluated":0,"orders":0,
            "paper_eligible":False,"live_enabled":False,
        }
    else:
        if args.archive is None:
            parser.error("future original sealed Bybit archive path required")
        report=evaluate_future_sealed_archive(args.archive)
    print(json.dumps(report,indent=2,sort_keys=True))
