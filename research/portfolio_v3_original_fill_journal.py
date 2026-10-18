"""Independent FIFO accounting of observable fills from the ORIGINAL portfolio v3.

This is not an alternative trading simulator and never determines fills.
The original exact_backtest emits an optional trace by its actual execution
paths. Fail closed if any trace cash, quantities, fees, P/L or drawdowns
disagree with the existing authoritative engine's result.
"""
from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import Any

import numpy as np
import pandas as pd

SCHEMA="nexus.portfolio-v3-original-execution-fifo-journal.v1"


class FillJournalError(ValueError):
    pass


def _digest(obj:Any)->str:
    return hashlib.sha256(json.dumps(
        obj,sort_keys=True,separators=(",",":"),allow_nan=False
    ).encode()).hexdigest()


def fifo_journal(
    trace:dict[str,Any],
    original_metrics:dict[str,Any],
    *,
    atol_usdt:float=2e-6,
)->dict[str,Any]:
    if (type(trace) is not dict or set(trace)!={
        "schema","initial_cash_usdt","period","symbols","fills",
        "equity_marks","terminal_cash_usdt","terminal_quantities"
    } or trace.get("schema")!="nexus.portfolio-v3-original-fill-trace.v1"
        or trace.get("symbols")!=["btc_usdt","eth_usdt"]
        or not isinstance(trace.get("fills"),list)
        or not isinstance(trace.get("equity_marks"),list)
        or not trace["equity_marks"]):
        raise FillJournalError("not an original recorded BTC/ETH Spot execution trace")
    if (not np.isfinite(atol_usdt) or not 0<atol_usdt<=1e-3):
        raise FillJournalError("invalid audit tolerance")
    starting=float(trace["initial_cash_usdt"])
    if not np.isfinite(starting) or starting<=0:
        raise FillJournalError("original cash not credible")
    cash=starting
    inventory={symbol:deque() for symbol in trace["symbols"]}
    quantities={symbol:0.0 for symbol in trace["symbols"]}
    fills=trace["fills"]
    positions=[]
    total_paid=0.0
    asset_counts={symbol:0 for symbol in trace["symbols"]}
    previous_time=None
    for n,fill in enumerate(fills):
        if (type(fill) is not dict or
            set(fill)!={"sequence","symbol","side","fill_kind",
                         "source_bar_open_utc","executed_at_utc",
                         "quantity","price_usdt","fee_usdt",
                         "cash_after_usdt","asset_quantity_after"}):
            raise FillJournalError("untrusted or altered fill record shape")
        if fill["sequence"]!=n or fill["symbol"] not in inventory or fill["side"] not in ("buy","sell"):
            raise FillJournalError("misordered or unrecognized Spot fill")
        time=pd.Timestamp(fill["executed_at_utc"])
        if time.tzinfo is None or time.utcoffset().total_seconds()!=0:
            raise FillJournalError("all fills must be physically UTC timestamped")
        if previous_time is not None and time<previous_time:
            raise FillJournalError("out-of-order original execution trace timestamps")
        previous_time=time
        if fill["fill_kind"] not in ("next_bar_open","terminal_bar_close"):
            raise FillJournalError("unexpected actual execution time class")
        q=float(fill["quantity"])
        px=float(fill["price_usdt"])
        fee=float(fill["fee_usdt"])
        if not all(np.isfinite(z) for z in (q,px,fee)) or q<=0 or px<=0 or fee<0:
            raise FillJournalError("non-physical recorded quantity, fill or cost")
        symbol=fill["symbol"]
        total_paid+=fee
        if fill["side"]=="buy":
            spent=q*px+fee
            cash-=spent
            quantities[symbol]+=q
            inventory[symbol].append({
                "qty":q,"basis":spent,
                "entry_at_utc":fill["executed_at_utc"],
                "entry_unit_fill_usdt":px,
            })
        else:
            if q>quantities[symbol]+1e-9:
                raise FillJournalError("sell exceeds real per-symbol Spot inventory")
            gross=q*px
            cash+=gross-fee
            quantities[symbol]-=q
            remaining=q
            while remaining>1e-10:
                if not inventory[symbol]:
                    raise FillJournalError("unmatched old-engine long entry lot")
                lot=inventory[symbol][0]
                amount=min(remaining,lot["qty"])
                basis=lot["basis"]*(amount/lot["qty"])
                received=(gross-fee)*(amount/q)
                allocated_fee=fee*(amount/q)
                pnl=received-basis
                positions.append({
                    "symbol":symbol,
                    "entry_at_utc":lot["entry_at_utc"],
                    "exit_at_utc":fill["executed_at_utc"],
                    "exit_kind":fill["fill_kind"],
                    "quantity":float(amount),
                    "entry_cost_with_fees_usdt":float(basis),
                    "exit_proceeds_after_fees_usdt":float(received),
                    "exit_fee_usdt":float(allocated_fee),
                    "pnl_usdt":float(pnl),
                    "is_win":bool(pnl>0),
                })
                lot["qty"]-=amount
                lot["basis"]-=basis
                remaining-=amount
                if lot["qty"]<=1e-10:
                    inventory[symbol].popleft()
            if abs(remaining)>1e-8:
                raise FillJournalError("unmatched original sell quantity")
        if cash < -atol_usdt:
            raise FillJournalError("trace breaches one shared cash account")
        if (abs(cash-float(fill["cash_after_usdt"]))>atol_usdt or
            abs(quantities[symbol]-float(fill["asset_quantity_after"]))>1e-8):
            raise FillJournalError("fill tampered: actual shared cash or asset inventory not conserved")
        asset_counts[symbol]+=1
    if (any(abs(x)>1e-8 for x in quantities.values()) or
        any(inventory[symbol] for symbol in inventory) or
        any(abs(float(q))>1e-8 for q in trace["terminal_quantities"]) or
        abs(cash-float(trace["terminal_cash_usdt"]))>atol_usdt):
        raise FillJournalError("old engine study was not flat at final liquidation")
    economic_profit=sum(row["pnl_usdt"] for row in positions)
    original_end=starting*(1+float(original_metrics["total_return"]))
    engine_fees=float(original_metrics["total_fees"])
    if (abs(cash-original_end)>atol_usdt or
        abs(economic_profit-(original_end-starting))>atol_usdt or
        abs(total_paid-engine_fees)>atol_usdt or
        len(fills)!=int(original_metrics["fill_count"]) or
        [asset_counts[s] for s in trace["symbols"]]!=original_metrics["asset_fill_counts"]):
        raise FillJournalError("independent FIFO ledger does not match authoritative original portfolio metrics")
    marks=trace["equity_marks"]
    values=np.array([float(row["equity_usdt"]) for row in marks],dtype=float)
    if (not np.isfinite(values).all() or (values<=0).any()
        or abs(values[-1]-cash)>atol_usdt
        or len(marks)<3):
        raise FillJournalError("invalid original 4h mark-to-market equity tape")
    dd=float(1-np.min(values/np.maximum.accumulate(values)))
    if abs(dd-float(original_metrics["max_drawdown"]))>1e-9:
        raise FillJournalError("actual original max drawdown not reconciled")
    monthly={}
    for p in positions:
        month=p["exit_at_utc"][:7]
        r=monthly.setdefault(month,{"fifo_matched_lot_segments":0,
                                      "net_pnl_usdt":0.0,"winning_segments":0})
        r["fifo_matched_lot_segments"]+=1
        r["net_pnl_usdt"]+=p["pnl_usdt"]
        r["winning_segments"]+=int(p["is_win"])
    for row in monthly.values():
        row["net_pnl_usdt"]=round(row["net_pnl_usdt"],8)
    result={
        "schema":SCHEMA,
        "accounting_method":"ACTUAL_ORIGINAL_EXECUTION_FILLS_FIFO_MATCHED_LOT_SEGMENTS",
        "this_is_not_a_new_fill_simulator":True,
        "original_engine_unchanged_when_trace_not_requested":True,
        "symbols":list(trace["symbols"]),
        "study_period":dict(trace["period"]),
        "initial_cash_usdt":starting,
        "terminal_cash_usdt":cash,
        "net_profit_usdt":economic_profit,
        "mean_net_pnl_per_fifo_matched_segment_usdt":
            economic_profit/len(positions) if positions else None,
        "closed_fifo_lot_segments":len(positions),
        "winning_fifo_lot_segments":sum(int(x["is_win"]) for x in positions),
        "exact_original_buy_sell_fill_events":len(fills),
        "btc_fill_events":asset_counts["btc_usdt"],
        "eth_fill_events":asset_counts["eth_usdt"],
        "total_fees_usdt":total_paid,
        "observed_max_drawdown_pct":100*dd,
        "monthly_by_fifo_exit_month":monthly,
        "fills":fills,
        "closed_fifo_lot_journal":positions,
        "equity_marks":marks,
        "per_trade_hard_stop_present":False,
        "gap_risk_bounded":False,
        "independent_future_OOS":False,
        "paper_eligible":False,
        "automatic_demo_promotion":False,
        "live_enabled":False,
        "real_orders":0,
    }
    result["digest"]=_digest(result)
    return result
