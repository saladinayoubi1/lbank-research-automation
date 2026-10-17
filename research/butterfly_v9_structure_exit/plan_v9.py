"""Butterfly V9: pre-registered *hypothetical* structural entry/exit plan.

NO orders, no Paper, no historical return claims and NO replacement of V8.
Only right-confirmed causal XABCD geometry; the close-time decision cannot
access next bar OPEN. A separate subsequent adapter can model this OPEN,
including adverse execution costs, but never transmit an order.
"""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
import math
from typing import Any, Sequence

from nexus_causal_butterfly_features import (
    ConfirmedPivot, bullish_butterfly_geometry,
)

SCHEMA = "nexus.butterfly-v9-structural-execution-plan.v1"
EXACT_ORDERS = 0
RESEARCH_ONLY = True
LIVE_ENABLED = False
PAPER_ELIGIBLE = False
SPOT_LONG_ONLY = True
OWNER_PAPER_UNCHANGED = True

# FIXED before testing new physical market data, not selected on past returns.
PRZ_STOP_XA_MULT = Decimal("1.414")
FIRST_TARGET_CD_RETRACE = Decimal("0.382")
SIMULATED_CASH = Decimal("500")
MAX_ALLOCATION_FRACTION = Decimal("0.10")
NOMINAL_RISK_BUDGET_FRACTION = Decimal("0.005")
# Match old conservative/stress assumptions, evaluated per side.
COST_PROFILES = {
    "conservative": (Decimal("10"), Decimal("5")),
    "stress": (Decimal("25"), Decimal("15")),
}


class StructuralPlanError(ValueError):
    pass


def _money(v: Decimal) -> str:
    return format(v.quantize(Decimal("0.00000001")), "f")


def digest(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()).hexdigest()


def _positive(v: float | int | str | Decimal) -> Decimal:
    if isinstance(v, bool):
        raise StructuralPlanError("boolean is not physical price")
    try:
        number = Decimal(str(v))
    except Exception as exc:
        raise StructuralPlanError("invalid price") from exc
    if not number.is_finite() or number <= 0:
        raise StructuralPlanError("nonfinite or nonpositive physical price")
    return number


def close_time_plan(
    pivots: Sequence[ConfirmedPivot],
    *,
    closed_bar_index: int,
    closed_open: float,
    closed_close: float,
    previous_close: float,
    independently_closed_h1_vol_ok: bool,
    h1_context_last_closed_15m_index: int,
) -> dict[str, Any]:
    """Observe right-confirmed D only once, one closed bar after D confirmation.

    Never use the next open or later OHLC to decide whether an entry is allowed.
    Does not claim that a pattern predicts profit or authentic Elliott structure.
    """
    if not isinstance(independently_closed_h1_vol_ok, bool):
        raise StructuralPlanError("higher timeframe context must be explicit")
    # Index zero is anchored to a UTC hour boundary in an independently
    # verified contiguous 15m source grid; the H1 candle including the
    # decision bar is never allowed unless it is fully closed at decision.
    if (type(closed_bar_index) is not int or closed_bar_index < 4
            or type(h1_context_last_closed_15m_index) is not int
            or h1_context_last_closed_15m_index != ((closed_bar_index + 1) // 4) * 4 - 1):
        raise StructuralPlanError("future, stale or partial one-hour context")
    if (
        type(closed_bar_index) is not int or closed_bar_index < 0
        or not isinstance(pivots, Sequence) or len(pivots) != 5
        or any(not isinstance(p, ConfirmedPivot) for p in pivots)
        or pivots[-1].confirmed_at + 1 != closed_bar_index
        or any(p.confirmed_at > pivots[-1].confirmed_at for p in pivots)
    ):
        raise StructuralPlanError("D confirmation or closed-bar timing violated")
    geometry = bullish_butterfly_geometry(pivots)
    if geometry is None:
        raise StructuralPlanError("not a frozen valid causally confirmed Butterfly")
    open_c = _positive(closed_open)
    close_c = _positive(closed_close)
    prev_c = _positive(previous_close)
    d = _positive(pivots[-1].price)
    a = _positive(pivots[1].price)
    c = _positive(pivots[3].price)
    xa = _positive(geometry["xa_size"])
    if not a > c > d:
        raise StructuralPlanError("harmonic leg order invalid")
    # Structural invalidation is at A-1.414*XA, NOT ATR or stop hindsight.
    stop = a - PRZ_STOP_XA_MULT * xa
    target = d + FIRST_TARGET_CD_RETRACE * (c - d)
    if stop <= 0 or not stop < d < target:
        raise StructuralPlanError("structural stop/target geometry invalid")
    trigger = (
        independently_closed_h1_vol_ok
        and close_c > open_c and close_c > prev_c
        and close_c >= _positive(geometry["rebound_price"])
    )
    core = {
        "schema": SCHEMA,
        "status": "CLOSED_BAR_PRECONDITIONS_PASS_NO_ORDER" if trigger else
            "CLOSED_BAR_REJECT_NO_ORDER",
        "candidate_pivot_indices": [int(p.index) for p in pivots],
        "D_right_confirmation_index": pivots[-1].confirmed_at,
        "decision_closed_bar_index": closed_bar_index,
        "allowed_hypothetical_next_open_index": closed_bar_index + 1,
        "h1_vol_context_closed": independently_closed_h1_vol_ok,
        "h1_context_last_closed_15m_index": h1_context_last_closed_15m_index,
        "input_grid_utc_hour_origin_required": True,
        "closed_candle_reversal_confirmation": trigger,
        "stop_structural_1p414_XA": _money(stop),
        "target_first_0p382_CD": _money(target),
        "D_price": _money(d),
        "risk_is_not_guaranteed_against_gaps": True,
        "historical_novelty_not_certified": True,
        "independent_future_OOS_not_present": True,
        "qualifies_for_demo": False,
        "live_enabled": False,
        "order_enabled": False,
    }
    return {**core, "plan_digest": digest(core)}


def hypothetical_next_open(
    plan: dict[str, Any],
    *,
    observed_bar_index: int,
    observed_open: float,
    cost_profile: str,
) -> dict[str, Any]:
    """Separately consume NEXT open, then veto structural gaps/bad reward.

    Estimates synthetic next-open exposure; NOT a market order, realized exit
    fill, or guaranteed risk limit when a real stop gaps through.
    """
    unsigned = {k: v for k, v in plan.items() if k != "plan_digest"}
    if (
        plan.get("plan_digest") != digest(unsigned)
        or plan.get("schema") != SCHEMA
        or plan.get("order_enabled") is not False
        or plan.get("live_enabled") is not False
        or type(observed_bar_index) is not int
        or observed_bar_index != plan.get("allowed_hypothetical_next_open_index")
        or cost_profile not in COST_PROFILES
    ):
        raise StructuralPlanError("forged or stale research-only decision")
    physical_open = _positive(observed_open)
    stop = _positive(plan["stop_structural_1p414_XA"])
    target = _positive(plan["target_first_0p382_CD"])
    fee_bps, slip_bps = COST_PROFILES[cost_profile]
    fee = fee_bps / Decimal("10000")
    slip = slip_bps / Decimal("10000")
    entry = physical_open * (Decimal(1) + slip)
    # Conservative exit estimates, actual stop gap can fill much worse.
    exit_stop = stop * (Decimal(1) - slip)
    exit_target = target * (Decimal(1) - slip)
    costed_entry_unit = entry * (Decimal(1) + fee)
    net_target_unit = exit_target * (Decimal(1) - fee)
    net_stop_unit = exit_stop * (Decimal(1) - fee)
    eligible = (
        plan.get("status") == "CLOSED_BAR_PRECONDITIONS_PASS_NO_ORDER"
        and physical_open > stop and physical_open < target
        and net_target_unit > costed_entry_unit
        and costed_entry_unit > net_stop_unit
    )
    qty = Decimal(0)
    if eligible:
        qty = min(
            (SIMULATED_CASH * MAX_ALLOCATION_FRACTION) / costed_entry_unit,
            (SIMULATED_CASH * NOMINAL_RISK_BUDGET_FRACTION)
            / (costed_entry_unit - net_stop_unit),
        )
        eligible = qty > 0 and (qty * costed_entry_unit <= SIMULATED_CASH)
    core = {
        "schema": "nexus.butterfly-v9-hypothetical-next-open.v1",
        "linked_closed_plan_digest": plan["plan_digest"],
        "cost_profile": cost_profile,
        "observed_first_postdecision_open_index": observed_bar_index,
        "status": "COST_AWARE_HYPOTHETICAL_ONLY_NO_ORDER" if eligible else
            "INADMISSIBLE_NEXT_OPEN_OR_COSTS_NO_ORDER",
        "estimated_buy_fill": _money(entry),
        "estimated_stop_sell_fill_not_gap_guarantee": _money(exit_stop),
        "estimated_target_sell_fill": _money(exit_target),
        "hypothetical_quantity": _money(qty),
        "hypothetical_buy_cash_spend": _money(qty * costed_entry_unit),
        "hypothetical_nominal_stop_loss_usdt": _money(qty * (costed_entry_unit - net_stop_unit)),
        "hypothetical_net_target_gain_usdt": _money(qty * (net_target_unit - costed_entry_unit)),
        "future_physical_exit_outcome_known": False,
        "new_market_order": False,
        "paper_eligible": False,
        "live_enabled": False,
    }
    return {**core, "receipt_digest": digest(core)}


def frozen_rulebook() -> dict[str, Any]:
    core = {
        "schema": SCHEMA,
        "source":"HarmonicTrader PRZ/1.414 XA structural invalidation, 0.382 CD first retracement",
        "PRZ_stop_XA_projection": str(PRZ_STOP_XA_MULT),
        "CD_first_target_retracement": str(FIRST_TARGET_CD_RETRACE),
        "cash_reference_usdt": str(SIMULATED_CASH),
        "max_cash_allocation_fraction": str(MAX_ALLOCATION_FRACTION),
        "max_nominal_stop_risk_fraction": str(NOMINAL_RISK_BUDGET_FRACTION),
        "fee_slippage_bps_profiles": {
            key: [str(f), str(s)] for key, (f, s) in COST_PROFILES.items()
        },
        "cannot_observe_next_open_in_close_signal": True,
        "no_unseen_market_data_used_for_selection": True,
        "not_a_backtest_or_measured_profit": True,
        "no_orders": True,
        "no_automatic_demo_promotion": True,
        "live_enabled": False,
        "frozen_V8_not_modified": True,
        "frozen_Elliott_V117_not_modified": True,
    }
    return {**core, "contract_digest": digest(core)}
