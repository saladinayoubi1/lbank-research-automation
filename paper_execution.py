from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any, Mapping, Sequence

from deterministic_risk import RiskDecision
from paper_event_store import PortfolioState, build_event, replay

COMMAND_KEYS = {
    "operation", "symbol", "side", "quantity", "reference_price", "stop_price",
    "target_price", "fee_rate", "slippage_bps", "currency",
}
MAX_SLIPPAGE_BPS = Decimal("100")
PRICE_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.00000001")


class PaperExecutionError(ValueError):
    pass


@dataclass(frozen=True)
class PaperExecutionResult:
    events: tuple[dict[str, Any], ...]
    state: PortfolioState
    fill_price: Decimal
    fee: Decimal
    slippage_cost: Decimal
    realized_pnl: Decimal


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise PaperExecutionError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PaperExecutionError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise PaperExecutionError(f"{field} must be finite")
    if positive and result <= 0:
        raise PaperExecutionError(f"{field} must be positive")
    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_EVEN)


def _price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _position(state: PortfolioState, symbol: str) -> tuple[str, Decimal, Decimal] | None:
    for item_symbol, side, quantity, entry in state.positions:
        if item_symbol == symbol:
            return side, quantity, entry
    return None


def _validate_command(command: Any) -> Mapping[str, Any]:
    if not isinstance(command, Mapping) or set(command) != COMMAND_KEYS:
        raise PaperExecutionError("paper command schema mismatch")
    if command["operation"] not in {"open", "close", "reduce", "reverse"}:
        raise PaperExecutionError("unsupported paper operation")
    if command["side"] not in {"long", "short"}:
        raise PaperExecutionError("unsupported position side")
    for field in ("symbol", "currency"):
        if not isinstance(command[field], str) or not command[field] or len(command[field]) > 64:
            raise PaperExecutionError(f"{field} must be a bounded identifier")
    quantity = _decimal(command["quantity"], "quantity", positive=True)
    reference = _decimal(command["reference_price"], "reference_price", positive=True)
    stop = _decimal(command["stop_price"], "stop_price", positive=True)
    target = _decimal(command["target_price"], "target_price", positive=True)
    fee_rate = _decimal(command["fee_rate"], "fee_rate")
    slippage = _decimal(command["slippage_bps"], "slippage_bps")
    if fee_rate < 0 or fee_rate > Decimal("0.01"):
        raise PaperExecutionError("fee_rate outside bounded paper range")
    if slippage < 0 or slippage > MAX_SLIPPAGE_BPS:
        raise PaperExecutionError("slippage_bps outside bounded paper range")
    if command["operation"] in {"open", "reverse"}:
        if command["side"] == "long" and not (stop < reference < target):
            raise PaperExecutionError("invalid long protective prices")
        if command["side"] == "short" and not (target < reference < stop):
            raise PaperExecutionError("invalid short protective prices")
    return {
        **command,
        "quantity": quantity,
        "reference_price": reference,
        "stop_price": stop,
        "target_price": target,
        "fee_rate": fee_rate,
        "slippage_bps": slippage,
    }


def _append(
    events: list[dict[str, Any]],
    state: PortfolioState,
    *,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: str,
    provenance: dict[str, Any],
    correlation_id: str,
    causation_id: str,
) -> PortfolioState:
    previous = events[-1]["event_digest"] if events else state.last_event_digest
    sequence = state.last_sequence + len(events) + 1
    event = build_event(
        event_id=f"{correlation_id}:{sequence}:{event_type}",
        event_type=event_type,
        aggregate_id=state.aggregate_id or "paper-account",
        sequence=sequence,
        occurred_at=occurred_at,
        correlation_id=correlation_id,
        causation_id=causation_id,
        provenance=provenance,
        previous_event_digest=previous,
        payload=payload,
    )
    events.append(event)
    return state


def execute_paper_command(
    *,
    command: Mapping[str, Any],
    state: PortfolioState,
    risk_decision: RiskDecision,
    occurred_at: str,
    provenance: dict[str, Any],
    correlation_id: str,
    causation_id: str,
) -> PaperExecutionResult:
    command = _validate_command(command)
    if state.aggregate_id is None or state.currency is None:
        raise PaperExecutionError("demo account must exist before execution")
    if state.kill_switch_enabled or not state.session_open:
        raise PaperExecutionError("paper execution is blocked by portfolio controls")
    if command["currency"] != state.currency:
        raise PaperExecutionError("currency mismatch")
    if not isinstance(risk_decision, RiskDecision) or not risk_decision.allowed:
        raise PaperExecutionError("deterministic risk approval is required")
    if risk_decision.signal_id != causation_id:
        raise PaperExecutionError("risk approval causation mismatch")
    expected_notional = command["quantity"] * command["reference_price"]
    if risk_decision.proposed_notional != expected_notional:
        raise PaperExecutionError("risk approval amount mismatch")

    operation = str(command["operation"])
    symbol = str(command["symbol"])
    side = str(command["side"])
    quantity = command["quantity"]
    reference = command["reference_price"]
    current = _position(state, symbol)
    if operation == "open" and current is not None:
        raise PaperExecutionError("cannot open an existing position")
    if operation in {"close", "reduce", "reverse"} and current is None:
        raise PaperExecutionError("paper operation requires an existing position")
    if current is not None and operation in {"close", "reduce"} and current[0] != side:
        raise PaperExecutionError("position side mismatch")
    if operation == "reduce" and quantity >= current[1]:
        raise PaperExecutionError("reduce quantity must be smaller than position")
    if operation == "close" and quantity != current[1]:
        raise PaperExecutionError("close quantity must equal position")
    if operation == "reverse" and current[0] == side:
        raise PaperExecutionError("reverse must change position side")
    if operation == "reverse" and quantity != current[1]:
        raise PaperExecutionError("reverse quantity must equal position")

    is_buy = (operation in {"open", "reverse"} and side == "long") or (
        operation in {"close", "reduce"} and side == "short"
    )
    slip_fraction = command["slippage_bps"] / Decimal("10000")
    fill = _price(reference * (Decimal("1") + slip_fraction if is_buy else Decimal("1") - slip_fraction))
    notional = _money(quantity * fill)
    fee = _money(notional * command["fee_rate"])
    slippage_cost = _money(abs(fill - reference) * quantity)
    realized = Decimal("0")
    if current is not None:
        current_side, _, entry = current
        realized = _money(
            (fill - entry) * quantity if current_side == "long" else (entry - fill) * quantity
        )

    events: list[dict[str, Any]] = []
    common = {
        "occurred_at": occurred_at,
        "provenance": provenance,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
    }
    _append(events, state, event_type="order_intent_recorded", payload={
        "symbol": symbol, "side": side, "quantity": str(quantity), "order_type": f"paper_{operation}",
    }, **common)
    _append(events, state, event_type="risk_decision_recorded", payload={
        "decision": "allow", "reason_code": risk_decision.reason_code,
    }, **common)
    _append(events, state, event_type="simulated_fill_recorded", payload={
        "symbol": symbol, "side": side, "quantity": str(quantity), "price": str(fill),
    }, **common)

    if operation == "open":
        transition_type = "position_opened"
        transition_payload = {
            "symbol": symbol, "side": side, "quantity": str(quantity), "entry_price": str(fill),
        }
    elif operation == "reduce":
        transition_type = "position_reduced"
        transition_payload = {
            "symbol": symbol, "quantity": str(quantity), "exit_price": str(fill),
            "realized_pnl": str(realized),
        }
    elif operation == "close":
        transition_type = "position_closed"
        transition_payload = {
            "symbol": symbol, "exit_price": str(fill), "realized_pnl": str(realized),
        }
    else:
        transition_type = "position_reversed"
        transition_payload = {
            "symbol": symbol, "side": side, "quantity": str(quantity),
            "entry_price": str(fill), "realized_pnl": str(realized),
        }
    _append(events, state, event_type=transition_type, payload=transition_payload, **common)

    if operation in {"open", "reverse"}:
        _append(events, state, event_type="stop_set", payload={
            "symbol": symbol, "price": str(command["stop_price"]),
        }, **common)
        _append(events, state, event_type="target_set", payload={
            "symbol": symbol, "price": str(command["target_price"]),
        }, **common)

    _append(events, state, event_type="fee_recorded", payload={
        "amount": str(fee), "currency": state.currency,
    }, **common)
    _append(events, state, event_type="slippage_recorded", payload={
        "amount": str(slippage_cost), "currency": state.currency,
    }, **common)

    resulting_cash = _money(state.cash + realized - fee - slippage_cost)
    resulting_equity = _money(state.equity + realized - fee - slippage_cost)
    _append(events, state, event_type="equity_snapshot_recorded", payload={
        "cash": str(resulting_cash), "equity": str(resulting_equity),
        "unrealized_pnl": str(state.unrealized_pnl),
    }, **common)

    reconstructed = replay(events, previous_valid=state).state
    return PaperExecutionResult(
        events=tuple(events),
        state=reconstructed,
        fill_price=fill,
        fee=fee,
        slippage_cost=slippage_cost,
        realized_pnl=realized,
    )
