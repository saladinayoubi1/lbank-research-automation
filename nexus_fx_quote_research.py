"""Research-only quote trigger kernel for NEXUS. No fills, wallet or order transport."""
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from typing import Optional


class TickContractError(ValueError):
    pass


def _require(ok, message):
    if not ok:
        raise TickContractError(message)


def _integer(value, name):
    _require(type(value) is int and 0 <= value <= 2**63-1, name)


def _amount(value, name, *, allow_zero=False):
    _require(type(value) is Decimal and value.is_finite(), name)
    _require((0 <= value if allow_zero else 0 < value) and value <= Decimal("1000000000000"), name)
    _require(-12 <= value.as_tuple().exponent <= 12, name)
    return value


def _name(value):
    _require(type(value) is str and bool(value.strip()) and len(value) <= 128, "missing identifier")


def _decimal_text(value):
    return format(value.normalize(), "f") if value else "0"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    price_step: Decimal
    contract_size: Decimal
    quote_currency: str

    def __post_init__(self):
        _name(self.symbol)
        _name(self.quote_currency)
        _amount(self.price_step, "price step")
        _amount(self.contract_size, "contract size")

    def price(self, value):
        _amount(value, "price")
        _require(value % self.price_step == 0, "off-grid price")


@dataclass(frozen=True)
class Tick:
    time_ms: int
    sequence: int
    bid: Decimal
    ask: Decimal

    def __post_init__(self):
        _integer(self.time_ms, "tick timestamp")
        _integer(self.sequence, "tick sequence")
        _amount(self.bid, "bid")
        _amount(self.ask, "ask")
        _require(self.bid <= self.ask, "crossed quote")


def quote_digest(ticks):
    """Hash normalized ordered quote records, not provider authenticity."""
    _require(type(ticks) is tuple and all(type(t) is Tick for t in ticks), "tick tuple required")
    h = sha256()
    for t in ticks:
        record = [t.time_ms, t.sequence, _decimal_text(t.bid), _decimal_text(t.ask)]
        h.update((json.dumps(record, separators=(",", ":")) + "\n").encode("ascii"))
    return h.hexdigest()


@dataclass(frozen=True)
class QuoteWindow:
    instrument: Instrument
    source_id: str
    source_revision: str
    start_ms: int
    end_ms: int
    max_gap_ms: int
    expected_sha256: str
    ticks: tuple

    def __post_init__(self):
        _require(type(self.instrument) is Instrument, "instrument required")
        _name(self.source_id)
        _name(self.source_revision)
        for value in (self.start_ms, self.end_ms, self.max_gap_ms):
            _integer(value, "window time")
        _require(self.start_ms < self.end_ms and self.max_gap_ms > 0, "invalid coverage")
        _require(type(self.ticks) is tuple and len(self.ticks) >= 2, "nonempty immutable tick window required")
        _require(all(type(t) is Tick for t in self.ticks), "invalid tick")
        _require(type(self.expected_sha256) is str and quote_digest(self.ticks) == self.expected_sha256,
                 "quote digest mismatch")
        _require(self.ticks[0].time_ms == self.start_ms and self.ticks[-1].time_ms == self.end_ms,
                 "coverage endpoints not observed")
        previous = None
        for t in self.ticks:
            self.instrument.price(t.bid)
            self.instrument.price(t.ask)
            if previous is not None:
                _require(t.sequence == previous.sequence + 1, "duplicate or missing sequence")
                _require(0 <= t.time_ms - previous.time_ms <= self.max_gap_ms, "unordered or gapped quotes")
            previous = t

    @property
    def binding(self):
        payload = [self.source_id, self.source_revision, self.instrument.symbol,
                   _decimal_text(self.instrument.price_step), _decimal_text(self.instrument.contract_size),
                   self.instrument.quote_currency, self.start_ms, self.end_ms,
                   self.max_gap_ms, self.expected_sha256]
        return sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EntryIntent:
    side: str
    kind: str
    active_ms: int
    expiry_ms: int
    level: Optional[Decimal] = None
    cancel_ms: Optional[int] = None

    def __post_init__(self):
        _require(self.side in ("buy", "sell"), "unknown side")
        _require(self.kind in ("market", "limit", "stop"), "unknown kind")
        _integer(self.active_ms, "activation")
        _integer(self.expiry_ms, "expiry")
        _require(self.active_ms < self.expiry_ms, "expiry must follow activation")
        if self.kind == "market":
            _require(self.level is None, "market has no trigger level")
        else:
            _amount(self.level, "entry level")
        if self.cancel_ms is not None:
            _integer(self.cancel_ms, "cancellation")
            _require(self.cancel_ms >= self.active_ms, "cancellation before activation")


@dataclass(frozen=True)
class Observation:
    status: str
    window_binding: str
    tick: Optional[Tick] = None
    executable_quote: Optional[Decimal] = None
    research_only: bool = True


def observe_entry(window, intent):
    """First eligible quote contact; this does not prove a fill or latency."""
    _require(type(window) is QuoteWindow and type(intent) is EntryIntent, "invalid inputs")
    _require(window.start_ms <= intent.active_ms <= window.end_ms, "activation not covered")
    if intent.level is not None:
        window.instrument.price(intent.level)
    terminal = min(intent.expiry_ms, intent.cancel_ms if intent.cancel_ms is not None else intent.expiry_ms)
    # Activation timestamp excluded: no assumed ordering between signal and quote.
    # Cancellation/expiry wins at its timestamp.
    for t in window.ticks:
        if t.time_ms <= intent.active_ms:
            continue
        if t.time_ms >= terminal:
            break
        q = t.ask if intent.side == "buy" else t.bid
        hit = (intent.kind == "market" or
               (intent.kind == "limit" and (q <= intent.level if intent.side == "buy" else q >= intent.level)) or
               (intent.kind == "stop" and (q >= intent.level if intent.side == "buy" else q <= intent.level)))
        if hit:
            return Observation("ENTRY_CONTACT", window.binding, t, q)
    if terminal <= window.end_ms:
        cancelled = intent.cancel_ms is not None and intent.cancel_ms <= intent.expiry_ms
        return Observation("CANCELLED" if cancelled else "EXPIRED", window.binding)
    return Observation("UNRESOLVED_COVERAGE", window.binding)


def observe_protection(window, *, entry_contact, side, stop, target):
    """First exit quote contact after a bound entry observation, not a booked trade."""
    _require(type(window) is QuoteWindow and type(entry_contact) is Observation, "invalid inputs")
    _require(entry_contact.status == "ENTRY_CONTACT" and entry_contact.window_binding == window.binding,
             "entry observation not bound to window")
    _require(entry_contact.tick in window.ticks, "entry tick absent")
    _require(side in ("buy", "sell"), "unknown side")
    entry = entry_contact.tick
    expected = entry.ask if side == "buy" else entry.bid
    _require(entry_contact.executable_quote == expected, "entry side mismatch")
    window.instrument.price(stop)
    window.instrument.price(target)
    _require(stop < expected < target if side == "buy" else target < expected < stop,
             "invalid protective geometry")
    # Same entry quote cannot prove subsequent exposure; later ordered quote only.
    # If the entry spread already crosses protection, the missing fill/activation
    # ordering is material; do not silently skip that ambiguity.
    exit_at_entry = entry.bid if side == "buy" else entry.ask
    if (exit_at_entry <= stop or exit_at_entry >= target) if side == "buy" else (exit_at_entry >= stop or exit_at_entry <= target):
        return Observation("UNRESOLVED_ENTRY_PROTECTION", window.binding)
    for t in window.ticks:
        if t.sequence <= entry.sequence:
            continue
        q = t.bid if side == "buy" else t.ask
        stop_hit = q <= stop if side == "buy" else q >= stop
        target_hit = q >= target if side == "buy" else q <= target
        if stop_hit or target_hit:
            return Observation("STOP_CONTACT" if stop_hit else "TARGET_CONTACT", window.binding, t, q)
    return Observation("UNRESOLVED_COVERAGE", window.binding)
