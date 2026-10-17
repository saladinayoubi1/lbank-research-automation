"""V111 source-derived, CLOSED-minute, two-symbol hypothetical capacity bridge.

No market data accessed at module import. No network/Bybit order APIs.
Original V107 wave1/2 gate is confirmed at Wave2 right-confirmation.
After 2 FULLY CLOSED minutes (latency + source reference), construct a
purely illustrative BUY_SPOT reference at the SECOND bar's CLOSE (never
its earlier/open "fill"). No future outcome is used to admit candidates.
Full original chronology is retained; additional original candidates
are accounted as abstentions, denials, reservations, known-after closure.
Terminal open hypotheses retain capital reserved, not invented PnL.
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
from research.elliott_v110_portfolio_capacity import capacity_v110 as v110

SCHEMA="nexus.elliott-v111-source-bound-closed-minute-capacity-bridge.v1"
V110_COMMIT="fa887a366efd51d862e19a745352c5daf5cb5860"
V110_REL="docs/evidence/elliott-v110-capacity-20261017/V110_FROZEN_CAPACITY_RULEBOOK.json"
V110_SHA="718fef90e7f22e24af4266d334172d50ba11c882ccd0377fcb2d8c95813994f2"
ENTRY_REFERENCE_AFTER_COMPLETE_MINUTES=2
SOURCE_OBSERVATION_HORIZON_1M=240
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True


def manifest()->dict:
    return {
        "schema":SCHEMA,
        "status":"FROZEN_CLOSED_MINUTE_CAPACITY_ADAPTER_NO_REAL_MARKET_RESULTS",
        "frozen_v110_commit":V110_COMMIT,
        "frozen_v110_sha256":V110_SHA,
        "untouched_source_start_utc":v101.WINDOW_START_UTC,
        "untouched_source_end_exclusive_utc":v101.WINDOW_END_EXCLUSIVE_UTC,
        "market_source":"BYBIT_PUBLIC_SPOT_1M_IN_FUTURE_ONLY",
        "symbols":list(v101.PAIRS),
        "all_v107_consecutive_six_coarse_windows_retained":True,
        "v107_predecision_fine_sha_per_window_unchanged":True,
        "source_bound_prerequisite":"V103_V104_ARCHIVE_CONSENSUS_V107_FULL_REPLAY",
        "two_offline_parsers_same_archive_not_exchange_signed":True,
        "candidate_must_have_causal_v107_necessary_pass":True,
        "bearish_patterns_never_create_spot_short":True,
        "first_full_closed_minute_only_latency":True,
        "second_closed_minute_reference_is_its_close_not_open_fill":True,
        "reference_known_at_wave2_right_confirmation_plus_minutes":2,
        "any_wave0_or_wave1_touch_in_first_two_minutes_abstains":True,
        "reference_close_must_be_strictly_between_wave0_wave1":True,
        "admit_on_shared_v110_500usdt_budget_only_after_reference_known":True,
        "exit_proof_only_after_observed_one_minute_bar_close":True,
        "both_exit_barriers_same_bar_assume_wave0_origin_first":True,
        "no_exit_seen_keeps_hypothetical_cash_reserved":True,
        "no_fictional_timeout_close_from_unresolved_candidate":True,
        "no_retroactive_release_or_revaluation_of_old_admission":True,
        "fixed_entry_to_original_wave2_horizon_closed_minutes":240,
        "all_abstained_and_capacity_denied_windows_retained":True,
        "no_fills_no_exchange_orders_no_realized_pnl":True,
        "future_period_market_rows_read_today":0,
        "orders":0,"paper_eligible":False,"entry_signal":False,
        "live_enabled":False,"v52_unchanged":True,
    }


def freeze(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit immutable research Path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    witness=v93.immutable_receipt(
        V110_REL,V110_SHA,V110_COMMIT,v110.SCHEMA)
    if (witness.get("real_trades_placed")!=0
        or witness.get("spot_buy_cash_reserve_includes_entry_side_stress_cost") is not True
        or witness.get("live_enabled") is not False):
        raise ValueError("V110 parent scientific cost-capacity policy changed")
    raw=(json.dumps(manifest(),sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V111 original source-to-capacity contract altered")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"status":"V111_BRIDGE_FROZEN_NO_FUTURE_SOURCE",
            "sha256":hashlib.sha256(raw).hexdigest(),
            "real_source_rows_evaluated":0,
            "orders":0}


def source_intents_for_symbol(
    symbol:str,
    coarse:list[v99.ObservedSwing],
    fine:list[v99.ObservedSwing],
    physical:list[v102.Candle],
)->dict:
    """Source-shaped pure retrospective replay; synthetic tests only.

    Raw events can be forged by caller; only sealed_future_archive()
    verifies two separate offline parsers and the fixed source manifest.
    No later price condition is used to grant a PRE-decision observation.
    """
    if symbol not in v101.PAIRS or type(coarse) is not list or type(fine) is not list:
        raise ValueError("fixed original Bybit Spot pair and event streams only")
    start,end=v108.validate_physical_candles(physical)
    census=v107.enumerate_event_prefixes(fine,coarse,end)
    created=[]
    all_candidates=[]
    for i,candidate in enumerate(census["candidate_ledger"]):
        six=coarse[i:i+6]
        original_t=six[-1].confirmed_ms
        status=None
        evidence={}
        is_pass=candidate["necessary_partial_skeleton_pass"]
        side=("BUY_SPOT" if six[3].kind=="LOW" else "BEAR_MARKET_RESEARCH_ONLY")
        if not is_pass:
            status="ORIGINAL_V107_NECESSARY_SCREEN_REJECTED"
        elif side!="BUY_SPOT":
            status="BEAR_CANNOT_OPEN_SPOT_SHORT"
        elif original_t<start or (original_t-start)%v99.MINUTE:
            raise ValueError("candidate cutoff not present in original physical source")
        else:
            j=(original_t-start)//v99.MINUTE
            w0,w1=six[3].center_close,six[4].center_close
            if not (0<w0<w1):
                status="NONCOMPARABLE_WAVE0_WAVE1_PRICE_LEVELS"
            elif j+ENTRY_REFERENCE_AFTER_COMPLETE_MINUTES>len(physical):
                status="RIGHT_CENSORED_BEFORE_CLOSED_REFERENCE"
            else:
                first,second=physical[j:j+2]
                if (first.ms!=original_t or second.ms!=original_t+v99.MINUTE):
                    raise ValueError("missing original two closed 1m entry-reference bars")
                evidence={
                    "original_wave2_right_confirmation_ms":original_t,
                    "first_closed_latency_minute_known_ms":first.ms+v99.MINUTE,
                    "second_close_reference_known_ms":second.ms+v99.MINUTE,
                    "reference_source_price":str(second.close),
                }
                if (first.low<=w0 or first.high>=w1 or
                    second.low<=w0 or second.high>=w1):
                    status="BARRIER_TOUCHED_BEFORE_CLOSED_REFERENCE"
                elif not w0<second.close<w1:
                    status="SECOND_CLOSED_REFERENCE_OUTSIDE_WAVE_BARRIERS"
                else:
                    observed_at=second.ms+v99.MINUTE
                    created.append(v110.Intent(
                        candidate_id=f"{symbol}-W{i:06d}",
                        symbol=symbol,
                        side="BUY_SPOT",
                        decision_asof_ms=observed_at,
                        reference_known_ms=observed_at,
                        hypothetical_entry_close=second.close,
                        confirmed_wave0_stop=w0,
                    ))
                    status="SOURCE_CAUSAL_SPOT_LONG_REFERENCE_ONLY"
        all_candidates.append({
            "symbol":symbol,
            "original_v107_ordinal":i,
            "original_v107_decision_asof_ms":original_t,
            "original_coarse_window_sha256":candidate["coarse_window_sha256"],
            "original_fine_asof_sha256":candidate["visible_fine_stream_sha256"],
            "original_v107_necessary_screen_pass":is_pass,
            "reference_screen_status":status,
            "closed_reference_evidence":evidence,
            "does_not_trigger_order":True,
        })
    if len(all_candidates)!=census["all_consecutive_six_coarse_windows"]:
        raise ValueError("omitted original Elliott candidate")
    return {
        "schema":"nexus.elliott-v111-source-shaped-complete-candidate-census.v1",
        "symbol":symbol,"original_v107_census":census,
        "physical_minute_count":len(physical),
        "original_candidate_screens":all_candidates,
        "hypothetical_intents":created,
        "real_market_source_authenticated":False,
    }


def _find_known_barrier_release(
    intent:v110.Intent,
    original_wave2_confirmation_ms:int,
    wave1_barrier:Decimal,
    physical:list[v102.Candle],
)->tuple[v110.Resolution|None,str|None]:
    """Only original CLOSED bar touching barrier can release reservation.

    Right-censored & unresolved candidate stays open; never fabricate
    TIMEOUT_EXPLICITLY_CLOSED. Zero fill, mark-to-market or PnL claimed.
    """
    start,end=v108.validate_physical_candles(physical)
    earliest=intent.decision_asof_ms
    last=min(original_wave2_confirmation_ms+
             SOURCE_OBSERVATION_HORIZON_1M*v99.MINUTE,end)
    if earliest<start or earliest>end:
        raise ValueError("entry reference asof outside original source")
    for candle in physical[
        (earliest-start)//v99.MINUTE:(last-start)//v99.MINUTE
    ]:
        hit_origin=candle.low<=intent.confirmed_wave0_stop
        hit_wave1=candle.high>=wave1_barrier
        if hit_origin or hit_wave1:
            label=("BOTH_SAME_MINUTE_ASSUME_WAVE0_FIRST"
                   if hit_origin and hit_wave1 else
                   "WAVE0_OBSERVED_AFTER_REFERENCE_CLOSE"
                   if hit_origin else "WAVE1_OBSERVED_AFTER_REFERENCE_CLOSE")
            return (v110.Resolution(intent.candidate_id,
                    candle.ms+v99.MINUTE,candle.ms+v99.MINUTE,
                    "BARRIER_CLOSED"),label)
    return None,None


def portfolio_census_from_source_streams(
    series:dict[str,tuple[list[v99.ObservedSwing],
                          list[v99.ObservedSwing],
                          list[v102.Candle]]]
)->dict:
    """No source authentication here; all inputs synthetic/caller provided.

    Build *all* original V107 candidate screens with no selected winners,
    then replay only eligible closed-reference hypotheses with V110.
    Source-scoped prospective releases are observed at subsequent 1m
    CLOSE timestamps. Replayed historical admission rows are never
    revised when releases occur later. Unresolved entries remain reserved.
    """
    if type(series) is not dict or not series or (
        any(symbol not in v101.PAIRS for symbol in series)):
        raise ValueError("fixed Bybit public Spot pair universe required")
    details={}
    prepared=[]
    per_id={}
    original_count=0
    clock_end=None
    for symbol in sorted(series):
        pair=series[symbol]
        if type(pair) is not tuple or len(pair)!=3:
            raise ValueError("typed original three-stream tuple required")
        coarse,fine,physical=pair
        begin,end=v108.validate_physical_candles(physical)
        if clock_end is None:
            clock_end=end
        elif clock_end!=end:
            raise ValueError("cross-symbol portfolio must use same complete cutoff")
        source=source_intents_for_symbol(symbol,coarse,fine,physical)
        details[symbol]=source
        original_count+=source["original_v107_census"][
            "all_consecutive_six_coarse_windows"]
        for intent in source["hypothetical_intents"]:
            ordinal=int(intent.candidate_id.rsplit("-W",1)[1])
            original=source["original_candidate_screens"][ordinal]
            if original["reference_screen_status"]!=(
                "SOURCE_CAUSAL_SPOT_LONG_REFERENCE_ONLY"):
                raise ValueError("source-to-order reference barrier bypass")
            per_id[intent.candidate_id]=(
                intent,original["original_v107_decision_asof_ms"],
                coarse[ordinal+4].center_close,physical)
            prepared.append(intent)
    assert clock_end is not None
    prepared.sort(key=lambda x:(x.decision_asof_ms,x.symbol,x.candidate_id))
    all_proposals=[]
    authorized_releases=[]
    release_proofs=[]
    for candidate in prepared:
        now=candidate.decision_asof_ms
        effective=[e for e in authorized_releases if e.known_at_ms<=now]
        prefix=v110.replay(all_proposals+[candidate],effective,now)
        all_proposals.append(candidate)
        if prefix["original_admission_outcomes"][
            candidate.candidate_id]!="HYPOTHETICAL_RESERVED":
            continue
        _,w2,w1,physical=per_id[candidate.candidate_id]
        closed,label=_find_known_barrier_release(
            candidate,w2,w1,physical)
        if closed is not None:
            authorized_releases.append(closed)
            release_proofs.append({
                "candidate_id":candidate.candidate_id,
                "source_observation_known_at_ms":closed.known_at_ms,
                "observation_only_no_auction_fill":label,
                "real_order_or_realized_profit":False,
            })
    final=v110.replay(all_proposals,authorized_releases,clock_end)
    if (len(all_proposals)>original_count or
        final["original_intents_count"]!=len(all_proposals) or
        final["known_resolutions_count"]!=len(authorized_releases)):
        raise ValueError("hypothetical portfolio omitted source proposal")
    all_screens=[e for sym in sorted(details)
                 for e in details[sym]["original_candidate_screens"]]
    if len(all_screens)!=original_count:
        raise ValueError("unaccounted source Wave1/2 candidate")
    abstentions=len(all_screens)-len(all_proposals)
    if abstentions<0:
        raise ValueError("source reference denominator invalid")
    return {
        "schema":SCHEMA,
        "source_status":"CALLER_SUPPLIED_RESEARCH_STREAMS_NOT_MARKET_AUTHENTICATED",
        "all_v107_candidate_windows":original_count,
        "all_source_reference_abstentions":abstentions,
        "all_source_reference_proposals":len(all_proposals),
        "all_original_candidate_reference_screens":all_screens,
        "synthetic_later_barrier_closure_observations":release_proofs,
        "cash_capacity_v110":final,
        "all_events_timed_after_source_confirmation":True,
        "unresolved_synthetic_reservations_remain_open":True,
        "not_market_execution_or_executable_trade_entry":True,
        "no_market_pnl_or_real_elliott_validation":True,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"orders":0,"net_pnl":None,
    }


def evaluate_future_sealed_archive(folder:Path)->dict:
    """STRICT after-Nov30 offline original 42-page Bybit source procedure.

    First V107 full postwindow two-parser audit and original V99 source
    event reconstruction, then time-causal reference/capacity tracking.
    All 7 physical columns rehashed to original source; no network access.
    """
    if not isinstance(folder,Path):
        raise ValueError("explicit original source archive Path required")
    finish=v102.locked_range()[1]
    if int(datetime.now(timezone.utc).timestamp()*1000)<finish:
        raise ValueError("FUTURE_WINDOW_INCOMPLETE_NO_ARCHIVE_READ")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    v93.immutable_receipt(V110_REL,V110_SHA,V110_COMMIT,v110.SCHEMA)
    received=v107.evaluate_future_sealed_archive(folder)
    streams={}
    for symbol in v101.PAIRS:
        seven=[]
        for page in v104.descriptors():
            if page["symbol"]!=symbol:
                continue
            raw=(folder/(page["stem"]+".raw.json")).read_bytes()
            receipt=(folder/(page["stem"]+".receipt.json")).read_bytes()
            seven.extend(v104.validate_independent_page(page,raw,receipt)[
                "candles"])
        proof=received["symbol_ledger"][symbol]
        canon=json.dumps(seven,ensure_ascii=False,separators=(",",":")).encode()
        if (len(seven)!=v101.COMPLETE_SOURCE_ROWS_PER_PAIR
            or hashlib.sha256(canon).hexdigest()!=proof[
                "complete_source_sha256"]):
            raise ValueError("original seven-field source changed during V111 audit")
        candles=[v102.Candle(int(a[0]),*(Decimal(x) for x in a[1:]))
                 for a in seven]
        start,end=v108.validate_physical_candles(candles)
        if (start,end)!=v102.locked_range():
            raise ValueError("original complete Bybit Spot source changed")
        closes=[v99.CloseMinute(c.ms,c.close) for c in candles]
        fine=v99.observe_scale(closes,v101.FINE_SCALE,end)
        coarse=v99.observe_scale(closes,v101.COARSE_SCALE,end)
        original=v107.enumerate_event_prefixes(fine,coarse,end)
        if (original["candidate_ledger"]!=proof["candidate_ledger"]
            or v100.digest_events(coarse)!=proof["all_coarse_events_sha256"]
            or v100.digest_events(fine)!=proof["all_fine_events_sha256"]):
            raise ValueError("original wave2 causal ledger source disagreement")
        streams[symbol]=(coarse,fine,candles)
    output=portfolio_census_from_source_streams(streams)
    output["source_status"]="AFTER_FROZEN_PERIOD_TWO_PARSERS_SAME_ARCHIVE"
    output["exchange_payload_cryptographically_authenticated"]=False
    output["two_parser_agreement_is_not_independent_venue_observation"]=True
    output["original_complete_1m_rows_per_symbol"]=20160
    return output


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument("--mode",choices=("status","future-offline-source"),default="status")
    p.add_argument("--archive",type=Path)
    args=p.parse_args()
    if args.mode=="status":
        result={"schema":SCHEMA,
                "status":"V111_FROZEN_EARLY_RESEARCH_NO_SOURCE_OBSERVED",
                "market_candles_opened":0,"orders":0,
                "paper_eligible":False,"live_enabled":False}
    else:
        if args.archive is None:
            p.error("original complete future Bybit source archive required")
        result=evaluate_future_sealed_archive(args.archive)
    print(json.dumps(result,indent=2,sort_keys=True,default=str))
