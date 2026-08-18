from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from deterministic_risk import RiskDecision, evaluate_risk
from paper_event_store import GENESIS_DIGEST, PortfolioState, build_event, replay, validate_event
from paper_execution import PaperExecutionError, execute_paper_command

PRODUCT_CONTRACT_VERSION = "nexus.product-runtime.v2"
PAPER_ACCOUNT_ID = "nexus-demo-paper"
PAPER_CURRENCY = "USDT"
PAPER_SUPPORTED_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
PAPER_SUPPORTED_TIMEFRAMES = ("minute15", "hour1", "hour4")
PAPER_DEFAULT_FEE_RATE = "0.001"
PAPER_DEFAULT_SLIPPAGE_BPS = "5"
MAX_PAPER_EVENTS = 100_000
ORDER_KEYS = {
    "operation", "symbol", "timeframe", "side", "quantity",
    "reference_price", "stop_price", "target_price",
}


class ProductRuntimeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, tuple): return [_json_safe(item) for item in value]
    if isinstance(value, list): return [_json_safe(item) for item in value]
    if isinstance(value, dict): return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def serialize_portfolio(state: PortfolioState) -> dict[str, Any]:
    raw = _json_safe(asdict(state))
    return {
        "aggregate_id": raw["aggregate_id"], "currency": raw["currency"],
        "cash": raw["cash"], "equity": raw["equity"],
        "realized_pnl": raw["realized_pnl"], "unrealized_pnl": raw["unrealized_pnl"],
        "positions": [
            {"symbol": row[0], "side": row[1], "quantity": row[2], "entry_price": row[3]}
            for row in raw["positions"]
        ],
        "stops": [{"symbol": row[0], "price": row[1]} for row in raw["stops"]],
        "targets": [{"symbol": row[0], "price": row[1]} for row in raw["targets"]],
        "kill_switch_enabled": raw["kill_switch_enabled"],
        "session_open": raw["session_open"],
        "last_sequence": raw["last_sequence"],
        "last_event_digest": raw["last_event_digest"],
    }


def _paper_provenance(*, timeframe: str, at: str) -> dict[str, Any]:
    return {
        "kind": "manual", "source_id": "nexus-product-paper-terminal",
        "source_timestamp": at, "received_timestamp": at, "timeframe": timeframe,
        "confidence": "1", "strategy_version": "manual-paper-v1",
        "policy_version": "product-paper-risk-v1",
    }


def _risk_policy() -> dict[str, Any]:
    return {
        "policy_id": "nexus-product-paper-risk", "policy_version": "1.0.0",
        "max_position_fraction": "0.10", "max_aggregate_fraction": "0.30",
        "max_daily_loss_fraction": "0.05", "max_drawdown_fraction": "0.10",
        "max_signals_per_session": 100, "max_signal_age_seconds": 300,
        "min_stop_distance_fraction": "0.001", "max_stop_distance_fraction": "0.20",
        "min_target_distance_fraction": "0.001",
        "supported_symbols": list(PAPER_SUPPORTED_SYMBOLS),
        "supported_timeframes": list(PAPER_SUPPORTED_TIMEFRAMES),
        "eligible_strategies": [{"id": "manual-paper", "version": "1.0.0"}],
    }


def _position_exposure(state: PortfolioState, symbol: str | None = None) -> Decimal:
    total = Decimal("0")
    for item_symbol, _side, quantity, entry in state.positions:
        if symbol is None or item_symbol == symbol: total += quantity * entry
    return total


def _session_signal_count(events: list[Mapping[str, Any]]) -> int:
    """Count actual proposals in the current Paper session, not journal records."""
    start = 0
    session_open = False
    for index, event in enumerate(events):
        if event.get("event_type") == "session_boundary_recorded":
            boundary = event.get("payload", {}).get("boundary")
            session_open = boundary == "open"
            start = index + 1
    if not session_open:
        return 0
    count = 0
    for event in events[start:]:
        kind = event.get("event_type")
        if kind == "signal_recorded":
            count += 1
        elif kind == "risk_decision_recorded" and event.get("provenance", {}).get("kind") == "manual":
            count += 1
    return count


def _risk_state(state: PortfolioState, *, symbol: str, signals_today: int = 0) -> dict[str, Any]:
    if isinstance(signals_today, bool) or not isinstance(signals_today, int) or signals_today < 0:
        raise ProductRuntimeError("signals_today must be a non-negative integer")
    return {
        "equity": str(state.equity),
        "daily_start_equity": str(max(state.equity - state.realized_pnl, Decimal("0.00000001"))),
        "daily_realized_pnl": str(state.realized_pnl),
        "current_exposure": str(_position_exposure(state)),
        "position_exposure": str(_position_exposure(state, symbol)),
        "session_open": state.session_open,
        "signals_today": signals_today,
        "seen_signal_ids": [],
        "kill_switch": state.kill_switch_enabled,
        "data_circuit_open": False,
        "strategy_circuit_open": False,
        "provider_circuit_open": False,
    }


def _risk_reducing_exit(*, state: PortfolioState, signal_id: str, symbol: str, side: str, quantity: str, reference_price: str) -> RiskDecision:
    requested_qty = Decimal(quantity)
    reference = Decimal(reference_price)
    position = next((row for row in state.positions if row[0] == symbol), None)
    allowed = bool(
        position and position[1] == side and requested_qty > 0 and requested_qty <= position[2]
        and reference > 0 and state.session_open and not state.kill_switch_enabled
    )
    proposed = requested_qty * reference if requested_qty > 0 and reference > 0 else Decimal("0")
    resulting = max(_position_exposure(state) - proposed, Decimal("0"))
    return RiskDecision(
        allowed=allowed,
        reason_code="risk_reducing_exit" if allowed else "risk_reducing_exit_denied",
        policy_id="nexus-product-paper-risk", policy_version="1.0.0",
        signal_id=signal_id, proposed_notional=proposed, resulting_exposure=resulting,
    )


class ProductRuntime:
    """Durable local Paper state. There is no live-money authority in this runtime."""

    def __init__(self, root: Path, *, opening_cash: str = "10000") -> None:
        self.root = Path(root)
        self.runtime_dir = self.root / "product_runtime"
        self.paper_events_path = self.runtime_dir / "paper-events.jsonl"
        self.opening_cash = str(Decimal(opening_cash))
        self._lock = threading.RLock()
        # Establish the journal clock boundary immediately so every downstream
        # automated event is necessarily ordered after account/session bootstrap.
        with self._lock:
            self._ensure_account()

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.paper_events_path.exists(): return []
        events: list[dict[str, Any]] = []
        try:
            with self.paper_events_path.open("r", encoding="utf-8") as handle:
                for index, line in enumerate(handle, start=1):
                    if index > MAX_PAPER_EVENTS: raise ProductRuntimeError("paper event journal exceeds bounded limit")
                    if not line.strip(): raise ProductRuntimeError("paper event journal contains blank record")
                    value = json.loads(line)
                    if not isinstance(value, dict): raise ProductRuntimeError("paper event journal record is not an object")
                    events.append(validate_event(value))
            replay(events)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ProductRuntimeError("paper event journal is corrupt or unavailable") from exc
        return events

    def _write_events(self, events: list[dict[str, Any]]) -> None:
        if len(events) > MAX_PAPER_EVENTS: raise ProductRuntimeError("paper event journal exceeds bounded limit")
        replay(events)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.paper_events_path.with_suffix(".tmp")
        content = "".join(json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n" for event in events)
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, self.paper_events_path)
        except OSError as exc:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
            raise ProductRuntimeError("failed to persist paper event journal atomically") from exc

    def _ensure_account(self) -> list[dict[str, Any]]:
        events = self._read_events()
        if events: return events
        at = _utc_now(); provenance = _paper_provenance(timeframe="session", at=at)
        account = build_event(
            event_id="product:account:1", event_type="demo_account_opened", aggregate_id=PAPER_ACCOUNT_ID,
            sequence=1, occurred_at=at, correlation_id="product-bootstrap",
            causation_id="product-bootstrap-account", provenance=provenance,
            previous_event_digest=GENESIS_DIGEST,
            payload={"currency": PAPER_CURRENCY, "opening_cash": self.opening_cash},
        )
        session = build_event(
            event_id="product:account:2", event_type="session_boundary_recorded", aggregate_id=PAPER_ACCOUNT_ID,
            sequence=2, occurred_at=at, correlation_id="product-bootstrap",
            causation_id="product-bootstrap-session", provenance=provenance,
            previous_event_digest=account["event_digest"], payload={"boundary": "open"},
        )
        events = [account, session]; self._write_events(events); return events

    def paper_snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = self._ensure_account(); state = replay(events).state
            return {
                "contract_version": PRODUCT_CONTRACT_VERSION, "mode": "paper", "paper_only": True,
                "live_trading_authority": False, "active": True, "account": serialize_portfolio(state),
                "event_count": len(events), "session_signal_count": _session_signal_count(events),
                "head_event_digest": state.last_event_digest,
                "supported_symbols": list(PAPER_SUPPORTED_SYMBOLS),
                "supported_timeframes": list(PAPER_SUPPORTED_TIMEFRAMES),
                "supported_operations": ["open", "close", "reduce", "reverse"],
                "fee_rate": PAPER_DEFAULT_FEE_RATE, "slippage_bps": PAPER_DEFAULT_SLIPPAGE_BPS,
            }

    def paper_events(self, *, limit: int = 200) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ProductRuntimeError("paper event limit must be between 1 and 1000")
        with self._lock:
            events = self._ensure_account()
            return {"contract_version": PRODUCT_CONTRACT_VERSION, "paper_only": True, "events": events[-limit:], "total": len(events)}

    def submit_paper_order(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping) or set(request) != ORDER_KEYS: raise ProductRuntimeError("paper order schema mismatch")
        operation = str(request["operation"]); symbol = str(request["symbol"]).upper(); timeframe = str(request["timeframe"]); side = str(request["side"])
        if operation not in {"open", "close", "reduce", "reverse"}: raise ProductRuntimeError("unsupported paper operation")
        if symbol not in PAPER_SUPPORTED_SYMBOLS: raise ProductRuntimeError("unsupported paper symbol")
        if timeframe not in PAPER_SUPPORTED_TIMEFRAMES: raise ProductRuntimeError("unsupported paper timeframe")
        if side not in {"long", "short"}: raise ProductRuntimeError("unsupported paper side")
        for name in ("quantity", "reference_price", "stop_price", "target_price"):
            value = request[name]
            if isinstance(value, float): raise ProductRuntimeError(f"{name} must not use binary floating point")
            try: numeric = Decimal(str(value))
            except Exception as exc: raise ProductRuntimeError(f"{name} is not a valid decimal") from exc
            if not numeric.is_finite() or numeric <= 0: raise ProductRuntimeError(f"{name} must be positive")

        with self._lock:
            events = self._ensure_account(); state = replay(events).state; at = _utc_now()
            signal_id = f"paper:{uuid.uuid4().hex}"; correlation_id = f"product:{uuid.uuid4().hex}"
            provenance = _paper_provenance(timeframe=timeframe, at=at)
            quantity = str(request["quantity"]); reference_price = str(request["reference_price"])
            stop_price = str(request["stop_price"]); target_price = str(request["target_price"])
            if operation in {"close", "reduce"}:
                risk = _risk_reducing_exit(state=state, signal_id=signal_id, symbol=symbol, side=side, quantity=quantity, reference_price=reference_price)
            else:
                signal = {
                    "signal_id": signal_id, "symbol": symbol, "timeframe": timeframe,
                    "strategy_id": "manual-paper", "strategy_version": "1.0.0", "side": side,
                    "quantity": quantity, "reference_price": reference_price, "stop_price": stop_price,
                    "target_price": target_price, "source_timestamp": at, "correlation_id": correlation_id,
                    "causation_id": signal_id, "provenance_kind": "manual",
                }
                risk = evaluate_risk(
                    signal,
                    _risk_state(state, symbol=symbol, signals_today=_session_signal_count(events)),
                    _risk_policy(),
                    evaluated_at=at,
                )
            if not risk.allowed:
                return {
                    "contract_version": PRODUCT_CONTRACT_VERSION, "paper_only": True, "accepted": False,
                    "risk": _json_safe(asdict(risk)), "account": serialize_portfolio(state),
                }
            command = {
                "operation": operation, "symbol": symbol, "side": side, "quantity": quantity,
                "reference_price": reference_price, "stop_price": stop_price, "target_price": target_price,
                "fee_rate": PAPER_DEFAULT_FEE_RATE, "slippage_bps": PAPER_DEFAULT_SLIPPAGE_BPS,
                "currency": PAPER_CURRENCY,
            }
            try:
                result = execute_paper_command(
                    command=command, state=state, risk_decision=risk, occurred_at=at,
                    provenance=provenance, correlation_id=correlation_id, causation_id=signal_id,
                )
            except PaperExecutionError as exc:
                raise ProductRuntimeError(str(exc)) from exc
            updated = [*events, *result.events]; self._write_events(updated)
            return {
                "contract_version": PRODUCT_CONTRACT_VERSION, "paper_only": True, "accepted": True,
                "risk": _json_safe(asdict(risk)),
                "execution": {
                    "fill_price": str(result.fill_price), "fee": str(result.fee),
                    "slippage_cost": str(result.slippage_cost), "realized_pnl": str(result.realized_pnl),
                    "event_count": len(result.events),
                },
                "account": serialize_portfolio(result.state),
            }

    def live_surface(self) -> dict[str, Any]:
        return {
            "contract_version": PRODUCT_CONTRACT_VERSION, "mode": "live",
            "status": "locked_owner_controlled", "enabled": False,
            "live_trading_authority": False, "exchange_credentials_configured": False,
            "orders_allowed": False, "withdrawals_allowed": False,
            "production_promotion_allowed": False,
            "reason": "Live/Main trading is outside the current NEXUS authority contract and requires a future explicit owner-controlled stage.",
        }
