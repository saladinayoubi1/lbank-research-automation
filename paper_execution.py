from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from typing import Any, Mapping

from deterministic_risk import RiskDecision
from paper_event_store import PortfolioState, build_event, replay
from paper_exchange_simulator import PaperExchangeSimulationError, simulate_paper_order

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
    execution_status: str = "FILLED"
    filled_quantity: Decimal = Decimal("0")
    remaining_quantity: Decimal = Decimal("0")


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
    execution_profile: Mapping[str, Any] | None = None,
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
    requested_quantity = command["quantity"]
    reference = command["reference_price"]
    current = _position(state, symbol)
    if operation == "open" and current is not None:
        raise PaperExecutionError("cannot open an existing position")
    if operation in {"close", "reduce", "reverse"} and current is None:
        raise PaperExecutionError("paper operation requires an existing position")
    if current is not None and operation in {"close", "reduce"} and current[0] != side:
        raise PaperExecutionError("position side mismatch")
    if operation == "reduce" and requested_quantity >= current[1]:
        raise PaperExecutionError("reduce quantity must be smaller than position")
    if operation == "close" and requested_quantity != current[1]:
        raise PaperExecutionError("close quantity must equal position")
    if operation == "reverse" and current[0] == side:
        raise PaperExecutionError("reverse must change position side")
    if operation == "reverse" and requested_quantity != current[1]:
        raise PaperExecutionError("reverse quantity must equal position")

    is_buy = (operation in {"open", "reverse"} and side == "long") or (
        operation in {"close", "reduce"} and side == "short"
    )
    profile = execution_profile or {
        "latency_ms": 0,
        "per_fill_quantity": str(requested_quantity),
        "max_fills": 1,
    }
    try:
        simulation = simulate_paper_order(
            order={
                "order_id": correlation_id,
                "symbol": symbol,
                "side": "buy" if is_buy else "sell",
                "quantity": str(requested_quantity),
                "reference_price": str(reference),
                "fee_rate": str(command["fee_rate"]),
                "slippage_bps": str(command["slippage_bps"]),
            },
            profile=profile,
        )
    except PaperExchangeSimulationError as exc:
        raise PaperExecutionError(f"paper exchange simulation rejected: {exc}") from exc

    filled_quantity = simulation.filled_quantity
    if filled_quantity <= 0 or not simulation.fills:
        raise PaperExecutionError("paper exchange produced no executable fill")
    if operation == "reverse" and simulation.remaining_quantity != 0:
        raise PaperExecutionError("partial reverse is not supported; no state transition applied")

    # v1 simulator uses one deterministic price across bounded fill slices. Keep this
    # explicit so a future price-per-slice model cannot silently alter accounting.
    fill_prices = {fill.price for fill in simulation.fills}
    if len(fill_prices) != 1:
        raise PaperExecutionError("mixed fill prices require explicit weighted accounting")
    fill = simulation.fills[0].price
    fee = simulation.total_fee
    slippage_cost = simulation.total_slippage_cost
    realized = Decimal("0")
    if current is not None:
        current_side, _, entry = current
        realized = _money(
            (fill - entry) * filled_quantity if current_side == "long" else (entry - fill) * filled_quantity
        )

    events: list[dict[str, Any]] = []
    common = {
        "occurred_at": occurred_at,
        "provenance": provenance,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
    }
    _append(events, state, event_type="order_intent_recorded", payload={
        "symbol": symbol, "side": side, "quantity": str(requested_quantity), "order_type": f"paper_{operation}",
    }, **common)
    _append(events, state, event_type="risk_decision_recorded", payload={
        "decision": "allow", "reason_code": risk_decision.reason_code,
    }, **common)
    for simulated_fill in simulation.fills:
        _append(events, state, event_type="simulated_fill_recorded", payload={
            "symbol": symbol,
            "side": side,
            "quantity": str(simulated_fill.quantity),
            "price": str(simulated_fill.price),
        }, **common)

    if operation == "open":
        transition_type = "position_opened"
        transition_payload = {
            "symbol": symbol, "side": side, "quantity": str(filled_quantity), "entry_price": str(fill),
        }
    elif operation == "reduce":
        transition_type = "position_reduced"
        transition_payload = {
            "symbol": symbol, "quantity": str(filled_quantity), "exit_price": str(fill),
            "realized_pnl": str(realized),
        }
    elif operation == "close" and simulation.remaining_quantity == 0:
        transition_type = "position_closed"
        transition_payload = {
            "symbol": symbol, "exit_price": str(fill), "realized_pnl": str(realized),
        }
    elif operation == "close":
        transition_type = "position_reduced"
        transition_payload = {
            "symbol": symbol, "quantity": str(filled_quantity), "exit_price": str(fill),
            "realized_pnl": str(realized),
        }
    else:
        transition_type = "position_reversed"
        transition_payload = {
            "symbol": symbol, "side": side, "quantity": str(filled_quantity),
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
        execution_status=simulation.status,
        filled_quantity=filled_quantity,
        remaining_quantity=simulation.remaining_quantity,
    )
