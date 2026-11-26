"""NEXUS research-only delayed entry scenario; no broker, actual fill or ledger."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
from nexus_fx_quote_research import EntryIntent, Observation, Tick, observe_entry, _require, _integer
from nexus_fx_cost_research import CostProfile, _validate_profile_binding, _scenario_terms, _limit_allows


@dataclass(frozen=True)
class DelayPolicy:
    """Explicit contact-to-candidate delay in milliseconds; strict later time."""
    latency_ms: int

    def __post_init__(self):
        _integer(self.latency_ms, "latency")
        _require(self.latency_ms <= 86_400_000, "latency exceeds bounded research policy")


@dataclass(frozen=True)
class HypotheticalEntry:
    tick: Tick
    reference_quote: Decimal
    units: Decimal
    price: Decimal
    notional: Decimal
    commission: Decimal
    slippage_cost: Decimal
    currency: str


@dataclass(frozen=True)
class EntryLifecycle:
    status: str
    window_binding: str
    intent: EntryIntent
    profile: CostProfile
    lots: Decimal
    delay: DelayPolicy
    first_contact: Observation
    candidate: Optional[HypotheticalEntry] = None
    research_only: bool = True


def model_entry_lifecycle(window, intent, profile, lots, delay):
    """Single full-quantity scenario. Trigger latches for market/stop; limit rechecks.
    Cancel/expiry wins until candidate. Strictly later than contact+latency:
    equal timestamps are conservatively excluded, even with zero latency.
    Unknown coverage stays unresolved; no market liquidity is inferred.
    """
    _require(type(intent) is EntryIntent and type(delay) is DelayPolicy, "explicit intent and delay required")
    _validate_profile_binding(window, profile, lots)
    contact = observe_entry(window, intent)
    def result(status, candidate=None):
        return EntryLifecycle(status, window.binding, intent, profile, lots, delay, contact, candidate)
    if contact.status != "ENTRY_CONTACT":
        return result(contact.status)
    ready = contact.tick.time_ms + delay.latency_ms
    _integer(ready, "delay horizon overflow")
    terminal = min(intent.expiry_ms, intent.cancel_ms if intent.cancel_ms is not None else intent.expiry_ms)
    for tick in window.ticks:
        if tick.time_ms <= ready:
            continue
        if tick.time_ms >= terminal:
            break
        q = tick.ask if intent.side == "buy" else tick.bid
        terms = _scenario_terms(profile, intent.side, q, lots)
        if not _limit_allows(intent, terms[1]):
            continue
        return result("HYPOTHETICAL_ENTRY", HypotheticalEntry(
            tick, q, *terms, profile.instrument.quote_currency))
    if terminal <= window.end_ms:
        cancelled = intent.cancel_ms is not None and intent.cancel_ms <= intent.expiry_ms
        return result("CANCELLED" if cancelled else "EXPIRED")
    return result("UNRESOLVED_COVERAGE")
