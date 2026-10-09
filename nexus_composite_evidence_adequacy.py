"""Independent, fail-closed *review coverage* check for physical composite QA.

The 1,000 x 15-minute runtime replay spans only ~10.4 days; a profitable
number from that window is not sufficient *observation coverage* for a
low-turnover strategy. This gate refuses a new QA-41 work authorization until
source-bound continuous closed-bar evidence covers the preregistered 30 days.

No historical minimum closed-trade count: zero activity means evidence is
inconclusive, not that the hypothesis was disproved. Passing this narrow check
means eligibility for independent numerical QA *only*. It never establishes
statistical edge, pristine prospective/OOS performance, REG-50 admission,
Paper/Demo readiness or Live authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

SCHEMA = "nexus.composite-qa-observation-adequacy.v1"
MILLISECONDS_PER_DAY = 86_400_000
MIN_REVIEW_DAYS = 30  # Observation coverage, NOT a minimum trade-count rule.
SIM_CASH_USDT = Decimal("10000")
PROFILES = {"conservative": (Decimal("10"), Decimal("5")),
            "stress": (Decimal("25"), Decimal("15"))}
SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})
TIMEFRAMES = {"minute15": 900_000, "hour1": 3_600_000, "hour4": 14_400_000}


class CompositeObservationError(ValueError):
    """Invalid independent accounting or source-binding evidence."""


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise CompositeObservationError(f"{name} must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CompositeObservationError(f"{name} is malformed") from exc
    if not number.is_finite():
        raise CompositeObservationError(f"{name} must be finite")
    return number


def _window(dataset: Mapping[str, Any], timeframe: str) -> int:
    if not isinstance(dataset, Mapping) or dataset.get("timeframe") != timeframe:
        raise CompositeObservationError("timeframe source binding missing")
    count = dataset.get("row_count")
    start, last = dataset.get("first_open_time_ms"), dataset.get("last_open_time_ms")
    if (
        type(count) is not int or type(start) is not int or type(last) is not int
        or count < 2 or start < 0 or last <= start
        or (last - start) != (count - 1) * TIMEFRAMES[timeframe]
    ):
        raise CompositeObservationError("noncontiguous or dishonest observed candle window")
    return count * TIMEFRAMES[timeframe]


def _profile(profile: Mapping[str, Any]) -> tuple[str, int]:
    if not isinstance(profile, Mapping):
        raise CompositeObservationError("missing runtime cost profile")
    kind = profile.get("profile")
    if kind not in PROFILES:
        raise CompositeObservationError("unexpected runtime cost profile")
    count = profile.get("closed_round_trips")
    if type(count) is not int or count < 0:
        raise CompositeObservationError("invalid closed-trade count")
    fee, slip = PROFILES[kind]
    if _decimal(profile.get("fee_bps"), "fee_bps") != fee or (
        _decimal(profile.get("slippage_bps"), "slippage_bps") != slip
    ):
        raise CompositeObservationError("profile does not use preregistered cost stress")
    pnl = _decimal(profile.get("net_pnl_usdt"), "net_pnl_usdt")
    percentage = _decimal(profile.get("net_return_pct"), "net_return_pct")
    # Simulated cash is isolated research capital, NOT the owner's 500 USDT.
    if abs(percentage - pnl / SIM_CASH_USDT * 100) > Decimal("0.0000002"):
        raise CompositeObservationError("independent PnL/return arithmetic mismatch")
    drawdown = _decimal(profile.get("max_drawdown_pct"), "max_drawdown_pct")
    turnover = _decimal(profile.get("turnover_usdt"), "turnover_usdt")
    exposure = _decimal(profile.get("exposure_bar_ratio"), "exposure_bar_ratio")
    if drawdown < 0 or drawdown > 100 or turnover < 0 or not 0 <= exposure <= 1:
        raise CompositeObservationError("physical risk or turnover metrics outside bounds")
    win = profile.get("win_rate_pct")
    if (count == 0 and win is not None) or (
        win is not None and not 0 <= _decimal(win, "win_rate_pct") <= 100
    ):
        raise CompositeObservationError("win-rate/count inconsistency")
    if count == 0 and (pnl != 0 or turnover != 0 or exposure != 0):
        raise CompositeObservationError("zero-trade profile fabricated execution metrics")
    if profile.get("halted_on_drawdown") is not False or profile.get("trade_count_limit") is not None:
        raise CompositeObservationError("requalification cannot admit a drawdown halt or trade cap")
    return kind, count


def assess(producer: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute observation coverage and accounting without calling the backtester.

    Intended AFTER the canonical producer's exact digest/verifier check, and
    repeated on QA task validation. Records a deterministic non-authoritative
    observation report; it never generates a candidate or Paper order.
    """
    if not isinstance(producer, Mapping):
        raise CompositeObservationError("physical requalification proof missing")
    evaluations = producer.get("evaluations")
    if not isinstance(evaluations, list) or len(evaluations) != len(SYMBOLS):
        raise CompositeObservationError("both source-bound runtime symbols required")
    window_days: dict[str, float] = {}
    activity: dict[str, int] = {}
    for row in evaluations:
        if not isinstance(row, Mapping):
            raise CompositeObservationError("runtime evaluation malformed")
        symbol = row.get("symbol")
        if symbol not in SYMBOLS or symbol in window_days:
            raise CompositeObservationError("duplicate or unsupported runtime symbol")
        datasets = row.get("datasets")
        if not isinstance(datasets, Mapping) or set(datasets) != set(TIMEFRAMES):
            raise CompositeObservationError("incomplete canonical multi-timeframe binding")
        durations = [_window(datasets[tf], tf) for tf in TIMEFRAMES]
        # All three timeframes must cover the observation interval.
        window_days[symbol] = round(min(durations) / MILLISECONDS_PER_DAY, 6)
        profiles = row.get("profiles")
        if not isinstance(profiles, list) or len(profiles) != len(PROFILES):
            raise CompositeObservationError("both cost profiles required")
        checks = dict(_profile(p) for p in profiles)
        if set(checks) != set(PROFILES):
            raise CompositeObservationError("duplicate runtime cost profile")
        # Do not double-count the same strategy's conservative/stress trades.
        activity[symbol] = checks["conservative"]
    if set(window_days) != SYMBOLS:
        raise CompositeObservationError("runtime pair set mismatch")
    if any(days < MIN_REVIEW_DAYS for days in window_days.values()):
        state, reason = "INCONCLUSIVE", "INSUFFICIENT_OBSERVATION_COVERAGE"
    elif not any(activity.values()):
        state, reason = "INCONCLUSIVE", "NO_CLOSED_TRADES_IN_OBSERVED_WINDOW"
    else:
        state, reason = "READY_FOR_INDEPENDENT_QA_ONLY", "OBSERVATION_AND_ARITHMETIC_SCREEN_PASSED"
    core = {
        "schema_version": SCHEMA,
        "decision": state,
        "reason_codes": [reason],
        "min_observation_days": MIN_REVIEW_DAYS,
        "actual_contiguous_window_days": window_days,
        "conservative_closed_trades_by_symbol": activity,
        "historical_minimum_trade_count": None,
        "statistical_significance_established": False,
        "pristine_prospective_evidence_present": False,
        "owner_demo_admission_allowed": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {
        **core,
        "observation_digest": hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":"),
                       allow_nan=False).encode("utf-8")
        ).hexdigest(),
    }
