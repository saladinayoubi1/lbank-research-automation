"""Offline FX risk and protection plan compiler; no strategy signals or trading authority."""
from dataclasses import dataclass
from decimal import Decimal, Context, localcontext, ROUND_FLOOR, ROUND_CEILING
from typing import Optional
from nexus_fx_quote_research import _amount, _name, _require
from nexus_fx_cost_research import CostProfile, _scenario_terms
from nexus_fx_entry_lifecycle_research import EntryLifecycle, model_entry_lifecycle
from nexus_fx_protection_research import Target, ExitPolicy, NextBarStopMove, model_protection


@dataclass(frozen=True)
class RiskBudget:
    equity: Decimal
    fraction: Decimal
    currency: str

    def __post_init__(self):
        _amount(self.equity, "equity")
        _amount(self.fraction, "risk fraction")
        _require(self.fraction <= 1, "risk fraction exceeds equity")
        _name(self.currency)


@dataclass(frozen=True)
class TargetRule:
    r_multiple: Optional[Decimal] = None
    structural_level: Optional[Decimal] = None

    def __post_init__(self):
        _require(self.r_multiple is not None or self.structural_level is not None,
                 "explicit target rule required")
        if self.r_multiple is not None:
            _amount(self.r_multiple, "R multiple")
        if self.structural_level is not None:
            _amount(self.structural_level, "structural target")


@dataclass(frozen=True)
class EqualSplit:
    first_r: Decimal
    bar_ms: int
    anchor_ms: int

    def __post_init__(self):
        _amount(self.first_r, "first R")
        # Reuse bar-grid validation; actual stop supplied after entry pricing.
        NextBarStopMove(1, Decimal(1), self.bar_ms, self.anchor_ms)


@dataclass(frozen=True)
class PlannedTrade:
    status: str
    budget: RiskBudget
    rule: TargetRule
    split: Optional[EqualSplit]
    initial_stop: Decimal
    entry: Optional[EntryLifecycle] = None
    initial_r: Optional[Decimal] = None
    estimated_stop_risk: Optional[Decimal] = None
    targets: tuple = ()
    policy: Optional[ExitPolicy] = None
    research_only: bool = True


def compile_trade_plan(window, intent, profile, delay, budget, initial_stop, rule, *, split=None):
    """Size using the hypothetical entry and adverse stop scenario, not a loss cap.
    The preliminary minimum-lot pricing probe is never a booked entry.
    Fixed quote-currency equity only; no leverage, margin or FX conversion claim.
    R is frozen at the candidate price. Target grid rounding is conservative.
    A structural target may cap an R target; crossed geometry is rejected.
    Equal split must be exactly feasible at the sized lot, not silently resized.
    """
    _require(type(profile) is CostProfile and type(budget) is RiskBudget
             and type(rule) is TargetRule, "explicit plan inputs required")
    _require(split is None or type(split) is EqualSplit, "invalid split")
    _require(budget.currency == profile.instrument.quote_currency, "currency conversion unsupported")
    profile.instrument.price(initial_stop)
    if rule.structural_level is not None:
        profile.instrument.price(rule.structural_level)

    def reject(status):
        return PlannedTrade(status, budget, rule, split, initial_stop)

    probe = model_entry_lifecycle(window, intent, profile, profile.min_lots, delay)
    if probe.status != "HYPOTHETICAL_ENTRY":
        return reject(probe.status)
    price = probe.candidate.price
    long = intent.side == "buy"
    side = "sell" if long else "buy"
    sign = Decimal(1) if long else Decimal(-1)
    step = profile.instrument.price_step

    with localcontext(Context(prec=96)):
        r = sign * (price - initial_stop)
        if r <= 0:
            return reject("REJECT_STOP_GEOMETRY")
        def rounded(value):
            mode = ROUND_FLOOR if long else ROUND_CEILING
            return (value / step).to_integral_value(rounding=mode) * step
        levels = []
        if rule.r_multiple is not None:
            levels.append(price + sign * r * rule.r_multiple)
        if rule.structural_level is not None:
            levels.append(rule.structural_level)
        target = rounded(min(levels) if long else max(levels))
        if target <= 0 or sign * (target - price) <= 0:
            return reject("REJECT_TARGET_GEOMETRY")
        profile.instrument.price(target)
        if split is not None:
            first = rounded(price + sign * r * split.first_r)
            if first <= 0 or sign * (first - price) <= 0 or sign * (target - first) <= 0:
                return reject("REJECT_SPLIT_GEOMETRY")
            profile.instrument.price(first)
        _, adverse_stop, _, _, _ = _scenario_terms(profile, side, initial_stop, profile.min_lots)
        per_lot = sign * (price - adverse_stop) * profile.instrument.contract_size + 2 * profile.commission_per_lot
        risk_budget = budget.equity * budget.fraction
        max_steps = risk_budget // (per_lot * profile.lot_step)
        lots = min(profile.max_lots, max_steps * profile.lot_step)
        if lots < profile.min_lots:
            return reject("REJECT_INSUFFICIENT_RISK_BUDGET")
        profile.validate_lots(lots)
        if split is not None:
            half = lots / 2
            if half < profile.min_lots or half % profile.lot_step != 0:
                return reject("REJECT_UNDIVIDABLE_LOTS")
            profile.validate_lots(half)
            targets = (Target(first, half), Target(target, half))
            policy = ExitPolicy("ORDER_PRICE", NextBarStopMove(1, price, split.bar_ms, split.anchor_ms))
        else:
            targets = (Target(target, lots),)
            policy = ExitPolicy("ORDER_PRICE")
        entry = model_entry_lifecycle(window, intent, profile, lots, delay)
        _require(entry.status == "HYPOTHETICAL_ENTRY" and
                 entry.candidate.tick == probe.candidate.tick and
                 entry.candidate.price == price, "sized entry differs from pricing probe")
        estimate = per_lot * lots
        _require(estimate <= risk_budget, "risk sizing exceeds budget")
        return PlannedTrade("HYPOTHETICAL_PLAN", budget, rule, split, initial_stop,
                            entry, r, estimate, targets, policy)


def replay_plan_protection(window, plan):
    """Reject modified plan inputs/results before replaying hypothetical exits."""
    _require(type(plan) is PlannedTrade and plan.status == "HYPOTHETICAL_PLAN",
             "eligible hypothetical plan required")
    e = plan.entry
    _require(type(e) is EntryLifecycle, "entry missing")
    expected = compile_trade_plan(window, e.intent, e.profile, e.delay, plan.budget,
                                  plan.initial_stop, plan.rule, split=plan.split)
    _require(plan == expected, "plan differs from replay")
    return model_protection(window, e, plan.initial_stop, plan.targets, policy=plan.policy)
