"""Offline NEXUS FX protective exit scenarios. No actual fills or wallet authority."""
from dataclasses import dataclass
from decimal import Decimal, Context, localcontext
from nexus_fx_quote_research import Tick, _require
from nexus_fx_cost_research import _scenario_terms
from nexus_fx_entry_lifecycle_research import EntryLifecycle, model_entry_lifecycle


@dataclass(frozen=True)
class Target:
    price: Decimal
    lots: Decimal


@dataclass(frozen=True)
class ExitScenario:
    reason: str
    tick: Tick
    lots: Decimal
    reference_quote: Decimal
    price: Decimal
    commission: Decimal
    slippage_cost: Decimal
    gross_pnl: Decimal
    allocated_entry_commission: Decimal
    net_pnl: Decimal


@dataclass(frozen=True)
class ProtectionScenario:
    status: str
    entry: EntryLifecycle
    stop: Decimal
    targets: tuple
    exits: tuple
    remaining_lots: Decimal
    gross_closed_pnl: Decimal
    net_closed_pnl: Decimal
    currency: str
    research_only: bool = True


def model_protection(window, entry, stop, targets):
    """Fixed stop and ordered target allocations, with explicit research assumptions.

    Each later quote can support the full eligible quantity in this hypothetical
    scenario; no depth or broker execution is asserted. No extra exit latency.
    Same-entry-timestamp protective contact is unresolved, never booked.
    A target is a price-constrained exit; if adverse slippage breaches its
    limit it stays pending. Stop is a market-style exit at the later quote.
    No trailing, financing, currency conversion, or mark-to-market P/L.
    """
    _require(type(entry) is EntryLifecycle and entry.status == "HYPOTHETICAL_ENTRY",
             "hypothetical entry required")
    _require(entry == model_entry_lifecycle(window, entry.intent, entry.profile,
                                           entry.lots, entry.delay),
             "entry does not match replay")
    _require(type(targets) is tuple and 0 < len(targets) <= 128 and
             all(type(t) is Target for t in targets), "explicit immutable target allocation required")
    p = entry.profile
    long = entry.intent.side == "buy"
    side = "sell" if long else "buy"
    e = entry.candidate
    p.instrument.price(stop)
    prev = e.price
    _require(stop < prev if long else stop > prev, "stop geometry")
    with localcontext(Context(prec=96)):
        for t in targets:
            p.instrument.price(t.price)
            p.validate_lots(t.lots)
            _require(t.price > prev if long else t.price < prev, "target order/geometry")
            prev = t.price
        _require(sum((t.lots for t in targets), Decimal(0)) == entry.lots,
                 "allocation must conserve total lots")
        remaining = entry.lots
        exits = []
        pending = list(targets)

        def result(status):
            return ProtectionScenario(status, entry, stop, targets, tuple(exits),
                remaining, sum((x.gross_pnl for x in exits), Decimal(0)),
                sum((x.net_pnl for x in exits), Decimal(0)), p.instrument.quote_currency)

        def touched_stop(q):
            return q <= stop if long else q >= stop

        def touched_target(q, t):
            return q >= t.price if long else q <= t.price

        def add_exit(reason, tick, q, lots, terms):
            nonlocal remaining
            units, price, _, commission, slip_cost = terms
            gross = (price - e.price if long else e.price - price) * units
            entry_fee = lots * p.commission_per_lot
            exits.append(ExitScenario(reason, tick, lots, q, price, commission,
                        slip_cost, gross, entry_fee, gross - commission - entry_fee))
            remaining -= lots

        for tick in window.ticks:
            if tick.sequence < e.tick.sequence:
                continue
            q = tick.bid if long else tick.ask
            if tick.time_ms == e.tick.time_ms:
                if touched_stop(q) or any(touched_target(q, t) for t in pending):
                    return result("UNRESOLVED_ENTRY_PROTECTION")
                continue
            if touched_stop(q):
                add_exit("STOP", tick, q, remaining, _scenario_terms(p, side, q, remaining))
                return result("CLOSED_STOP")
            while pending and touched_target(q, pending[0]):
                t = pending[0]
                terms = _scenario_terms(p, side, q, t.lots)
                price = terms[1]
                if not (price >= t.price if long else price <= t.price):
                    break
                add_exit("TARGET", tick, q, t.lots, terms)
                pending.pop(0)
            if not remaining:
                return result("CLOSED_TARGETS")
        return result("UNRESOLVED_COVERAGE")
