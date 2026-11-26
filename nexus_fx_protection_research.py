"""Offline NEXUS FX protective exit scenarios. No actual fills or wallet authority."""
from dataclasses import dataclass
from decimal import Decimal, Context, localcontext
from nexus_fx_quote_research import Tick, _require, _integer
from nexus_fx_cost_research import _scenario_terms
from nexus_fx_entry_lifecycle_research import EntryLifecycle, model_entry_lifecycle


@dataclass(frozen=True)
class Target:
    price: Decimal
    lots: Decimal


@dataclass(frozen=True)
class NextBarStopMove:
    """Caller-supplied tighter stop after a specified partial target."""
    after_target: int
    new_stop: Decimal
    bar_ms: int
    anchor_ms: int

    def __post_init__(self):
        for x in (self.after_target, self.bar_ms, self.anchor_ms):
            _integer(x, "stop move timing")
        _require(self.after_target > 0 and self.bar_ms > 0 and self.anchor_ms < self.bar_ms,
                 "invalid target index or bar grid")


@dataclass(frozen=True)
class ExitPolicy:
    target_price_mode: str
    stop_move: NextBarStopMove = None

    def __post_init__(self):
        _require(self.target_price_mode in ("ADVERSE_QUOTE", "ORDER_PRICE"),
                 "explicit target price mode required")
        _require(self.stop_move is None or type(self.stop_move) is NextBarStopMove,
                 "invalid stop move policy")


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
    policy: ExitPolicy = None
    active_stop: Decimal = None
    pending_activation_ms: int = None


def model_protection(window, entry, stop, targets, *, policy=None):
    """Fixed stop and ordered target allocations, with explicit research assumptions.

    Each later quote can support the full eligible quantity in this hypothetical
    scenario; no depth or broker execution is asserted. No extra exit latency.
    Same-entry-timestamp protective contact is unresolved, never booked.
    A target is a price-constrained exit; if adverse slippage breaches its
    limit it stays pending. Stop is a market-style exit at the later quote.
    Legacy policy retains adverse-quote target simulation. Explicit ORDER_PRICE
    books exactly the limit on eligible quote contact, without claiming actual
    liquidity or additional market-order slippage on that limit.
    Optional stop move activates at the next fixed-grid bar boundary after its
    triggering partial target. No continuous trailing or mark-to-market P/L.
    """
    _require(type(entry) is EntryLifecycle and entry.status == "HYPOTHETICAL_ENTRY",
             "hypothetical entry required")
    _require(entry == model_entry_lifecycle(window, entry.intent, entry.profile,
                                           entry.lots, entry.delay),
             "entry does not match replay")
    _require(type(targets) is tuple and 0 < len(targets) <= 128 and
             all(type(t) is Target for t in targets), "explicit immutable target allocation required")
    _require(policy is None or type(policy) is ExitPolicy, "invalid exit policy")
    move = None if policy is None else policy.stop_move
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
        if move is not None:
            _require(move.after_target < len(targets), "move must follow a partial target")
            p.instrument.price(move.new_stop)
            trigger_price = targets[move.after_target - 1].price
            _require(stop < move.new_stop < trigger_price if long else
                     trigger_price < move.new_stop < stop, "move must tighten stop behind trigger")
        active_stop = stop
        pending_activation = None
        remaining = entry.lots
        exits = []
        pending = list(targets)

        def result(status):
            return ProtectionScenario(status, entry, stop, targets, tuple(exits),
                remaining, sum((x.gross_pnl for x in exits), Decimal(0)),
                sum((x.net_pnl for x in exits), Decimal(0)), p.instrument.quote_currency,
                policy=policy, active_stop=active_stop, pending_activation_ms=pending_activation)

        def touched_stop(q):
            return q <= active_stop if long else q >= active_stop

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
            if pending_activation is not None and tick.time_ms >= pending_activation:
                active_stop = move.new_stop
                pending_activation = None
            if touched_stop(q):
                add_exit("STOP", tick, q, remaining, _scenario_terms(p, side, q, remaining))
                pending_activation = None
                return result("CLOSED_STOP")
            while pending and touched_target(q, pending[0]):
                t = pending[0]
                if policy is not None and policy.target_price_mode == "ORDER_PRICE":
                    units = t.lots * p.instrument.contract_size
                    terms = (units, t.price, units * t.price,
                             t.lots * p.commission_per_lot, Decimal(0))
                else:
                    terms = _scenario_terms(p, side, q, t.lots)
                    price = terms[1]
                    if not (price >= t.price if long else price <= t.price):
                        break
                add_exit("TARGET", tick, q, t.lots, terms)
                pending.pop(0)
                if move is not None and len(exits) == move.after_target and remaining:
                    pending_activation = (move.anchor_ms +
                        ((tick.time_ms - move.anchor_ms) // move.bar_ms + 1) * move.bar_ms)
                    _integer(pending_activation, "stop activation overflow")
            if not remaining:
                pending_activation = None
                return result("CLOSED_TARGETS")
        return result("UNRESOLVED_COVERAGE")
