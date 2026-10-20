"""Synthetic Bybit Spot IOC accounting, with no network or order writer.

This is a receipt reconciler, not a liquidity model. Callers must supply every
synthetic fill; no fill is inferred from a candle or an acknowledgement. The
frozen CTREND v1 model/wallet stay unchanged. Fee rounding and historical venue
rules still require source evidence before any real-data feasibility claim.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Mapping, Sequence

from research.nexus_ctrend_causal_wallet_v1 import (
    ZERO, ONE, WalletError, _number, _time, _add, _mul, _neg, _precision,
)


class SpotError(WalletError):
    """An invalid synthetic order/receipt; account state is unchanged."""


def _positive(value, name):
    value = _number(value, name)
    if value <= ZERO:
        raise SpotError(name + " must be positive")
    return value


def _id(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,36}", value):
        raise SpotError("Invalid " + name)
    return value


def _multiple(value, step):
    # Reuse exact finite-decimal division, not the process Decimal context.
    from research.nexus_ctrend_causal_wallet_v1 import PaperWallet
    return PaperWallet._multiple(value, step)


@dataclass(frozen=True)
class SpotRules:
    symbol: str
    base_coin: str
    quote_coin: str
    base_precision: Decimal | str
    quote_precision: Decimal | str
    min_order_amt: Decimal | str
    max_market_order_qty: Decimal | str
    max_limit_order_qty: Decimal | str
    tick_size: Decimal | str
    as_of_ms: int
    source_id: str
    evidence_class: str
    valid_until_ms: int | None = None

    def __post_init__(self):
        if (not isinstance(self.base_coin, str) or not re.fullmatch(r"[A-Z0-9]+", self.base_coin)
                or self.quote_coin != "USDT" or self.base_coin == "USDT"
                or self.symbol != self.base_coin + self.quote_coin):
            raise SpotError("Require an explicit base/USDT Spot identity")
        for field in ("base_precision", "quote_precision", "min_order_amt",
                      "max_market_order_qty", "max_limit_order_qty", "tick_size"):
            object.__setattr__(self, field, _positive(getattr(self, field), field))
        _time(self.as_of_ms)
        if self.evidence_class not in ("synthetic", "observed_metadata"):
            raise SpotError("Unknown rules evidence class")
        prefix = "synthetic:" if self.evidence_class == "synthetic" else "bybit:"
        if not isinstance(self.source_id, str) or not self.source_id.startswith(prefix):
            raise SpotError("Rules must retain their explicit source class")
        if self.valid_until_ms is not None:
            _time(self.valid_until_ms)
            if self.valid_until_ms < self.as_of_ms or self.evidence_class != "synthetic":
                raise SpotError("Do not invent historical validity for current metadata")

    def validate_at(self, timestamp):
        end = self.as_of_ms if self.valid_until_ms is None else self.valid_until_ms
        if not self.as_of_ms <= timestamp <= end:
            raise SpotError("Rules are future, stale or expired")


def rules_from_response(response, *, symbol, captured_at_ms, source_id, evidence_class):
    """Parse a successful Spot response; current metadata is never backdated."""
    try:
        if type(response["retCode"]) is not int or response["retCode"] != 0:
            raise SpotError("Unsuccessful provider response")
        result = response["result"]
        if result["category"] != "spot" or not isinstance(result["list"], list):
            raise SpotError("Require Spot instruments schema")
        matches = [row for row in result["list"] if row["symbol"] == symbol]
        if len(matches) != 1 or matches[0]["status"] != "Trading":
            raise SpotError("Missing, duplicated or nontrading symbol")
        row = matches[0]
        lot = row["lotSizeFilter"]
        return SpotRules(symbol, row["baseCoin"], row["quoteCoin"],
            lot["basePrecision"], lot["quotePrecision"], lot["minOrderAmt"],
            lot["maxMarketOrderQty"], lot["maxLimitOrderQty"],
            row["priceFilter"]["tickSize"], captured_at_ms, source_id, evidence_class)
    except (KeyError, TypeError) as exc:
        raise SpotError("Incomplete Spot metadata; deprecated fields are not substitutes") from exc


@dataclass(frozen=True)
class IOCIntent:
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: Decimal | str
    market_unit: str | None
    reference_price: Decimal | str
    price_bound: Decimal | str
    decision_ms: int
    submitted_ms: int
    source_id: str

    def __post_init__(self):
        _id(self.order_id, "order ID")
        if self.side not in ("Buy", "Sell") or self.order_type not in ("Market", "Limit"):
            raise SpotError("Only Spot Buy/Sell Market/Limit IOC is supported")
        if (self.order_type == "Market" and self.market_unit not in ("baseCoin", "quoteCoin")):
            raise SpotError("Market quantity unit must be explicit")
        if self.order_type == "Limit" and self.market_unit is not None:
            raise SpotError("Limit quantity is base coin; marketUnit must be absent")
        if self.side == "Sell" and self.market_unit == "quoteCoin":
            raise SpotError("Quote-quantity sells are unsupported; never infer base quantity")
        for field in ("quantity", "reference_price", "price_bound"):
            object.__setattr__(self, field, _positive(getattr(self, field), field))
        for value in (self.decision_ms, self.submitted_ms):
            _time(value)
        if self.submitted_ms <= self.decision_ms:
            raise SpotError("Execution must originate strictly after decision")
        if not isinstance(self.source_id, str) or not self.source_id.startswith("synthetic:"):
            raise SpotError("Real order admission is disabled")
        if self.order_type == "Market":
            if ((self.side == "Buy" and self.price_bound < self.reference_price)
                    or (self.side == "Sell" and self.price_bound > self.reference_price)):
                raise SpotError("Market bound must include the reference price")


@dataclass(frozen=True)
class SyntheticFill:
    fill_id: str
    order_id: str
    base_quantity: Decimal | str
    price: Decimal | str
    executed_ms: int

    def __post_init__(self):
        _id(self.fill_id, "fill ID")
        _id(self.order_id, "fill order ID")
        object.__setattr__(self, "base_quantity", _positive(self.base_quantity, "fill quantity"))
        object.__setattr__(self, "price", _positive(self.price, "fill price"))
        _time(self.executed_ms)


class SpotResearchWallet:
    """One shared long/cash USDT account. Settled IOC remainders are cancelled.

    Validation is atomic per order, not across several exchange orders. A prior
    settled sale survives a later rejected purchase. Unfilled sale proceeds
    cannot fund a purchase. Requested base quantity obeys the grid; partial
    executions and net fee dust need not meet an entire order's minimum.
    """
    def __init__(self, initial_cash="500"):
        self.initial_cash = _positive(initial_cash, "initial cash")
        self._cash = self.initial_cash
        self._positions = {}
        self._orders, self._fills = set(), set()
        self._journal = []
        self._peak, self._drawdown = self.initial_cash, ZERO
        self._last_ms, self._last_marks = None, {}

    @property
    def cash(self):
        return self._cash

    @property
    def positions(self):
        return dict(self._positions)

    @property
    def journal(self):
        return deepcopy(self._journal)

    def _marks(self, marks, required):
        if not isinstance(marks, Mapping):
            raise SpotError("Marks must be a mapping")
        parsed = {s: _positive(p, "mark") for s, p in marks.items()}
        if set(required) - set(parsed):
            raise SpotError("Missing held/ordered mark; NAV cannot be certified")
        return parsed

    def _clock(self, timestamp, marks):
        _time(timestamp)
        if self._last_ms is not None:
            if timestamp < self._last_ms:
                raise SpotError("Account time moved backwards")
            if timestamp == self._last_ms and any(
                marks[s] != self._last_marks[s] for s in set(marks) & set(self._last_marks)
            ):
                raise SpotError("Conflicting valuation at the same timestamp")

    @staticmethod
    def _nav(cash, positions, marks):
        return _add(cash, *(_mul(q, marks[s]) for s, q in positions.items()))

    @_precision
    def settle_ioc(self, intent: IOCIntent, fills: Sequence[SyntheticFill], rules: SpotRules,
                   marks: Mapping, *, fee_rate, closed_at_ms):
        if not isinstance(intent, IOCIntent) or not isinstance(rules, SpotRules):
            raise SpotError("Typed intent and Spot rules required")
        if rules.evidence_class != "synthetic" or rules.symbol != intent.symbol:
            raise SpotError("Only source-bound synthetic rules can execute here")
        if intent.order_id in self._orders:
            raise SpotError("Order already settled")
        _time(closed_at_ms)
        if closed_at_ms < intent.submitted_ms:
            raise SpotError("Close precedes submission")
        # Old marks must not be reused as evidence for an older order submission.
        if self._last_ms is not None and intent.submitted_ms < self._last_ms:
            raise SpotError("Submission predates the settled account")
        rules.validate_at(intent.submitted_ms)
        rules.validate_at(closed_at_ms)
        prices = self._marks(marks, set(self._positions) | {intent.symbol})
        if prices[intent.symbol] != intent.reference_price:
            raise SpotError("Intent reference differs from the valuation mark")
        self._clock(closed_at_ms, prices)
        fee = _number(fee_rate, "fee rate")
        if not ZERO <= fee < ONE:
            raise SpotError("Fee rate must be in [0,1)")
        quote_unit = intent.market_unit == "quoteCoin"
        step = rules.quote_precision if quote_unit else rules.base_precision
        if not _multiple(intent.quantity, step):
            raise SpotError("Requested quantity violates its explicit unit precision")
        limit = rules.max_market_order_qty if intent.order_type == "Market" else rules.max_limit_order_qty
        if not quote_unit and intent.quantity > limit:
            raise SpotError("Order exceeds its order-type quantity cap")
        if intent.order_type == "Limit" and not _multiple(intent.price_bound, rules.tick_size):
            raise SpotError("Limit price violates tickSize")
        # A conservative synthetic submission rule; not a claim about Bybit's
        # unspecified instantaneous market-order notional valuation algorithm.
        minimum_basis = (intent.quantity if quote_unit else
                         _mul(intent.quantity, min(intent.reference_price, intent.price_bound)))
        if minimum_basis < rules.min_order_amt:
            raise SpotError("Submitted order is below minOrderAmt")
        if intent.side == "Buy":
            reserve = intent.quantity if quote_unit else _mul(intent.quantity, intent.price_bound)
            if reserve > self._cash:
                raise SpotError("Insufficient actual cash; prospective sale proceeds do not count")
        elif intent.quantity > self._positions.get(intent.symbol, ZERO):
            raise SpotError("Insufficient actual base; borrowing and shorting are disabled")

        cash, positions = self._cash, dict(self._positions)
        before = self._nav(cash, positions, prices)
        seen, records = set(), []
        base_total = quote_total = fees_marked = impact = ZERO
        previous_time = intent.submitted_ms
        for fill in fills:
            if not isinstance(fill, SyntheticFill) or fill.order_id != intent.order_id:
                raise SpotError("Detached or untyped fill")
            if fill.fill_id in self._fills or fill.fill_id in seen:
                raise SpotError("Duplicate fill")
            if not previous_time <= fill.executed_ms <= closed_at_ms:
                raise SpotError("Fill time is outside the IOC interval or moved backwards")
            previous_time = fill.executed_ms
            if ((intent.side == "Buy" and fill.price > intent.price_bound)
                    or (intent.side == "Sell" and fill.price < intent.price_bound)):
                raise SpotError("Fill violates explicit IOC price bound")
            q, price = fill.base_quantity, fill.price
            gross = _mul(q, price)
            base_total, quote_total = _add(base_total, q), _add(quote_total, gross)
            used = quote_total if quote_unit else base_total
            if used > intent.quantity or base_total > limit:
                raise SpotError("Cumulative fills exceed requested amount or venue quantity cap")
            held = positions.get(intent.symbol, ZERO)
            if intent.side == "Buy":
                fee_amount = _mul(q, fee)
                fee_coin = rules.base_coin
                received = _add(q, _neg(fee_amount))
                cash = _add(cash, _neg(gross))
                positions[intent.symbol] = _add(held, received)
                fee_value = _mul(fee_amount, intent.reference_price)
                drag = _mul(q, _add(price, _neg(intent.reference_price)))
            else:
                fee_amount = _mul(gross, fee)
                fee_coin = rules.quote_coin
                received = _add(gross, _neg(fee_amount))
                cash = _add(cash, received)
                positions[intent.symbol] = _add(held, _neg(q))
                fee_value = fee_amount
                drag = _mul(q, _add(intent.reference_price, _neg(price)))
            if cash < ZERO or positions[intent.symbol] < ZERO:
                raise SpotError("Negative cash/base after execution")
            fees_marked, impact = _add(fees_marked, fee_value), _add(impact, drag)
            seen.add(fill.fill_id)
            records.append(dict(fill_id=fill.fill_id, order_id=fill.order_id,
                executed_ms=fill.executed_ms, base_quantity=str(q), price=str(price),
                gross_quote=str(gross), fee_amount=str(fee_amount), fee_coin=fee_coin,
                fee_marked_usdt=str(fee_value), price_impact_usdt=str(drag),
                received_quantity=str(received), cash_after=str(cash),
                base_after=str(positions[intent.symbol])))
        positions = {s: q for s, q in positions.items() if q != ZERO}
        after = self._nav(cash, positions, prices)
        if after != _add(before, _neg(fees_marked), _neg(impact)):
            raise SpotError("Independent-unit cash/base NAV identity failed")
        used = quote_total if quote_unit else base_total
        remaining = _add(intent.quantity, _neg(used))
        status = "Filled" if remaining == ZERO else (
            "PartiallyFilledCanceled" if used > ZERO else "Canceled")
        peak = max(self._peak, before)
        dd = max(self._drawdown, _add(peak, _neg(before)) / peak)
        peak = max(peak, after)
        dd = max(dd, _add(peak, _neg(after)) / peak)
        report = dict(schema="nexus.ctrend-bybit-spot-ioc.v1", evidence_class="synthetic",
            order_id=intent.order_id, symbol=intent.symbol, side=intent.side,
            order_type=intent.order_type, market_unit=intent.market_unit,
            time_in_force="IOC", status=status, requested_quantity=str(intent.quantity),
            filled_base=str(base_total), filled_quote=str(quote_total),
            canceled_quantity=str(remaining), canceled_quantity_unit="quoteCoin" if quote_unit else "baseCoin",
            pre_nav=str(before), post_nav=str(after), cash=str(cash),
            positions={s: str(q) for s, q in positions.items()}, fills=records,
            fee_marked_usdt=str(fees_marked), price_impact_usdt=str(impact),
            peak_nav=str(peak), max_drawdown=str(dd), closed_at_ms=closed_at_ms,
            rules_source_id=rules.source_id, rules_as_of_ms=rules.as_of_ms,
            financial_backtest=False, demo_admitted=False, paper_writer_enabled=False,
            live_enabled=False, real_orders=0)
        self._cash, self._positions = cash, positions
        self._peak, self._drawdown = peak, dd
        self._orders.add(intent.order_id)
        self._fills.update(seen)
        old = self._last_marks if closed_at_ms == self._last_ms else {}
        self._last_ms, self._last_marks = closed_at_ms, {**old, **prices}
        self._journal.append(deepcopy(report))
        return report


@_precision
def plan_initial_allocation(target_weights, rules, reference_prices, *,
                            decision_ms, submitted_ms, cash="500", slippage_rate="0.0005"):
    """Translate an initial long/cash allocation into explicit quote-budget buys.

    Selected asset IDs must already have a verified symbol crosswalk. This pure
    function neither supplies such a crosswalk nor changes CTREND membership.
    It handles initial cash only, not later rebalances. Downward quote rounding
    remains in cash; fee deducted from received base is never added to spend.
    Receipt settlement reports actual holdings, not the requested weights.
    """
    if not isinstance(target_weights, Mapping) or not isinstance(rules, Mapping):
        raise SpotError("Require explicit target and rules mappings")
    weights = {s: _number(w, "target weight") for s, w in target_weights.items()}
    if any(w < ZERO for w in weights.values()) or _add(*weights.values()) > ONE:
        raise SpotError("Initial allocation must be long/cash without leverage")
    available = _positive(cash, "cash")
    slip = _number(slippage_rate, "slippage rate")
    if not ZERO <= slip < ONE:
        raise SpotError("Slippage rate must be in [0,1)")
    from research.nexus_ctrend_causal_wallet_v1 import PaperWallet
    result, allocated = [], ZERO
    for index, (symbol, weight) in enumerate(sorted(weights.items())):
        if weight == ZERO:
            continue
        if symbol not in rules or symbol not in reference_prices:
            raise SpotError("Missing selected-asset identity/rules/reference")
        spec = rules[symbol]
        if not isinstance(spec, SpotRules) or spec.symbol != symbol or spec.evidence_class != "synthetic":
            raise SpotError("Require matching explicitly synthetic rules")
        spec.validate_at(submitted_ms)
        amount, _, _ = PaperWallet._floor_quantity(_mul(available, weight), spec.quote_precision)
        if amount == ZERO or amount < spec.min_order_amt:
            raise SpotError("Selected member is not affordable; do not drop or redistribute it")
        price = _positive(reference_prices[symbol], "reference price")
        result.append(IOCIntent(f"entry_{decision_ms}_{index}", symbol, "Buy", "Market",
            amount, "quoteCoin", price, _mul(price, _add(ONE, slip)),
            decision_ms, submitted_ms, "synthetic:ctrend-initial-allocation"))
        allocated = _add(allocated, amount)
    return tuple(result), _add(available, _neg(allocated))
