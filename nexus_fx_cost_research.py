"""NEXUS offline FX cost scenario contract; no fill, ledger or order authority."""
from dataclasses import dataclass
from decimal import Decimal, localcontext, Context
from nexus_fx_quote_research import (
    Instrument, QuoteWindow, EntryIntent, Observation, observe_entry,
    _amount, _name, _require, _scaled_units,
)


@dataclass(frozen=True)
class CostProfile:
    """Explicit scenario assumptions: lots, quote-currency commission per lot per side,
    adverse integer price ticks. Zero must be explicitly supplied, not inferred.
    No broker authenticity, spread duplication, financing or FX conversion.
    """
    instrument: Instrument
    source_id: str
    source_revision: str
    assumption_id: str
    lot_step: Decimal
    min_lots: Decimal
    max_lots: Decimal
    commission_per_lot: Decimal
    slippage_ticks: int

    def __post_init__(self):
        _require(type(self.instrument) is Instrument, "instrument required")
        for name in (self.source_id, self.source_revision, self.assumption_id):
            _name(name)
        for amount in (self.lot_step, self.min_lots, self.max_lots):
            _amount(amount, "lot metadata")
        _require(self.min_lots <= self.max_lots, "lot bounds")
        for amount in (self.min_lots, self.max_lots):
            _require(_scaled_units(amount) % _scaled_units(self.lot_step) == 0,
                     "lot bounds off-grid")
        _amount(self.commission_per_lot, "commission per lot", allow_zero=True)
        _require(type(self.slippage_ticks) is int and 0 <= self.slippage_ticks <= 10**9,
                 "explicit bounded slippage ticks required")

    def validate_lots(self, lots):
        _amount(lots, "lots")
        _require(self.min_lots <= lots <= self.max_lots, "lot quantity outside bounds")
        _require(_scaled_units(lots) % _scaled_units(self.lot_step) == 0, "off-grid lots")


@dataclass(frozen=True)
class EntryCostScenario:
    window_binding: str
    profile: CostProfile
    intent: EntryIntent
    contact: Observation
    lots: Decimal
    underlying_units: Decimal
    hypothetical_price: Decimal
    quote_notional: Decimal
    commission: Decimal
    slippage_cost: Decimal
    quote_currency: str
    research_only: bool = True


def _validate_profile_binding(window, profile, lots):
    _require(type(window) is QuoteWindow and type(profile) is CostProfile,
             "invalid cost contract types")
    _require((profile.instrument, profile.source_id, profile.source_revision) ==
             (window.instrument, window.source_id, window.source_revision),
             "cost profile not bound to source/instrument")
    profile.validate_lots(lots)


def _scenario_terms(profile, side, reference, lots):
    """Shared exact-decimal cost model, not fill evidence."""
    with localcontext(Context(prec=96)):
        slip = profile.instrument.price_step * profile.slippage_ticks
        price = reference + slip if side == "buy" else reference - slip
        profile.instrument.price(price)
        units = lots * profile.instrument.contract_size
        return (units, price, units * price, lots * profile.commission_per_lot,
                units * slip)


def _limit_allows(intent, price):
    return (intent.kind != "limit" or
            (price <= intent.level if intent.side == "buy" else price >= intent.level))


def model_entry_cost(window, intent, contact, profile, lots):
    """Calculate a scenario on a replayed quote contact, never a realized fill.
    Limit violations fail closed instead of clipping an adverse price.
    """
    _require(type(intent) is EntryIntent and type(contact) is Observation,
             "invalid contract types")
    _validate_profile_binding(window, profile, lots)
    _require(contact.status == "ENTRY_CONTACT" and contact == observe_entry(window, intent),
             "entry contact not verified by replay")
    terms = _scenario_terms(profile, intent.side, contact.executable_quote, lots)
    _require(_limit_allows(intent, terms[1]), "adverse scenario violates limit price")
    return EntryCostScenario(window.binding, profile, intent, contact, lots, *terms,
                             profile.instrument.quote_currency)
