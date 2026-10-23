"""Numerical necessary-condition screen for future MR40 closed trades, research only.

NOT a source verifier, broker, fill simulation, paper modification or permission
to promote. Input records are untrusted until independently audited.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal as D, InvalidOperation
from pathlib import Path
import argparse
import json

PROTOCOL = "research/mr40_forward_closed_trade_decision_gate_protocol_20261023.json"
CUTOFF = datetime(2026, 10, 23, tzinfo=timezone.utc)

def when(x):
    if not isinstance(x, str) or not x.endswith("Z"):
        raise ValueError("timestamp_must_be_UTC_Z")
    try:
        parsed = datetime.fromisoformat(x[:-1] + "+00:00")
    except ValueError as e:
        raise ValueError("invalid_utc_timestamp") from e
    return parsed

def finite(x):
    if isinstance(x, bool) or not isinstance(x, str):
        raise ValueError("decimal_must_be_string")
    try:
        v = D(x)
    except (InvalidOperation, ValueError) as e:
        raise ValueError("invalid_decimal") from e
    if not v.is_finite():
        raise ValueError("nonfinite_decimal")
    return v

def arm(name, x, start, end):
    if x.get("arm") != name or x.get("cost_profile") != "conservative":
        raise ValueError("arm_or_cost_profile_mismatch")
    trades = x.get("fully_closed_trades")
    if not isinstance(trades, list):
        raise ValueError("missing_closed_trade_ledger")
    ids, prev_end, net = set(), None, D(0)
    for t in trades:
        uid=t.get("trade_uid")
        if not isinstance(uid,str) or not uid or uid in ids:
            raise ValueError("empty_or_duplicate_trade_uid")
        ids.add(uid)
        first,last=when(t.get("entry_utc")),when(t.get("exit_utc"))
        if not start <= first < last <= end:
            raise ValueError("trade_outside_locked_forward_period_or_open")
        if prev_end is not None and first < prev_end:
            raise ValueError("long_only_trade_overlap")
        if t.get("closed") is not True or t.get("open_exposure") is not False:
            raise ValueError("incomplete_or_open_trade")
        prev_end=last
        net += finite(t.get("net_pnl_conservative_USDT"))
    reported=finite(x.get("net_pnl_conservative_USDT"))
    if reported != net:
        raise ValueError("declared_pnl_not_equal_to_closed_trade_sum")
    dd=finite(x.get("modeled_intratrade_low_DD_pct"))
    if not D(0) <= dd <= D(100):
        raise ValueError("invalid_modeled_low_drawdown")
    return {"closed_positions":len(trades),"net_USDT":net,"low_DD_pct":dd}

def assess(doc, protocol):
    if protocol.get("schema") != "nexus.mr40.forward_closed_trade_decision_gate.v1":
        raise ValueError("unexpected_locked_protocol")
    if protocol.get("min_fully_closed_positions_per_arm") != 12 or protocol.get("safety",{}).get("auto_promote") is not False:
        raise ValueError("locked_12_and_no_auto_promote_changed")
    if doc.get("schema") != "nexus.mr40.prospective_dual_arm_economic_claim.v1":
        raise ValueError("unexpected_forward_report_schema")
    if doc.get("source_market") != "Bybit BTCUSDT Spot" or doc.get("execution_mode") != "research_only":
        raise ValueError("wrong_venue_or_executable_report")
    if doc.get("historical_seen_47_included") is not False or doc.get("precommitted_locked_criteria") is not True:
        raise ValueError("historical_leakage_or_unlocked_threshold")
    if doc.get("same_observation_window_both_arms") is not True:
        raise ValueError("arms_not_same_observation_window")
    if finite(doc.get("initial_reference_capital_USDT")) != D(500):
        raise ValueError("capital_baseline_drift")
    start, end = when(doc.get("forward_start_utc")), when(doc.get("forward_end_utc"))
    if start < CUTOFF or end <= start:
        raise ValueError("forward_window_not_after_lock")
    # Declared evidence authenticity is not independently verifiable from
    # caller-supplied JSON. NEVER convert a numeric pass to promotion.
    arms=doc.get("arms")
    if not isinstance(arms,dict) or set(arms)!={"baseline","candidate"}:
        raise ValueError("expected_both_research_arms")
    base=arm("baseline",arms["baseline"],start,end)
    cand=arm("candidate",arms["candidate"],start,end)
    enough=(base["closed_positions"]>=12 and cand["closed_positions"]>=12)
    keeps_profit=(base["net_USDT"]>0 and cand["net_USDT"]>0 and cand["net_USDT"]>=base["net_USDT"])
    dd_ok=(base["low_DD_pct"]>0 and cand["low_DD_pct"]<=D("0.8")*base["low_DD_pct"])
    necessary=enough and keeps_profit and dd_ok
    return {
       "schema":"nexus.mr40.forward_numeric_screen.v1",
       "same_market_and_forward_window_claim_checked":True,
       "fully_closed_trade_counts":{"baseline":base["closed_positions"],"candidate":cand["closed_positions"]},
       "minimum_12_per_arm_met":enough,
       "conservative_net_profit_preserved_numerically":keeps_profit,
       "modeled_low_DD_at_least_20pct_better_numerically":dd_ok,
       "necessary_numeric_conditions_pass":necessary,
       "economic_edge_verified":False,
       "authentic_market_source_verified":False,
       "real_fill_verified":False,
       "independent_evidence_and_user_approval_required":True,
       "paper_or_live_promotion_authorized":False,
       "decision":"NUMERIC_PASS_REQUIRES_INDEPENDENT_REVIEW" if necessary else "NO_PROMOTE_NUMERIC_GATE_FAILED"
    }

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--report",type=Path,required=True)
    parser.add_argument("--protocol",type=Path,required=True)
    a=parser.parse_args()
    result=assess(json.loads(a.report.read_bytes()),json.loads(a.protocol.read_bytes()))
    print(json.dumps(result,sort_keys=True,ensure_ascii=False))

if __name__=="__main__":
    main()
