"""V24 Elliott entry/exit integrity audit — RESEARCH ONLY.

Independent ledger and bracket audit of the frozen V17 prospective study.
Does not change V17 rules, use hindsight to retune stops/targets, confirm
recursive Elliott counts, verify externally supplied pivot/source booleans,
place orders, or promote Paper/Demo/Live. Synthetic testing ONLY until a
separately authenticated future-source adapter qualifies closed Bybit data.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from typing import Mapping, Sequence

from nexus_elliott_prospective_exit_v17 import (
    CANDLE_MINUTES, MAX_HOLD_BARS, MAX_REWARD_RISK, MAX_POSITION_FRACTION,
    MAX_STOP_RISK_FRACTION, PROFILES, REFERENCE_CELL_CASH, _decimal,
    _utc_aligned, _validated_bars, evaluate_prospective_study,
)

RESEARCH_ONLY = True
LIVE_ENABLED = False
AUTO_DEMO = False
PAPER_ELIGIBLE = False
CAN_PLACE_ORDER = False
TUNES_ENTRY_EXIT_USING_HISTORICAL_PNL = False
RECURSIVE_ELLIOTT_COUNT_PROVEN = False
COST_PROFILES_FROZEN = tuple(PROFILES)


def _must_equal_money(value: object, expected: Decimal, field: str) -> None:
    try:
        actual = Decimal(str(value))
    except Exception as exc:
        raise ValueError("independent ledger mismatch: " + field) from exc
    if not actual.is_finite() or abs(actual - expected) > Decimal("1e-35"):
        raise ValueError("independent ledger mismatch: " + field)


def audit_single(
    observation: Mapping[str, object],
    closed_future_bars: Sequence[Mapping[str, object]],
    *, profile: str, observed_at_utc: datetime,
    supplied_v17_receipt: Mapping[str, object] | None = None,
) -> dict:
    """Check source chronology, entry boundary, fills, exits and ledger.

    Quarantine warnings do not rewrite, delete or favorably rescore the V17
    outcome. Full provider authenticity and recursiveness are separate gates.
    """
    v17 = evaluate_prospective_study(
        observation, closed_future_bars, profile=profile,
        observed_at_utc=observed_at_utc,
    )
    if supplied_v17_receipt is not None:
        if not isinstance(supplied_v17_receipt, Mapping) or dict(supplied_v17_receipt) != v17:
            raise ValueError("submitted V17 receipt differs from canonical computation")
    decision = _utc_aligned(observation["decision_close_utc"], "decision")
    seen = _utc_aligned(observed_at_utc, "observed_at_utc")
    bars, source_digest = _validated_bars(closed_future_bars, decision, seen)
    if source_digest != v17["future_closed_bar_sha256"]:
        raise ValueError("future OHLC digest mismatch")
    first_open = Decimal(bars[0]["open"])
    fifth_high = _decimal(observation["fifth_high"], "fifth high")
    correction = _decimal(observation["correction_low"], "correction low")
    signal_close = _decimal(observation["decision_close"], "signal close")
    problems = ["EXTERNAL_BYBIT_AND_PIVOT_PROVENANCE_NOT_REVERIFIED",
                "FULL_RECURSIVE_ELLIOTT_5_3_5_3_5_NOT_CERTIFIED"]
    if v17.get("source_bound_claim_from_caller_not_reverified") is not True or (
        v17.get("complete_recursive_elliott_count") is not False
    ) or v17.get("real_broker_fill_verified") is not False:
        raise ValueError("unexpected source/fill/recursive authority claim")
    if first_open <= correction:
        if v17["status"] != "NO_ENTRY_OPEN_AT_OR_BELOW_CORRECTION" or (
            v17["filled"] is not False or v17["net_pnl"] is not None
        ):
            raise ValueError("structural stop invalidation misclassified")
        problems.append("NEXT_OPEN_INVALIDATES_CORRECTION_STOP_NO_ENTRY")
    elif first_open <= fifth_high:
        # The previous bar closed beyond the high, but the very first next
        # open has already fallen back below/equal to breakout: do not
        # silently treat this as a pristine breakout.
        problems.append("NEXT_OPEN_REENTERED_PRE_BREAKOUT_RANGE")
    with localcontext() as ctx:
        ctx.prec = 46
        if first_open > correction:
            friction = PROFILES[profile]
            fee = friction["fee_bps"] / Decimal("10000")
            slip = friction["slip_bps"] / Decimal("10000")
            entry = first_open * (1 + slip)
            risk_per_unit = entry - correction
            target = entry + MAX_REWARD_RISK * risk_per_unit
            quantity = min(
                REFERENCE_CELL_CASH * MAX_STOP_RISK_FRACTION / risk_per_unit,
                REFERENCE_CELL_CASH * MAX_POSITION_FRACTION / (entry * (1 + fee)),
            )
            if not v17["filled"]:
                raise ValueError("eligible next-open was not filled by V17 model")
            for field, expected in (
                ("entry_reference", first_open), ("entry", entry),
                ("structural_stop", correction), ("target", target),
                ("quantity", quantity),
            ):
                _must_equal_money(v17[field], expected, field)
            if quantity * risk_per_unit > (
                REFERENCE_CELL_CASH * MAX_STOP_RISK_FRACTION + Decimal("1e-35")
            ):
                raise ValueError("nominal stop-risk cap violated")
            if quantity * entry * (1 + fee) > (
                REFERENCE_CELL_CASH * MAX_POSITION_FRACTION + Decimal("1e-35")
            ):
                raise ValueError("reference notional cap violated")
            independent = None
            for index, b in enumerate(bars):
                op, high, low, close = (
                    Decimal(b[k]) for k in ("open", "high", "low", "close")
                )
                if low <= correction:
                    reference = min(op, correction)
                    why = "stop"
                    both = high >= target
                    if index == 0:
                        problems.append("STOP_TOUCHED_INSIDE_ENTRY_CANDLE_ORDER_UNOBSERVED")
                    if op < correction:
                        problems.append("STOP_GAP_OPEN_WORSE_THAN_STRUCTURAL_LEVEL")
                    if both:
                        problems.append("BOTH_STOP_AND_TARGET_INSIDE_CANDLE_STOP_FIRST")
                elif high >= target:
                    reference = target
                    why = "target"
                    both = False
                    if op > target:
                        problems.append("FAVORABLE_GAP_PROFIT_CAPPED_AT_TARGET")
                elif index == MAX_HOLD_BARS - 1:
                    reference = close
                    why = "time_limit"
                    both = False
                    problems.append("TIME_LIMIT_EXIT_AT_LAST_CLOSED_BAR")
                else:
                    continue
                exit_price = reference * (1 - slip)
                entry_fee = quantity * entry * fee
                exit_fee = quantity * exit_price * fee
                net = quantity * (exit_price - entry) - entry_fee - exit_fee
                independent = (index, why, both, reference, exit_price,
                               entry_fee, exit_fee, net)
                break
            if independent is None:
                if (v17["status"] != "AWAITING_MORE_CLOSED_BARS" or
                    v17.get("net_pnl") is not None or
                    v17.get("exit_reason") is not None):
                    raise ValueError("pending outcome was fabricated")
                problems.append("NO_FULLY_OBSERVED_EXIT_PENDING_NOT_ZERO_PNL")
            else:
                index, why, both, ref, exit_px, entry_fee, exit_fee, net = independent
                if (v17["status"] != "EXITED" or v17.get("exit_reason") != why or
                    v17.get("exit_bar_index_after_entry") != index or
                    v17.get("both_levels_touched_stop_first") is not both or
                    v17.get("exit_close_utc") != (
                        decision + timedelta(minutes=(index + 1) * CANDLE_MINUTES)
                    ).isoformat()):
                    raise ValueError("independently checked stop/target/time ordering differs")
                for field, expected in (
                    ("exit_reference", ref), ("exit_price", exit_px),
                    ("entry_fee", entry_fee), ("exit_fee", exit_fee),
                    ("net_pnl", net),
                ):
                    _must_equal_money(v17[field], expected, field)
                if why == "stop" and net >= 0:
                    raise ValueError("stop exit incorrectly reported as profitable")
        elif v17.get("net_pnl") is not None:
            raise ValueError("unfilled event cannot claim PNL")
    # No net aggregation for uncertain/pending events. Do not opportunistically
    # exclude loss-making warning events when reporting frozen strategy PNL.
    return {
        "schema": "nexus.elliott-v24-entry-exit-audit.v1",
        "symbol": v17["symbol"], "event_id": v17["event_id"],
        "profile": profile,
        "decision_close_utc": v17["decision_close_utc"],
        "future_closed_bar_sha256": v17["future_closed_bar_sha256"],
        "source_market_authenticity_verified_here": False,
        "full_recursive_wave_count_verified_here": False,
        "real_broker_fill_verified": False,
        "audit_status": "RESEARCH_QUARANTINED_NO_PROMOTION",
        "v17_hypothetical_status_unmodified": v17["status"],
        "v17_hypothetical_net_pnl_unmodified": v17.get("net_pnl"),
        "v17_hypothetical_exit_reason_unmodified": v17.get("exit_reason"),
        "warning_codes": sorted(set(problems)),
        "next_open_minus_signal_close": str(first_open - signal_close),
        "next_open_minus_breakout_high": str(first_open - fifth_high),
        # Fixed price-only gate for a FUTURE strategy design, not an edit
        # of V17's registered hypothetical fill or historical winner set.
        "prospective_price_path_entry_gate_passed": (
            first_open > fifth_high and first_open > correction
        ),
        "candidate_for_paper_or_live_even_if_gate_passed": False,
        "model_fill_must_not_be_interpreted_as_authorized_entry": True,
        "entry_model_validated": True,
        "exit_model_validated": True,
        "friction_reconciled": True,
        "historical_parameter_optimization": False,
        "research_only": True, "live_enabled": False, "auto_demo": False,
        "paper_eligible": False, "entry_signal": False,
        "orders_placed": 0,
    }


def audit_unique_batch(events: Sequence[Mapping[str, object]]) -> list[dict]:
    """Reject duplicate source events and decisions before double-counting PNL."""
    if not isinstance(events, (list, tuple)):
        raise ValueError("events must be a sequence")
    seen_ids = set()
    seen_decisions = set()
    reports = []
    for request in events:
        if not isinstance(request, Mapping):
            raise ValueError("event request must be a mapping")
        obs = request["observation"]
        profile = request["profile"]
        symbol = obs["symbol"]
        identity = (symbol, obs["event_id"], profile)
        decision = (symbol, _utc_aligned(obs["decision_close_utc"], "decision"), profile)
        if identity in seen_ids or decision in seen_decisions:
            raise ValueError("duplicate Elliott event or decision within friction profile")
        seen_ids.add(identity)
        seen_decisions.add(decision)
        reports.append(audit_single(
            obs, request["closed_future_bars"],
            profile=profile, observed_at_utc=request["observed_at_utc"],
            supplied_v17_receipt=request.get("supplied_v17_receipt"),
        ))
    return reports
