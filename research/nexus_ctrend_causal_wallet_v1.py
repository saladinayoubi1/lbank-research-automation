"""Synthetic/Paper-only, self-financing long/cash wallet; no exchange I/O.

Timestamps are epoch milliseconds. LotSpec is a caller-supplied snapshot, not
proof of historical Bybit rules. Without valid_until it is valid only at as_of.
Target solving uses 50 significant digits. A 1e-40 relative lattice snap repairs
arithmetic representations of exact lot boundaries; it never waives a minimum
order or negative-cash check. All other quantity rounding is downward.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, DecimalException, ROUND_FLOOR, ROUND_HALF_EVEN, localcontext
from functools import wraps
from typing import Mapping

ZERO, ONE = Decimal("0"), Decimal("1")
PRECISION = 50
LATTICE_EPS = Decimal("1e-40")


class WalletError(ValueError):
    """An invalid whole batch; no wallet state was changed."""


def _number(value, label: str) -> Decimal:
    if not isinstance(value, (str, Decimal)):
        raise WalletError(f"{label}: require a Decimal or decimal string")
    try:
        result = Decimal(value)
    except DecimalException as exc:
        raise WalletError(f"{label}: malformed decimal") from exc
    if not result.is_finite():
        raise WalletError(f"{label}: nonfinite decimal")
    return result


def _time(value, label="timestamp") -> int:
    if type(value) is not int or value < 0:
        raise WalletError(f"{label}: require nonnegative integer epoch milliseconds")
    return value


def _symbol(value) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise WalletError("Invalid symbol")
    return value


def _add(*values: Decimal) -> Decimal:
    """Exact finite-decimal addition, including account reconciliation."""
    if not values:
        return ZERO
    high = max(v.adjusted() for v in values)
    low = min(v.as_tuple().exponent for v in values)
    with localcontext() as ctx:
        ctx.prec = max(PRECISION, high - low + len(str(len(values))) + 3)
        return sum(values, ZERO)


def _mul(*values: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = max(PRECISION, sum(len(v.as_tuple().digits) for v in values) + 3)
        result = ONE
        for value in values:
            result *= value
        return result


def _neg(value: Decimal) -> Decimal:
    return value.copy_negate()


def _precision(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            with localcontext() as ctx:
                ctx.prec = PRECISION
                return method(*args, **kwargs)
        except DecimalException as exc:
            raise WalletError("Decimal arithmetic could not represent this batch") from exc
    return call


@dataclass(frozen=True)
class LotSpec:
    qty_step: Decimal | str
    min_qty: Decimal | str
    min_notional: Decimal | str
    as_of: int
    valid_until: int | None = None

    def __post_init__(self):
        for name in ("qty_step", "min_qty", "min_notional"):
            value = _number(getattr(self, name), "LotSpec." + name)
            if value < ZERO or (name == "qty_step" and value == ZERO):
                raise WalletError("Invalid lot constraint: " + name)
            object.__setattr__(self, name, value)
        _time(self.as_of, "LotSpec.as_of")
        if self.valid_until is not None:
            _time(self.valid_until, "LotSpec.valid_until")
            if self.valid_until < self.as_of:
                raise WalletError("LotSpec expiry precedes snapshot")

    def validate_at(self, timestamp: int):
        end = self.as_of if self.valid_until is None else self.valid_until
        if not self.as_of <= timestamp <= end:
            raise WalletError("Future, stale, or expired LotSpec")


class PaperWallet:
    def __init__(self, initial_cash: Decimal | str = "500"):
        initial = _number(initial_cash, "initial_cash")
        if initial <= ZERO:
            raise WalletError("initial_cash must be positive")
        self.initial_cash = initial
        self._cash = initial
        self._positions: dict[str, Decimal] = {}
        self._journal: list[dict] = []
        self._peak = initial
        self._drawdown = ZERO
        self._last_timestamp: int | None = None
        self._last_prices: dict[str, Decimal] = {}

    @property
    def cash(self) -> Decimal:
        return self._cash

    @property
    def positions(self) -> dict[str, Decimal]:
        return dict(self._positions)

    @property
    def journal(self) -> list[dict]:
        return deepcopy(self._journal)

    def _prices(self, prices: Mapping, required) -> dict[str, Decimal]:
        if not isinstance(prices, Mapping):
            raise WalletError("prices must be a mapping")
        parsed = {_symbol(s): _number(p, "price:" + str(s)) for s, p in prices.items()}
        if any(p <= ZERO for p in parsed.values()):
            raise WalletError("Prices must be positive")
        missing = set(required) - set(parsed)
        if missing:
            raise WalletError("Missing held/target price: " + ",".join(sorted(missing)))
        return parsed

    def _clock(self, timestamp: int, prices: Mapping[str, Decimal]):
        _time(timestamp)
        if self._last_timestamp is not None:
            if timestamp < self._last_timestamp:
                raise WalletError("Time travel")
            if timestamp == self._last_timestamp:
                for s in set(prices) & set(self._last_prices):
                    if prices[s] != self._last_prices[s]:
                        raise WalletError("Conflicting prices at the same timestamp")

    def _commit_clock(self, timestamp, prices):
        previous = self._last_prices if timestamp == self._last_timestamp else {}
        self._last_prices = {**previous, **prices}
        self._last_timestamp = timestamp

    def _value(self, prices, cash=None, positions=None):
        cash = self._cash if cash is None else cash
        positions = self._positions if positions is None else positions
        return _add(cash, *(_mul(q, prices[s]) for s, q in positions.items()))

    @_precision
    def nav(self, prices: Mapping[str, Decimal | str]) -> Decimal:
        """Pure valuation: missing held prices fail without any renormalization."""
        return self._value(self._prices(prices, self._positions))

    def _risk(self, *navs):
        peak, drawdown = self._peak, self._drawdown
        for nav in navs:
            peak = max(peak, nav)
            drawdown = max(drawdown, _add(peak, _neg(nav)) / peak)
        return peak, drawdown

    @_precision
    def mark(self, prices: Mapping[str, Decimal | str], *, timestamp: int) -> dict:
        parsed = self._prices(prices, self._positions)
        self._clock(timestamp, parsed)
        value = self._value(parsed)
        peak, dd = self._risk(value)
        report = dict(kind="mark", timestamp=timestamp, nav=str(value),
                      cash=str(self._cash), positions={s: str(q) for s, q in self._positions.items()},
                      peak_nav=str(peak), max_drawdown=str(dd), paper_only=True,
                      live_enabled=False, orders=0)
        self._peak, self._drawdown = peak, dd
        self._commit_clock(timestamp, parsed)
        self._journal.append(deepcopy(report))
        return report

    @staticmethod
    def _floor_quantity(raw: Decimal, step: Decimal):
        ratio = raw / step
        nearest = ratio.to_integral_value(rounding=ROUND_HALF_EVEN)
        snap = (ratio - nearest).copy_abs() <= _mul(LATTICE_EPS, max(ONE, ratio.copy_abs()))
        adjusted = _mul(nearest, step) if snap else raw
        units = nearest if snap else ratio.to_integral_value(rounding=ROUND_FLOOR)
        quantity = _mul(units, step)
        return quantity, adjusted, _add(adjusted, _neg(raw))

    @staticmethod
    def _multiple(quantity: Decimal, step: Decimal) -> bool:
        with localcontext() as ctx:
            ctx.prec = max(PRECISION, quantity.adjusted() - step.as_tuple().exponent + 5)
            return quantity % step == ZERO

    @_precision
    def rebalance(self, target_weights: Mapping[str, Decimal | str],
                  prices: Mapping[str, Decimal | str], specs: Mapping[str, LotSpec], *,
                  timestamp: int, fee_rate: Decimal | str,
                  slippage_rate: Decimal | str) -> dict:
        if not isinstance(target_weights, Mapping) or not isinstance(specs, Mapping):
            raise WalletError("Weights and specs must be mappings")
        weights = {_symbol(s): _number(w, "weight:" + str(s)) for s, w in target_weights.items()}
        total_weight = _add(*weights.values())
        if any(w < ZERO for w in weights.values()) or total_weight > ONE:
            raise WalletError("Weights must be long/cash, nonnegative, and sum to at most one")
        fee, slip = _number(fee_rate, "fee_rate"), _number(slippage_rate, "slippage_rate")
        if not ZERO <= fee < ONE or not ZERO <= slip < ONE:
            raise WalletError("Rates must lie in [0,1)")
        symbols = sorted(set(self._positions) | {s for s, w in weights.items() if w > ZERO})
        parsed = self._prices(prices, symbols)
        self._clock(timestamp, parsed)
        for s, spec in specs.items():
            _symbol(s)
            if not isinstance(spec, LotSpec):
                raise WalletError("Expected LotSpec for " + s)
            spec.validate_at(timestamp)
        if set(symbols) - set(specs):
            raise WalletError("Missing LotSpec")
        pre = self._value(parsed)
        buy_multiplier, sell_multiplier = _add(ONE, slip), _add(ONE, _neg(slip))

        def continuous_cost(value):
            costs = []
            for s in symbols:
                desired = _mul(weights.get(s, ZERO), value) / parsed[s]
                delta = _add(desired, _neg(self._positions.get(s, ZERO)))
                reference = _mul(delta.copy_abs(), parsed[s])
                executed = _mul(reference, buy_multiplier if delta > ZERO else sell_multiplier)
                costs.append(_add(_mul(reference, slip), _mul(executed, fee)))
            return _add(*costs)

        lo, hi = ZERO, pre
        if continuous_cost(hi) == ZERO:
            lo = hi
        else:
            for _ in range(256):
                mid = _add(lo, hi) / 2
                if mid == lo or mid == hi:
                    break
                residual = _add(mid, continuous_cost(mid), _neg(pre))
                if residual == ZERO:
                    lo = hi = mid
                    break
                if residual < ZERO:
                    lo = mid
                else:
                    hi = mid
        target_nav = lo
        targets, rounding, proposals = {}, {}, []
        for s in symbols:
            raw = _mul(weights.get(s, ZERO), target_nav) / parsed[s]
            quantity, adjusted, snap = self._floor_quantity(raw, specs[s].qty_step)
            if weights.get(s, ZERO) > ZERO and quantity == ZERO:
                raise WalletError("Positive target rounds to zero: " + s)
            targets[s] = quantity
            rounding[s] = dict(continuous_quantity=str(raw), floored_quantity=str(quantity),
                               arithmetic_snap_quantity=str(snap),
                               unallocated_quantity=str(_add(adjusted, _neg(quantity))))
            delta = _add(quantity, _neg(self._positions.get(s, ZERO)))
            if delta == ZERO:
                continue
            amount = delta.copy_abs()
            execution = _mul(parsed[s], buy_multiplier if delta > ZERO else sell_multiplier)
            gross = _mul(amount, execution)
            if not self._multiple(amount, specs[s].qty_step):
                raise WalletError("Proposed delta violates quantity step: " + s)
            if amount < specs[s].min_qty or gross < specs[s].min_notional:
                raise WalletError("Proposed delta fails minimum order: " + s)
            proposals.append((delta > ZERO, s, amount, execution, gross))

        # Work entirely on proposed state. A failed leg cannot leave an earlier sale behind.
        cash, fills, fees, slippage, turnover = self._cash, [], ZERO, ZERO, ZERO
        for buy, s, amount, execution, gross in sorted(proposals):
            charge = _mul(gross, fee)
            reference = _mul(amount, parsed[s])
            drag = _mul(reference, slip)
            cash = _add(cash, _neg(_add(gross, charge)) if buy else _add(gross, _neg(charge)))
            if cash < ZERO:
                raise WalletError("Fee/slippage/rounding would produce negative cash")
            fees, slippage, turnover = _add(fees, charge), _add(slippage, drag), _add(turnover, reference)
            fills.append(dict(symbol=s, side="buy" if buy else "sell", quantity=str(amount),
                              reference_price=str(parsed[s]), fill_price=str(execution),
                              gross=str(gross), fee=str(charge), slippage=str(drag),
                              cash_after=str(cash), timestamp=timestamp))
        positions = {s: q for s, q in targets.items() if q > ZERO}
        post = self._value(parsed, cash, positions)
        if post != _add(pre, _neg(fees), _neg(slippage)):
            raise WalletError("Self-financing accounting identity failed")
        peak, dd = self._risk(pre, post)
        report = dict(kind="rebalance", timestamp=timestamp, pre_nav=str(pre), post_nav=str(post),
                      nav=str(post), cash_before=str(self._cash), cash_after=str(cash), cash=str(cash),
                      positions={s: str(q) for s, q in positions.items()},
                      target_weights={s: str(w) for s, w in weights.items()},
                      target_quantities={s: str(q) for s, q in targets.items()},
                      continuous_target_nav=str(target_nav), rounding=rounding,
                      cash_residual=str(cash), fees=str(fees), slippage=str(slippage),
                      traded_reference_notional=str(turnover), fills=fills,
                      min_notional_basis="adverse_executed_gross",
                      peak_nav=str(peak), max_drawdown=str(dd), paper_only=True,
                      live_enabled=False, orders=0)
        self._cash, self._positions = cash, positions
        self._peak, self._drawdown = peak, dd
        self._commit_clock(timestamp, parsed)
        self._journal.append(deepcopy(report))
        return report
