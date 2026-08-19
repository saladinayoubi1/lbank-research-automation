from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any, Mapping


MODEL_VERSION = "nexus.paper-futures-model.v1"
POSITION_KEYS = {
    "symbol",
    "side",
    "quantity",
    "entry_price",
    "leverage",
    "maintenance_margin_rate",
    "collateral",
}
MARKET_KEYS = {"mark_price", "funding_rate", "funding_intervals"}
MONEY_QUANTUM = Decimal("0.00000001")
MAX_LEVERAGE = 100
MAX_ABS_FUNDING_RATE = Decimal("0.01")
MAX_FUNDING_INTERVALS = 10_000


class PaperFuturesModelError(ValueError):
    pass


@dataclass(frozen=True)
class PaperFuturesSnapshot:
    model_version: str
    symbol: str
    side: str
    quantity: Decimal
    entry_price: Decimal
    mark_price: Decimal
    leverage: int
    maintenance_margin_rate: Decimal
    collateral: Decimal
    entry_notional: Decimal
    mark_notional: Decimal
    initial_margin: Decimal
    maintenance_margin: Decimal
    unrealized_pnl: Decimal
    funding_cashflow: Decimal
    equity: Decimal
    margin_buffer: Decimal
    liquidation_triggered: bool
    reason_code: str
    paper_trading_only: bool = True


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise PaperFuturesModelError(f"{field} must not use binary floating point")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperFuturesModelError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise PaperFuturesModelError(f"{field} must be finite")
    if positive and parsed <= 0:
        raise PaperFuturesModelError(f"{field} must be positive")
    return parsed


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def _bounded_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise PaperFuturesModelError(f"{field} must be a bounded identifier")
    return value


def _validate_position(position: Any) -> dict[str, Any]:
    if not isinstance(position, Mapping) or set(position) != POSITION_KEYS:
        raise PaperFuturesModelError("paper futures position schema mismatch")
    side = position["side"]
    if side not in {"long", "short"}:
        raise PaperFuturesModelError("side must be long or short")
    leverage = position["leverage"]
    if isinstance(leverage, bool) or not isinstance(leverage, int):
        raise PaperFuturesModelError("leverage must be an integer")
    if leverage < 1 or leverage > MAX_LEVERAGE:
        raise PaperFuturesModelError("leverage outside bounded paper range")

    quantity = _decimal(position["quantity"], "quantity", positive=True)
    entry_price = _decimal(position["entry_price"], "entry_price", positive=True)
    maintenance_margin_rate = _decimal(
        position["maintenance_margin_rate"], "maintenance_margin_rate"
    )
    collateral = _decimal(position["collateral"], "collateral", positive=True)
    if maintenance_margin_rate < 0:
        raise PaperFuturesModelError("maintenance_margin_rate must be non-negative")
    if maintenance_margin_rate >= Decimal("1") / Decimal(leverage):
        raise PaperFuturesModelError(
            "maintenance_margin_rate must remain below initial margin rate"
        )

    entry_notional = _money(quantity * entry_price)
    initial_margin = _money(entry_notional / Decimal(leverage))
    if collateral < initial_margin:
        raise PaperFuturesModelError("collateral is below required initial margin")

    return {
        "symbol": _bounded_identifier(position["symbol"], "symbol"),
        "side": side,
        "quantity": quantity,
        "entry_price": entry_price,
        "leverage": leverage,
        "maintenance_margin_rate": maintenance_margin_rate,
        "collateral": collateral,
        "entry_notional": entry_notional,
        "initial_margin": initial_margin,
    }


def _validate_market(market: Any) -> dict[str, Any]:
    if not isinstance(market, Mapping) or set(market) != MARKET_KEYS:
        raise PaperFuturesModelError("paper futures market schema mismatch")
    mark_price = _decimal(market["mark_price"], "mark_price", positive=True)
    funding_rate = _decimal(market["funding_rate"], "funding_rate")
    if abs(funding_rate) > MAX_ABS_FUNDING_RATE:
        raise PaperFuturesModelError("funding_rate outside bounded paper range")
    funding_intervals = market["funding_intervals"]
    if isinstance(funding_intervals, bool) or not isinstance(funding_intervals, int):
        raise PaperFuturesModelError("funding_intervals must be an integer")
    if funding_intervals < 0 or funding_intervals > MAX_FUNDING_INTERVALS:
        raise PaperFuturesModelError("funding_intervals outside bounded paper range")
    return {
        "mark_price": mark_price,
        "funding_rate": funding_rate,
        "funding_intervals": funding_intervals,
    }


def evaluate_paper_futures_position(
    *, position: Mapping[str, Any], market: Mapping[str, Any]
) -> PaperFuturesSnapshot:
    """Evaluate one bounded isolated-margin Paper futures position deterministically.

    The model is intentionally exchange-neutral and Paper-only. It models leverage,
    maintenance margin, mark-to-market PnL and funding cashflow without any network,
    credential, exchange-order or authority surface. Liquidation is a deterministic
    threshold condition: account equity at the supplied mark is less than or equal to
    maintenance margin.
    """
    position = _validate_position(position)
    market = _validate_market(market)

    mark_notional = _money(position["quantity"] * market["mark_price"])
    maintenance_margin = _money(mark_notional * position["maintenance_margin_rate"])
    if position["side"] == "long":
        unrealized = _money(
            (market["mark_price"] - position["entry_price"]) * position["quantity"]
        )
        funding_cashflow = _money(
            -mark_notional
            * market["funding_rate"]
            * Decimal(market["funding_intervals"])
        )
    else:
        unrealized = _money(
            (position["entry_price"] - market["mark_price"]) * position["quantity"]
        )
        funding_cashflow = _money(
            mark_notional
            * market["funding_rate"]
            * Decimal(market["funding_intervals"])
        )

    equity = _money(position["collateral"] + unrealized + funding_cashflow)
    margin_buffer = _money(equity - maintenance_margin)
    liquidation_triggered = margin_buffer <= 0
    reason_code = (
        "LIQUIDATION_THRESHOLD_BREACHED"
        if liquidation_triggered
        else "MARGIN_HEALTHY"
    )

    return PaperFuturesSnapshot(
        model_version=MODEL_VERSION,
        symbol=position["symbol"],
        side=position["side"],
        quantity=position["quantity"],
        entry_price=position["entry_price"],
        mark_price=market["mark_price"],
        leverage=position["leverage"],
        maintenance_margin_rate=position["maintenance_margin_rate"],
        collateral=position["collateral"],
        entry_notional=position["entry_notional"],
        mark_notional=mark_notional,
        initial_margin=position["initial_margin"],
        maintenance_margin=maintenance_margin,
        unrealized_pnl=unrealized,
        funding_cashflow=funding_cashflow,
        equity=equity,
        margin_buffer=margin_buffer,
        liquidation_triggered=liquidation_triggered,
        reason_code=reason_code,
    )
