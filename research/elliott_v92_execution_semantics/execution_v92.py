"""V92 offline synthetic execution semantics and V91-denied case audit.

This module is NEVER an order adapter or trading signal. Synthetic scenarios
probe fill/cost/timestamp pitfalls independently of the July historical sample.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(r"E:\NEXUS-QA\elliott-v92-synthetic-fill-gate-20261017")
REPO = Path(__file__).resolve().parents[2]
V91_REL = "docs/evidence/elliott-v91-nested-impulse-gate-20261017/V91_NESTED_ENTRY_EXIT_GATE.json"
V91_SHA = "d4401a5606dee6a0842d1ee3752375dc95de732b9189eb3e65983640ec1715c0"
V91_COMMIT = "1fa94b9432be9d13782f3f76c0bb48737c3bc445"
MINUTE_MS = 60000

RESEARCH_ONLY = True
LIVE_ENABLED = False
PAPER_ELIGIBLE = False
ENTRY_SIGNAL = False
V52_UNCHANGED = True
ORDER_CONNECTOR = None
SYNTHETIC_ONLY = True


def d(value: object) -> Decimal:
    if isinstance(value, (bool,float)):
        raise ValueError("binary-float or boolean price rejected")
    try:
        x=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError) as exc:
        raise ValueError("invalid fixed-point numeric input") from exc
    if not x.is_finite():
        raise ValueError("nonfinite fixed-point numeric input")
    return x


@dataclass(frozen=True)
class Candle:
    open_ms: int
    op: Decimal
    hi: Decimal
    lo: Decimal
    cl: Decimal


@dataclass(frozen=True)
class DiagnosticPlan:
    side: str
    quantity: Decimal
    stop: Decimal
    target: Decimal
    fee_bps_per_side: Decimal
    spread_bps_full: Decimal
    adverse_slippage_bps_per_side: Decimal
    max_gross_notional: Decimal
    max_nominal_risk_including_fees: Decimal


def _check_candle(c: Candle) -> None:
    if type(c) is not Candle or type(c.open_ms) is not int or c.open_ms%MINUTE_MS:
        raise ValueError("closed UTC one-minute candle required")
    if not all(type(x) is Decimal and x.is_finite() for x in (c.op,c.hi,c.lo,c.cl)):
        raise ValueError("typed finite Decimal OHLC required")
    if c.lo<=0 or not c.lo<=c.op<=c.hi or not c.lo<=c.cl<=c.hi:
        raise ValueError("invalid physical 1m OHLC")


def _check_plan(plan: DiagnosticPlan, entered_at: Decimal) -> None:
    if type(plan) is not DiagnosticPlan or plan.side not in ("long","short"):
        raise ValueError("typed long/short diagnostic only")
    fields=(plan.quantity,plan.stop,plan.target,plan.fee_bps_per_side,
            plan.spread_bps_full,plan.adverse_slippage_bps_per_side,
            plan.max_gross_notional,plan.max_nominal_risk_including_fees)
    if any(type(x) is not Decimal or not x.is_finite() for x in fields):
        raise ValueError("all fixed-point parameters must be finite Decimal")
    if any(x<=0 for x in (plan.quantity,plan.stop,plan.target,
                         plan.max_gross_notional,plan.max_nominal_risk_including_fees)):
        raise ValueError("positive diagnostic size, prices and limits required")
    if any(x<0 or x>=Decimal("10000")
           for x in (plan.fee_bps_per_side,plan.spread_bps_full,
                     plan.adverse_slippage_bps_per_side)):
        raise ValueError("invalid or negative fee/spread/slippage bps")
    if (plan.spread_bps_full/Decimal("2")+
            plan.adverse_slippage_bps_per_side)>=Decimal("10000"):
        raise ValueError("combined adverse friction cannot cross full price")
    if (plan.side=="long" and not plan.stop<entered_at<plan.target) or (
        plan.side=="short" and not plan.target<entered_at<plan.stop):
        raise ValueError("precommitted exit sides inconsistent with next-bar open")


def _adverse(price: Decimal,side: str,entry: bool,plan: DiagnosticPlan) -> Decimal:
    # Mid-price synthetic inputs: charge half the bid/ask spread each side,
    # plus explicit adverse execution slippage. Fee is separate.
    halfspread=plan.spread_bps_full/Decimal("2")
    friction=(halfspread+plan.adverse_slippage_bps_per_side)/Decimal("10000")
    is_buy=(side=="long")==entry
    return price*(Decimal("1")+friction if is_buy else Decimal("1")-friction)


def _costed_result(side: str,qty: Decimal,entry_fill: Decimal,
                   exit_fill: Decimal,plan: DiagnosticPlan,why: str) -> dict:
    direction=Decimal("1") if side=="long" else Decimal("-1")
    gross=(exit_fill-entry_fill)*qty*direction
    fee=(entry_fill+exit_fill)*qty*plan.fee_bps_per_side/Decimal("10000")
    return {
        "synthetic_only":True,"classification":why,
        "entry_fill":str(entry_fill),"exit_fill":str(exit_fill),
        "gross_usdt":str(gross),"fees_usdt":str(fee),
        "illustrative_net_usdt":str(gross-fee),
        "not_historical_pnl":True,
        "paper_eligible":False,"new_order":False,"live_enabled":False,
    }


def hypothetical_entry_after_confirmation(
        confirmed_close_ms: int, entry_bar: Candle, plan: DiagnosticPlan,
        closed_through_ms: int) -> dict:
    """Offline-only single-bounded-minute probe. No source trade authorization.

    Market-order fill is modeled as adverse opening-mid plus spread/slip.
    If entry candle touches stop and target: pessimistic stop, never target.
    If neither exit occurs: unresolved, not a realized profitable trade.
    """
    if (type(confirmed_close_ms) is not int or
            confirmed_close_ms%MINUTE_MS or confirmed_close_ms<0):
        raise ValueError("physical right-confirmed minute close required")
    _check_candle(entry_bar)
    if entry_bar.open_ms!=confirmed_close_ms:
        raise ValueError("entry must be the immediate first post-confirmation minute")
    if (type(closed_through_ms) is not int or
            closed_through_ms<entry_bar.open_ms+MINUTE_MS):
        raise ValueError("entry-bar OHLC is not yet closed and physically knowable")
    _check_plan(plan,entry_bar.op)
    entry=_adverse(entry_bar.op,plan.side,True,plan)
    if entry<=0:
        raise ValueError("invalid entry fill from extreme adverse friction")
    notional=entry*plan.quantity
    stop_mid=plan.stop
    stop_exec=_adverse(stop_mid,plan.side,False,plan)
    est_fees=(entry+stop_exec)*plan.quantity*plan.fee_bps_per_side/Decimal("10000")
    nominal_loss=max(Decimal("0"),(entry-stop_exec)*plan.quantity*(
        Decimal("1") if plan.side=="long" else Decimal("-1")))+est_fees
    # Worst actual loss may exceed nominal risk when stop gaps: never
    # promise a fixed risk bound in real execution.
    if notional>plan.max_gross_notional:
        return {"status":"REJECT_MAX_DIAGNOSTIC_NOTIONAL",
                "new_order":False,"paper_eligible":False,"real_pnl":None}
    if nominal_loss>plan.max_nominal_risk_including_fees:
        return {"status":"REJECT_NOMINAL_STOP_RISK",
                "new_order":False,"paper_eligible":False,"real_pnl":None}
    stop_hit=(entry_bar.lo<=plan.stop if plan.side=="long"
              else entry_bar.hi>=plan.stop)
    target_hit=(entry_bar.hi>=plan.target if plan.side=="long"
                else entry_bar.lo<=plan.target)
    if stop_hit:
        outcome="SYNTHETIC_STOP_FIRST_AMBIGUOUS" if target_hit else "SYNTHETIC_STOP"
        # next entry bar open is in protective-side relative range; an
        # intrabar move may jump over stop in real market, not modeled.
        finish=_adverse(plan.stop,plan.side,False,plan)
        return {"status":"SYNTHETIC_CLOSED_WITHIN_ENTRY_BAR",
                "source_open_ms":entry_bar.open_ms,
                "nominal_risk_usdt":str(nominal_loss),
                "exit":_costed_result(plan.side,plan.quantity,entry,finish,plan,outcome),
                "real_pnl":None,"new_order":False}
    if target_hit:
        finish=_adverse(plan.target,plan.side,False,plan)
        return {"status":"SYNTHETIC_CLOSED_WITHIN_ENTRY_BAR",
                "source_open_ms":entry_bar.open_ms,
                "nominal_risk_usdt":str(nominal_loss),
                "exit":_costed_result(plan.side,plan.quantity,entry,finish,plan,
                                       "SYNTHETIC_TARGET"),
                "real_pnl":None,"new_order":False}
    return {
        "status":"SYNTHETIC_OPEN_UNRESOLVED_NO_MARK_TO_MARKET_PROFIT",
        "source_open_ms":entry_bar.open_ms,
        "nominal_risk_usdt":str(nominal_loss),
        "entry_fill":str(entry),
        "exit":None,"real_pnl":None,"paper_eligible":False,"new_order":False,
    }


def hypothetical_followup_exit(
        original_side: str, entry_fill: Decimal, qty: Decimal,
        stop: Decimal, target: Decimal, exit_bar: Candle,
        plan: DiagnosticPlan, entry_open_ms: int, closed_through_ms: int) -> dict:
    """For previously opened synthetic position: handle gap-through stops.

    Prices gap past stops: fill at worse open, not impossible stop price.
    OHLC double stop+target: stop first; never infer intrabar favorable order.
    """
    _check_candle(exit_bar)
    if (type(entry_open_ms) is not int or entry_open_ms%MINUTE_MS or
        exit_bar.open_ms!=entry_open_ms+MINUTE_MS):
        raise ValueError("synthetic followup must be the next chronological minute")
    if (type(closed_through_ms) is not int or
        closed_through_ms<exit_bar.open_ms+MINUTE_MS):
        raise ValueError("future followup OHLC must be fully closed")
    if (plan.side!=original_side or type(entry_fill) is not Decimal or
        type(qty) is not Decimal or type(stop) is not Decimal or
        type(target) is not Decimal or qty!=plan.quantity or
        stop!=plan.stop or target!=plan.target or not entry_fill.is_finite()):
        raise ValueError("untrusted prior synthetic position")
    _check_plan(plan,entry_fill)
    stop_hit=(exit_bar.lo<=stop if original_side=="long" else exit_bar.hi>=stop)
    take_hit=(exit_bar.hi>=target if original_side=="long" else exit_bar.lo<=target)
    if stop_hit:
        gap_through=(exit_bar.op<stop if original_side=="long" else exit_bar.op>stop)
        level=exit_bar.op if gap_through else stop
        reason="SYNTHETIC_STOP_GAP_AT_WORSE_OPEN" if gap_through else (
            "SYNTHETIC_STOP_FIRST_AMBIGUOUS" if take_hit else "SYNTHETIC_STOP")
    elif take_hit:
        # Favorable gap not improved: conservative target fill, rather
        # than claiming the best available OHLC point.
        level=target
        reason="SYNTHETIC_TARGET"
    else:
        return {"status":"SYNTHETIC_STILL_OPEN_NO_PNL",
                "paper_eligible":False,"real_pnl":None,"new_order":False}
    fill=_adverse(level,original_side,False,plan)
    return {"status":"SYNTHETIC_EXIT_WITNESSED",
            "exit":_costed_result(original_side,qty,entry_fill,fill,plan,reason),
            "real_pnl":None,"new_order":False}


def sealed_v91() -> dict:
    source=REPO/V91_REL
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=V91_SHA:
        raise ValueError("V91 frozen evidence mutated")
    original=subprocess.run(
        ["git","show",V91_COMMIT+":"+V91_REL],cwd=REPO,
        capture_output=True,check=True).stdout
    if original!=raw:
        raise ValueError("Git V91 immutable receipt not byte-for-byte identical")
    subprocess.run(["git","merge-base","--is-ancestor",V91_COMMIT,"HEAD"],
                   cwd=REPO,capture_output=True,check=True)
    record=json.loads(raw)
    if (record.get("schema")!="nexus.elliott-v91-causal-nested-impulse-entry-exit-gate.v1"
        or record.get("v90_committed_sha256")!=
           "1db892fcfe75699ded97151501e538d04c2fd8ae4084765c9e1cd4aa9fd4683a"):
        raise ValueError("V90/V91 source lineage broken")
    return record


def audit_denied_cases() -> dict:
    """All eight actual historical candidates remain DENY, no simulated fills."""
    old=sealed_v91()
    summaries={}
    explanations=[]
    for symbol in ("BTCUSDT","ETHUSDT"):
        candidates=old["symbols"][symbol]["cases"]
        rejected=0
        for case in candidates:
            decision=case["execution_gate"]
            inner=case["nesting"]
            if (decision.get("order_admission")!="DENY" or
                decision.get("new_entry_signal") is not False or
                decision.get("paper_eligible") is not False or
                inner.get("complete_recursive_elliott_proven") is not False):
                raise ValueError("V91 order denial unexpectedly replaced")
            asof=case["first_observable_ms"]
            if (decision["earliest_bar_open_after_confirmation_ms"]!=asof or
                decision["must_not_use_pivot_center_as_entry_time"] is not True or
                any(decision[k] is not None for k in
                    ("entry_price","protective_stop","take_profit",
                     "timeout_exit","quantity","net_pnl"))):
                raise ValueError("V91 lookahead or invented entry/exit values")
            if len(decision.get("missing_requirements",[]))!=7:
                raise ValueError("V91 gate missing expected blockers")
            rejected+=1
            explanations.append({"symbol":symbol,"asof_ms":asof,
                 "pattern_state":inner["state"],"admission":"DENY",
                 "reason_count":len(decision["missing_requirements"])})
        summaries[symbol]={"total_candidates":len(candidates),
                          "denied":rejected,"admitted":0,
                          "illustrative_fill_count":0,"real_pnl":None}
    if (summaries["BTCUSDT"]["total_candidates"]!=6 or
        summaries["ETHUSDT"]["total_candidates"]!=2):
        raise ValueError("frozen V91 population changed")
    report={
        "schema":"nexus.elliott-v92-synthetic-execution-contract-v1",
        "created_utc":datetime.now(timezone.utc).isoformat(),
        "v91_immutable_source_sha256":V91_SHA,"v91_prior_commit":V91_COMMIT,
        "history_used":"V91 locked structural admissions only, no OHLC replay",
        "synthetic_fill_math_checked_in_tests_only":True,
        "no_symbol_risk_or_fee_parameters_optimized":True,
        "no_real_trade_backtest":True,
        "v52_unchanged":True,
        "data_is_historical_not_prospective":True,
        "research_only":True,"live_enabled":False,"paper_eligible":False,
        "new_entry_signals":0,"orders":0,"real_pnl":None,
        "sources":summaries,"denied_cases":explanations,
        "remaining_unverified_requirements":[
           "independently verified multi-degree recursive structure",
           "unambiguous market source ordering and wave degree context",
           "precommitted post-confirmation entry trigger with physical candle",
           "protective stop and strategy invalidation",
           "time and target exit semantics with gap/SL-TP worst-first handling",
           "Bybit Demo market spread/slippage/fee and actual fills",
           "prospective risk controls and held-out net trade validation",
        ],
        "deployed_to_demo_runner":False,
    }
    ROOT.mkdir(parents=True,exist_ok=True)
    output=ROOT/"V92_EXECUTION_CONTRACT_AUDIT.json"
    encoded=(json.dumps(report,sort_keys=True,indent=2)+"\n").encode("utf8")
    if output.exists():
        previous=json.loads(output.read_bytes())
        prior=json.loads(encoded)
        previous.pop("created_utc",None)
        prior.pop("created_utc",None)
        if previous!=prior:
            raise ValueError("previous V92 result differs; no outcome overwrite")
        encoded=output.read_bytes()
    else:
        output.write_bytes(encoded)
    print(json.dumps({
        "stage":"V92","sha256":hashlib.sha256(encoded).hexdigest(),
        "cases":summaries,"entry_allowed":False,
        "synthetic_only":True,"source_provenance":V91_SHA,
    },indent=2))
    return report


if __name__=="__main__":
    audit_denied_cases()
