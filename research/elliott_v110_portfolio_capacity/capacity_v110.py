"""V110 zero-order deterministic portfolio reservation ledger; NO PNL.

Only SYNTHETIC hypothetical public Spot BUY cash/risk capacity, tied to
original decision/observation timestamps. Intent objects CANNOT include
future outcomes. Resolution events free capacity solely at the instant
the closure becomes known (never their past historical center).
No V109 posthoc exit category is used to select or allocate candidates.
Not a trade simulator or Bybit compliant min-size/fees verifier.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from research.elliott_v109_spot_stress import stress_v109 as v109
from research.elliott_v101_preregistered_grammar import grammar_v101 as v101

SCHEMA="nexus.elliott-v110-two-asset-causal-spot-capacity-v1"
V109_REL="docs/evidence/elliott-v109-spot-stress-20261017/V109_FROZEN_SPOT_STRESS_RULEBOOK.json"
V109_SHA="86b4b02c33204e020065481def1c0b332da3e060e93883eab7153504d2444dd4"
V109_COMMIT="afa043041ac4600ae2145977f00ad176561f6d95"
CASH=Decimal("500")
MAX_ACTIVE=2
MAX_PER_SYMBOL=1
MAX_POSITION_USDT=Decimal("250")
MAX_RISK_PER_RESERVATION_USDT=Decimal("2.5")
MAX_AGGREGATE_OPEN_RISK_USDT=Decimal("5")
ENTRY_EXIT_STRESS_BPS_EACH_SIDE=Decimal("17")
COST_RATE=ENTRY_EXIT_STRESS_BPS_EACH_SIDE/Decimal("10000")
MINUTE=60000
CAPITAL_PRECISION=Decimal("0.00000001")
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True

@dataclass(frozen=True)
class Intent:
    candidate_id:str
    symbol:str
    side:str
    decision_asof_ms:int
    reference_known_ms:int
    hypothetical_entry_close:Decimal
    confirmed_wave0_stop:Decimal


@dataclass(frozen=True)
class Resolution:
    candidate_id:str
    observed_closed_ms:int
    known_at_ms:int
    reason:str


def plan()->dict:
    return {
        "schema":SCHEMA,
        "status":"FROZEN_SYNTHETIC_CAPACITY_ONLY_NO_MARKET_EVALUATION",
        "parent_v109_commit":V109_COMMIT,
        "parent_v109_sha256":V109_SHA,
        "prospective_source_start_utc":v101.WINDOW_START_UTC,
        "prospective_source_end_exclusive_utc":v101.WINDOW_END_EXCLUSIVE_UTC,
        "reference_paper_balance_usdt":str(CASH),
        "max_concurrent_reservations":MAX_ACTIVE,
        "max_concurrent_per_symbol":MAX_PER_SYMBOL,
        "fixed_symbols":list(v101.PAIRS),
        "max_notional_per_reservation_usdt":str(MAX_POSITION_USDT),
        "max_one_reservation_stressed_loss_usdt":str(MAX_RISK_PER_RESERVATION_USDT),
        "max_aggregate_reserved_stressed_loss_usdt":str(MAX_AGGREGATE_OPEN_RISK_USDT),
        "stress_entry_cost_bps":str(ENTRY_EXIT_STRESS_BPS_EACH_SIDE),
        "stress_exit_cost_bps":str(ENTRY_EXIT_STRESS_BPS_EACH_SIDE),
        "stress_costs_are_arbitrary_not_real_account_fees":True,
        "spot_cash_only_no_borrow_or_short_or_leverage":True,
        "declared_decision_and_reference_must_precede_reservation":True,
        "source_cutoff_must_be_complete_1m":True,
        "same_time_tiebreaker":"RESOLUTIONS_FIRST_THEN_SYMBOL_ASC_THEN_CANDIDATE_ID_ASC",
        "late_known_release_cannot_rewrite_prior_admission":True,
        "missing_release_cannot_free_reserved_cash_or_risk":True,
        "stressed_downside_includes_two_sided_costs":True,
        "spot_buy_cash_reserve_includes_entry_side_stress_cost":True,
        "no_trade_size_floor_or_bybit_qty_step_asserted":True,
        "hypothetical_usdt_reservation_rounds_down_to_8_decimals":True,
        "all_intents_accounted_including_capacity_rejections":True,
        "no_postdecision_price_outcome_on_intent":True,
        "no_future_exit_category_used_to_select_candidates":True,
        "denied_proposals_stay_in_denominator":True,
        "portfolio_event_log_is_append_only_causal":True,
        "ledger_summary_may_change_as_future_resolutions_arrive":True,
        "performance_not_measured":True,
        "real_trades_placed":0,
        "realized_pnl":None,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "v52_unchanged":True,
    }


def frozen_bytes()->bytes:
    return (json.dumps(plan(),sort_keys=True,indent=2)+"\n").encode()


def freeze_rulebook(path:Path)->dict:
    if not isinstance(path,Path):
        raise ValueError("explicit local research Path required")
    from research.elliott_v93_recursive_proof import proof_v93 as v93
    prev=v93.immutable_receipt(V109_REL,V109_SHA,V109_COMMIT,v109.SCHEMA)
    if (prev["orders"]!=0 or prev["zero_real_market_rows_accessed_during_v109"]
        is not True or prev["live_enabled"] is not False):
        raise ValueError("immutable upstream V109 research boundary changed")
    raw=frozen_bytes()
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("V110 FROZEN RULEBOOK DIFFERS; NO REWRITE")
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return {"state":"CAPACITY_RULES_FROZEN_SYNTHETIC_ONLY",
            "sha256":hashlib.sha256(raw).hexdigest(),
            "original_market_rows_accessed":0,"actual_orders":0}


def _valid_intent(intent:Intent)->None:
    if type(intent) is not Intent:
        raise ValueError("typed hypothetical intent required, no added outcome fields")
    if (type(intent.candidate_id) is not str or
        not intent.candidate_id.isascii() or
        not 0<len(intent.candidate_id)<=96):
        raise ValueError("nonempty ASCII research candidate identifier required")
    if (intent.symbol not in v101.PAIRS or intent.side!="BUY_SPOT"):
        raise ValueError("Bybit spot BUY only, no short/borrow/exchange substitution")
    if (type(intent.decision_asof_ms) is not int
        or type(intent.reference_known_ms) is not int
        or intent.decision_asof_ms%MINUTE
        or intent.reference_known_ms%MINUTE
        or intent.reference_known_ms>intent.decision_asof_ms):
        raise ValueError("cannot reserve before source reference is causally known")
    for n in (intent.hypothetical_entry_close,intent.confirmed_wave0_stop):
        if type(n) is not Decimal or not n.is_finite() or n<=0:
            raise ValueError("finite positive source-close or Wave0 required")


def _valid_resolution(event:Resolution)->None:
    if (type(event) is not Resolution or
        type(event.candidate_id) is not str or
        type(event.observed_closed_ms) is not int or
        type(event.known_at_ms) is not int or
        event.observed_closed_ms%MINUTE or
        event.known_at_ms%MINUTE or
        event.known_at_ms<event.observed_closed_ms or
        type(event.reason) is not str or
        event.reason not in ("BARRIER_CLOSED","TIMEOUT_EXPLICITLY_CLOSED",
                             "OPERATOR_SIMULATED_ABORT")):
        raise ValueError("release must be an explicitly known closed event")


def _money(d:Decimal)->str:
    return format(d,"f")


def _risk_rate(intent:Intent)->Decimal:
    # Stress loss based on gapless Wave0 barrier, worse gaps NOT covered
    # by reserved cap; do not call this a guaranteed maximum loss.
    ref=intent.hypothetical_entry_close
    stop=intent.confirmed_wave0_stop
    return (ref-stop)/ref + COST_RATE*Decimal(2)


def replay(
    intents:list[Intent],
    resolutions:list[Resolution],
    asof_ms:int,
)->dict:
    """Replay deterministic *KNOWN* research events, no broker side effects.

    At an identical instant, finalized closures release capacity before
    new intents are considered. Candidate priority is fixed alphabetically,
    independent of symbol profit or postdecision wave pattern outcomes.
    """
    if (type(intents) is not list or type(resolutions) is not list or
        type(asof_ms) is not int or asof_ms%MINUTE):
        raise ValueError("typed event lists and complete-minute cutoff required")
    proposals={}
    for intent in intents:
        _valid_intent(intent)
        if intent.candidate_id in proposals:
            raise ValueError("same candidate replayed twice")
        if intent.decision_asof_ms>asof_ms:
            raise ValueError("future candidate intent not available by asof")
        proposals[intent.candidate_id]=intent
    released_ids=set()
    for event in resolutions:
        _valid_resolution(event)
        if event.candidate_id not in proposals or event.candidate_id in released_ids:
            raise ValueError("duplicated or unknown research release")
        if event.known_at_ms>asof_ms:
            raise ValueError("future release not known by cutoff")
        if event.observed_closed_ms<proposals[event.candidate_id].decision_asof_ms:
            raise ValueError("future result used before original decision")
        released_ids.add(event.candidate_id)
    agenda=[]
    for item in intents:
        agenda.append((item.decision_asof_ms,1,item.symbol,
                       item.candidate_id,"intent",item))
    for item in resolutions:
        agenda.append((item.known_at_ms,0,"",item.candidate_id,
                       "release",item))
    agenda.sort(key=lambda x:x[:4])
    active={}
    admit_states={}
    reserved=Decimal(0)
    exposed=Decimal(0)
    events=[]
    for ts,_,symbol,candidate_id,kind,obj in agenda:
        if kind=="release":
            if candidate_id not in active:
                # A denied intent cannot later be "closed"; forbids fictive
                # release of another candidate's reserved capital.
                raise ValueError("resolution of inactive or denied research intent")
            holding=active.pop(candidate_id)
            reserved-=holding["capital_required"]
            exposed-=holding["loss_reserve"]
            events.append({
                "known_at_ms":ts,"event":"RELEASE_KNOWN",
                "candidate_id":candidate_id,
                "observed_closed_ms":obj.observed_closed_ms,
                "reason":obj.reason,
                "reserved_capital_after":_money(reserved),
                "stressed_risk_reserve_after":_money(exposed),
                "not_realized_pnl":True,
            })
            continue
        reason=None
        rate=_risk_rate(obj)
        if rate<=COST_RATE*Decimal(2):
            reason="INVALID_OR_NONPOSITIVE_WAVE0_RISK"
        elif len(active)>=MAX_ACTIVE:
            reason="MAX_CONCURRENT_RESEARCH_RESERVATIONS"
        elif any(v["symbol"]==obj.symbol for v in active.values()):
            reason="SAME_SYMBOL_RESERVATION_ALREADY_ACTIVE"
        elif CASH-reserved<=0 or MAX_AGGREGATE_OPEN_RISK_USDT-exposed<=0:
            reason="INSUFFICIENT_SHARED_CASH_OR_RISK_BUDGET"
        budget=Decimal(0)
        if reason is None:
            budget=min(MAX_POSITION_USDT,CASH-reserved,
                (CASH-reserved)/(Decimal(1)+COST_RATE),
                MAX_RISK_PER_RESERVATION_USDT/rate,
                (MAX_AGGREGATE_OPEN_RISK_USDT-exposed)/rate)
            budget=budget.quantize(CAPITAL_PRECISION,rounding=ROUND_DOWN)
            if budget<=0:
                reason="INSUFFICIENT_SHARED_CASH_OR_RISK_BUDGET"
        if reason is not None:
            admit_states[candidate_id]="DENIED_"+reason
            events.append({
                "known_at_ms":ts,"event":"DENIED_CAPACITY_OR_SOURCE",
                "candidate_id":candidate_id,"symbol":obj.symbol,
                "reason":reason,
                "reserved_capital_after":_money(reserved),
                "stressed_risk_reserve_after":_money(exposed),
            })
            continue
        reserve=budget*rate
        capital_required=budget*(Decimal(1)+COST_RATE)
        if (budget<=0 or reserve>MAX_RISK_PER_RESERVATION_USDT or
            reserved+capital_required>CASH or
            exposed+reserve>MAX_AGGREGATE_OPEN_RISK_USDT):
            raise ValueError("invariant: hypothetical shared risk/cash overallocated")
        active[candidate_id]={
            "symbol":obj.symbol,
            "notional":budget,
            "capital_required":capital_required,
            "loss_reserve":reserve,
            "decision_asof_ms":ts,
            "reference_close":obj.hypothetical_entry_close,
            "wave0_stop":obj.confirmed_wave0_stop,
        }
        reserved+=capital_required
        exposed+=reserve
        admit_states[candidate_id]="HYPOTHETICAL_RESERVED"
        events.append({
            "known_at_ms":ts,
            "event":"SYNTHETIC_CAPACITY_RESERVED_NOT_ORDER",
            "candidate_id":candidate_id,"symbol":obj.symbol,
            "hypothetical_notional_usdt":_money(budget),
            "hypothetical_buy_cash_plus_entry_stress_usdt":_money(capital_required),
            "assumed_gapless_stressed_loss_reserve_usdt":_money(reserve),
            "reserved_capital_after":_money(reserved),
            "stressed_risk_reserve_after":_money(exposed),
        })
    if (len(admit_states)!=len(intents) or
        len(active)>MAX_ACTIVE or
        reserved>CASH or exposed>MAX_AGGREGATE_OPEN_RISK_USDT):
        raise ValueError("proposal denominator or capacity invariant violated")
    return {
        "schema":SCHEMA,
        "source":"CALLER_SUPPLIED_HYPOTHETICAL_EVENTS_NOT_MARKET_AUTHENTICATED",
        "asof_ms":asof_ms,
        "original_intents_count":len(intents),
        "admitted_hypothetical_intents":sum(x=="HYPOTHETICAL_RESERVED"
                                           for x in admit_states.values()),
        "denied_hypothetical_intents":sum(x.startswith("DENIED_")
                                         for x in admit_states.values()),
        "known_resolutions_count":len(resolutions),
        "append_only_causal_event_ledger":events,
        "original_admission_outcomes":dict(sorted(admit_states.items())),
        "open_symbol_reservations":{x:active[x]["symbol"] for x in sorted(active)},
        "reserved_usdt":_money(reserved),
        "stressed_gapless_risk_reserve_usdt":_money(exposed),
        "unreserved_cash_usdt":_money(CASH-reserved),
        "unknown_future_outcomes_do_not_release_capacity":True,
        "stress_reserve_not_a_guaranteed_loss_bound_with_gaps":True,
        "no_verified_Bybit_min_qty_or_execution_fees":True,
        "real_market_profitability_proven":False,
        "trade_count":0,"entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"actual_net_pnl":None,
    }
