from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

PAPER_SCHEMA = "nexus.phase5-paper-trading.v1"


class PaperTradingError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise PaperTradingError(f"{field} must be finite numeric evidence")
    return float(value)


def _digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def evaluate_paper_candidate(
    qualification: Mapping[str, Any],
    fills: Sequence[Mapping[str, Any]],
    *,
    initial_equity: float,
    minimum_days: int = 30,
    minimum_trades: int = 30,
    maximum_drawdown_pct: float = 20.0,
) -> dict[str, Any]:
    """Evaluate a paper-only strategy using live-like execution evidence.

    Each fill must contain timestamp_ms, side, quantity, mark_price, fill_price,
    fee, funding and realized_pnl. The caller is responsible for sourcing prices;
    this boundary only accepts explicit execution evidence and never routes orders.
    """
    if qualification.get("status") != "paper_candidate":
        raise PaperTradingError("only a qualified paper candidate may enter paper trading")
    if qualification.get("paper_only") is not True or qualification.get("live_execution_allowed") is not False:
        raise PaperTradingError("qualification widened authority beyond paper scope")
    equity = _finite(initial_equity, "initial_equity")
    if equity <= 0:
        raise PaperTradingError("initial_equity must be positive")
    if not isinstance(minimum_days, int) or minimum_days < 1:
        raise PaperTradingError("minimum_days must be a positive integer")
    if not isinstance(minimum_trades, int) or minimum_trades < 1:
        raise PaperTradingError("minimum_trades must be a positive integer")
    max_dd_limit = _finite(maximum_drawdown_pct, "maximum_drawdown_pct")
    if not 0 < max_dd_limit < 100:
        raise PaperTradingError("maximum_drawdown_pct must be between zero and 100")
    if not isinstance(fills, Sequence) or isinstance(fills, (str, bytes)):
        raise PaperTradingError("fills must be a sequence")

    normalized: list[dict[str, Any]] = []
    peak = equity
    max_drawdown = 0.0
    previous_timestamp = -1
    gross_pnl = fees = funding = slippage = 0.0
    for index, raw in enumerate(fills):
        if not isinstance(raw, Mapping):
            raise PaperTradingError(f"fill {index} must be a mapping")
        required = {"timestamp_ms", "side", "quantity", "mark_price", "fill_price", "fee", "funding", "realized_pnl"}
        if set(raw) != required:
            raise PaperTradingError(f"fill {index} schema mismatch")
        timestamp = raw["timestamp_ms"]
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= previous_timestamp:
            raise PaperTradingError("fill timestamps must be strictly increasing integers")
        previous_timestamp = timestamp
        side = raw["side"]
        if side not in {"buy", "sell"}:
            raise PaperTradingError("fill side must be buy or sell")
        quantity = _finite(raw["quantity"], "quantity")
        mark = _finite(raw["mark_price"], "mark_price")
        price = _finite(raw["fill_price"], "fill_price")
        fee = _finite(raw["fee"], "fee")
        funding_cost = _finite(raw["funding"], "funding")
        pnl = _finite(raw["realized_pnl"], "realized_pnl")
        if quantity <= 0 or mark <= 0 or price <= 0 or fee < 0:
            raise PaperTradingError("fill quantity/prices must be positive and fee non-negative")
        slip = abs(price - mark) * quantity
        gross_pnl += pnl
        fees += fee
        funding += funding_cost
        slippage += slip
        equity += pnl - fee - funding_cost - slip
        peak = max(peak, equity)
        drawdown = 100.0 * (peak - equity) / peak
        max_drawdown = max(max_drawdown, drawdown)
        normalized.append({
            "timestamp_ms": timestamp, "side": side, "quantity": quantity,
            "mark_price": mark, "fill_price": price, "fee": fee,
            "funding": funding_cost, "realized_pnl": pnl,
        })

    observed_ms = 0 if len(normalized) < 2 else normalized[-1]["timestamp_ms"] - normalized[0]["timestamp_ms"]
    observed_days = observed_ms / 86_400_000
    reasons: list[str] = []
    if len(normalized) < minimum_trades:
        reasons.append("INSUFFICIENT_TRADES")
    if observed_ms < minimum_days * 86_400_000:
        reasons.append("INSUFFICIENT_OBSERVATION_DAYS")
    if max_drawdown > max_dd_limit:
        reasons.append("DRAWDOWN_LIMIT_BREACHED")
    if equity <= 0:
        reasons.append("EQUITY_DEPLETED")

    core = {
        "schema_version": PAPER_SCHEMA,
        "qualification_digest": qualification.get("qualification_digest"),
        "strategy_version": qualification.get("strategy_version"),
        "paper_only": True,
        "live_execution_allowed": False,
        "status": "proved_in_paper" if not reasons else "observing" if set(reasons) <= {"INSUFFICIENT_TRADES", "INSUFFICIENT_OBSERVATION_DAYS"} else "rejected",
        "reasons": reasons,
        "trade_count": len(normalized),
        "observed_days": observed_days,
        "initial_equity": float(initial_equity),
        "ending_equity": equity,
        "gross_realized_pnl": gross_pnl,
        "fees": fees,
        "funding": funding,
        "slippage": slippage,
        "max_drawdown_pct": max_drawdown,
        "minimum_days": minimum_days,
        "minimum_trades": minimum_trades,
        "maximum_drawdown_pct": max_dd_limit,
        "fills_digest": _digest(normalized),
    }
    return {**core, "report_digest": _digest(core)}
