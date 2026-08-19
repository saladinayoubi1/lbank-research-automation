from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any, Mapping


ORDER_KEYS = {
    "order_id",
    "symbol",
    "side",
    "quantity",
    "reference_price",
    "fee_rate",
    "slippage_bps",
}
PROFILE_KEYS = {"latency_ms", "per_fill_quantity", "max_fills"}
PRICE_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.00000001")
MAX_SLIPPAGE_BPS = Decimal("100")
MAX_LATENCY_MS = 60_000
MAX_FILLS = 32


class PaperExchangeSimulationError(ValueError):
    pass


@dataclass(frozen=True)
class SimulatedFill:
    fill_id: str
    order_id: str
    fill_index: int
    side: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    slippage_cost: Decimal
    latency_ms: int
    paper_trading_only: bool = True


@dataclass(frozen=True)
class PaperExchangeSimulationResult:
    order_id: str
    status: str
    requested_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal
    fills: tuple[SimulatedFill, ...]
    total_fee: Decimal
    total_slippage_cost: Decimal
    paper_trading_only: bool = True


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise PaperExchangeSimulationError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperExchangeSimulationError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise PaperExchangeSimulationError(f"{field} must be finite")
    if positive and result <= 0:
        raise PaperExchangeSimulationError(f"{field} must be positive")
    return result


def _bounded_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise PaperExchangeSimulationError(f"{field} must be a bounded identifier")
    return value


def _price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def _validate_order(order: Any) -> dict[str, Any]:
    if not isinstance(order, Mapping) or set(order) != ORDER_KEYS:
        raise PaperExchangeSimulationError("paper exchange order schema mismatch")
    side = order["side"]
    if side not in {"buy", "sell"}:
        raise PaperExchangeSimulationError("side must be buy or sell")
    quantity = _decimal(order["quantity"], "quantity", positive=True)
    reference = _decimal(order["reference_price"], "reference_price", positive=True)
    fee_rate = _decimal(order["fee_rate"], "fee_rate")
    slippage = _decimal(order["slippage_bps"], "slippage_bps")
    if fee_rate < 0 or fee_rate > Decimal("0.01"):
        raise PaperExchangeSimulationError("fee_rate outside bounded paper range")
    if slippage < 0 or slippage > MAX_SLIPPAGE_BPS:
        raise PaperExchangeSimulationError("slippage_bps outside bounded paper range")
    return {
        "order_id": _bounded_identifier(order["order_id"], "order_id"),
        "symbol": _bounded_identifier(order["symbol"], "symbol"),
        "side": side,
        "quantity": quantity,
        "reference_price": reference,
        "fee_rate": fee_rate,
        "slippage_bps": slippage,
    }


def _validate_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, Mapping) or set(profile) != PROFILE_KEYS:
        raise PaperExchangeSimulationError("paper exchange profile schema mismatch")
    latency_ms = profile["latency_ms"]
    max_fills = profile["max_fills"]
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, int):
        raise PaperExchangeSimulationError("latency_ms must be an integer")
    if latency_ms < 0 or latency_ms > MAX_LATENCY_MS:
        raise PaperExchangeSimulationError("latency_ms outside bounded paper range")
    if isinstance(max_fills, bool) or not isinstance(max_fills, int):
        raise PaperExchangeSimulationError("max_fills must be an integer")
    if max_fills < 1 or max_fills > MAX_FILLS:
        raise PaperExchangeSimulationError("max_fills outside bounded paper range")
    per_fill = _decimal(profile["per_fill_quantity"], "per_fill_quantity", positive=True)
    return {
        "latency_ms": latency_ms,
        "per_fill_quantity": per_fill,
        "max_fills": max_fills,
    }


def simulate_paper_order(*, order: Mapping[str, Any], profile: Mapping[str, Any]) -> PaperExchangeSimulationResult:
    """Deterministically simulate bounded Paper-only fills for an already-approved order intent.

    The simulator has no exchange/network/credential adapter and cannot grant trading authority.
    `max_fills` intentionally allows a run to end PARTIALLY_FILLED with a replayable remainder.
    """
    order = _validate_order(order)
    profile = _validate_profile(profile)
    remaining = order["quantity"]
    fills: list[SimulatedFill] = []
    slip_fraction = order["slippage_bps"] / Decimal("10000")
    multiplier = Decimal("1") + slip_fraction if order["side"] == "buy" else Decimal("1") - slip_fraction
    fill_price = _price(order["reference_price"] * multiplier)

    for index in range(1, profile["max_fills"] + 1):
        if remaining <= 0:
            break
        fill_quantity = min(remaining, profile["per_fill_quantity"])
        notional = _money(fill_quantity * fill_price)
        fee = _money(notional * order["fee_rate"])
        slippage_cost = _money(abs(fill_price - order["reference_price"]) * fill_quantity)
        fills.append(
            SimulatedFill(
                fill_id=f"{order['order_id']}:fill:{index}",
                order_id=order["order_id"],
                fill_index=index,
                side=order["side"],
                quantity=fill_quantity,
                price=fill_price,
                fee=fee,
                slippage_cost=slippage_cost,
                latency_ms=profile["latency_ms"] * index,
            )
        )
        remaining -= fill_quantity

    filled = order["quantity"] - remaining
    status = "FILLED" if remaining == 0 else "PARTIALLY_FILLED"
    return PaperExchangeSimulationResult(
        order_id=order["order_id"],
        status=status,
        requested_quantity=order["quantity"],
        filled_quantity=filled,
        remaining_quantity=remaining,
        fills=tuple(fills),
        total_fee=_money(sum((fill.fee for fill in fills), Decimal("0"))),
        total_slippage_cost=_money(sum((fill.slippage_cost for fill in fills), Decimal("0"))),
    )
