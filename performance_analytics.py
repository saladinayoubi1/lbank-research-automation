from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "nexus.phase7-performance-analytics.v1"
TRADE_KEYS = {
    "trade_id",
    "opened_at_ms",
    "closed_at_ms",
    "gross_pnl",
    "fees",
    "entry_notional",
    "exit_notional",
    "regime",
}
WINDOW_KEYS = {"window_id", "score", "parameters"}
ALLOWED_REGIMES = {"TREND_UP", "TREND_DOWN", "HIGH_VOLATILITY", "RANGE", "UNKNOWN"}
Q8 = Decimal("0.00000001")
Q6 = Decimal("0.000001")


class PerformanceAnalyticsError(ValueError):
    pass


def _decimal(value: Any, field: str, *, non_negative: bool = False) -> Decimal:
    if isinstance(value, float):
        raise PerformanceAnalyticsError(f"{field} must not use binary floating point")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PerformanceAnalyticsError(f"{field} is not a valid decimal") from exc
    if not result.is_finite():
        raise PerformanceAnalyticsError(f"{field} must be finite")
    if non_negative and result < 0:
        raise PerformanceAnalyticsError(f"{field} must be non-negative")
    return result


def _q(value: Decimal, quantum: Decimal = Q8) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PerformanceAnalyticsError("analytics evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise PerformanceAnalyticsError(f"{field} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise PerformanceAnalyticsError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _bounded_text(value: Any, field: str, limit: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise PerformanceAnalyticsError(f"{field} must be bounded non-empty text")
    return value


def _validate_trade(raw: Any, previous_close: int | None) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or set(raw) != TRADE_KEYS:
        raise PerformanceAnalyticsError("trade schema mismatch")
    trade_id = _bounded_text(raw["trade_id"], "trade_id")
    opened = raw["opened_at_ms"]
    closed = raw["closed_at_ms"]
    if (
        isinstance(opened, bool)
        or not isinstance(opened, int)
        or isinstance(closed, bool)
        or not isinstance(closed, int)
        or opened < 0
        or closed <= opened
    ):
        raise PerformanceAnalyticsError("trade timestamps are invalid")
    if previous_close is not None and closed <= previous_close:
        raise PerformanceAnalyticsError("trades must be strictly ordered by close time")
    regime = raw["regime"]
    if regime not in ALLOWED_REGIMES:
        raise PerformanceAnalyticsError("unsupported trade regime")
    gross = _decimal(raw["gross_pnl"], "gross_pnl")
    fees = _decimal(raw["fees"], "fees", non_negative=True)
    entry = _decimal(raw["entry_notional"], "entry_notional", non_negative=True)
    exit_ = _decimal(raw["exit_notional"], "exit_notional", non_negative=True)
    return {
        "trade_id": trade_id,
        "opened_at_ms": opened,
        "closed_at_ms": closed,
        "gross_pnl": gross,
        "fees": fees,
        "entry_notional": entry,
        "exit_notional": exit_,
        "regime": regime,
        "net_pnl": gross - fees,
    }


def _validate_windows(raw_windows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw_windows, Sequence) or isinstance(raw_windows, (str, bytes)):
        raise PerformanceAnalyticsError("evaluation_windows must be a sequence")
    if not raw_windows:
        return []
    if len(raw_windows) > 256:
        raise PerformanceAnalyticsError("evaluation_windows exceeds bounded limit")
    parameter_names: set[str] | None = None
    windows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_windows:
        if not isinstance(raw, Mapping) or set(raw) != WINDOW_KEYS:
            raise PerformanceAnalyticsError("evaluation window schema mismatch")
        window_id = _bounded_text(raw["window_id"], "window_id")
        if window_id in seen_ids:
            raise PerformanceAnalyticsError("duplicate evaluation window_id")
        seen_ids.add(window_id)
        score = _decimal(raw["score"], "score")
        params = raw["parameters"]
        if not isinstance(params, Mapping) or not params or len(params) > 64:
            raise PerformanceAnalyticsError("parameters must be a bounded non-empty mapping")
        names = set(params)
        if parameter_names is None:
            parameter_names = names
        elif names != parameter_names:
            raise PerformanceAnalyticsError("parameter names must match across windows")
        parsed_params: dict[str, Decimal] = {}
        for name in sorted(names):
            _bounded_text(name, "parameter name")
            parsed_params[name] = _decimal(params[name], f"parameters.{name}")
        windows.append({"window_id": window_id, "score": score, "parameters": parsed_params})
    return windows


def _sqrt(value: Decimal) -> Decimal:
    if value < 0:
        raise PerformanceAnalyticsError("cannot sqrt negative value")
    with localcontext() as ctx:
        ctx.prec = 40
        return value.sqrt()


def _drawdown(equity: Sequence[Decimal]) -> tuple[Decimal, int]:
    peak = equity[0]
    max_dd = Decimal("0")
    max_duration = 0
    active_peak_index = 0
    for index, value in enumerate(equity):
        if value >= peak:
            peak = value
            active_peak_index = index
            continue
        if peak > 0:
            dd = (peak - value) / peak
            if dd > max_dd:
                max_dd = dd
        duration = index - active_peak_index
        if duration > max_duration:
            max_duration = duration
    return max_dd, max_duration


def _consecutive_losses(net_pnls: Sequence[Decimal]) -> int:
    current = 0
    maximum = 0
    for pnl in net_pnls:
        if pnl < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _tail_loss(net_pnls: Sequence[Decimal]) -> Decimal:
    losses = sorted((-pnl for pnl in net_pnls if pnl < 0), reverse=True)
    if not losses:
        return Decimal("0")
    count = max(1, (len(losses) + 19) // 20)
    return _q(sum(losses[:count], Decimal("0")) / Decimal(count))


def _regime_breakdown(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for regime in sorted(ALLOWED_REGIMES):
        selected = [trade for trade in trades if trade["regime"] == regime]
        if not selected:
            continue
        net = [trade["net_pnl"] for trade in selected]
        wins = sum(1 for value in net if value > 0)
        output[regime] = {
            "trade_count": len(selected),
            "net_pnl": str(_q(sum(net, Decimal("0")))),
            "win_rate": str(_q(Decimal(wins) / Decimal(len(selected)), Q6)),
            "expectancy": str(_q(sum(net, Decimal("0")) / Decimal(len(selected)))),
        }
    return output


def _parameter_stability(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not windows:
        return {
            "status": "NOT_APPLICABLE",
            "reason_code": "NO_EVALUATION_WINDOWS",
        }
    scores = [window["score"] for window in windows]
    mean_score = sum(scores, Decimal("0")) / Decimal(len(scores))
    variance = sum((score - mean_score) ** 2 for score in scores) / Decimal(len(scores))
    parameter_ranges: dict[str, str] = {}
    for name in sorted(windows[0]["parameters"]):
        values = [window["parameters"][name] for window in windows]
        parameter_ranges[name] = str(_q(max(values) - min(values)))
    return {
        "status": "MEASURED",
        "window_count": len(windows),
        "score_mean": str(_q(mean_score)),
        "score_stddev": str(_q(_sqrt(variance))),
        "score_range": str(_q(max(scores) - min(scores))),
        "parameter_ranges": parameter_ranges,
    }


def analyze_performance(
    *,
    source_binding_sha256: str,
    initial_equity: Any,
    trades: Sequence[Mapping[str, Any]],
    evaluation_windows: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return deterministic Paper/Backtest performance evidence from closed trades.

    The function is analytics-only. It has no exchange, order, promotion, or Risk authority.
    Trade PnL is netted by explicit fees and converted into a deterministic equity path.
    """
    source_binding = _sha256(source_binding_sha256, "source_binding_sha256")
    starting = _decimal(initial_equity, "initial_equity", non_negative=True)
    if starting <= 0:
        raise PerformanceAnalyticsError("initial_equity must be positive")
    if not isinstance(trades, Sequence) or isinstance(trades, (str, bytes)) or not trades:
        raise PerformanceAnalyticsError("trades must be a non-empty bounded sequence")
    if len(trades) > 1_000_000:
        raise PerformanceAnalyticsError("trades exceeds bounded limit")

    parsed: list[dict[str, Any]] = []
    previous_close: int | None = None
    ids: set[str] = set()
    for raw in trades:
        trade = _validate_trade(raw, previous_close)
        if trade["trade_id"] in ids:
            raise PerformanceAnalyticsError("duplicate trade_id")
        ids.add(trade["trade_id"])
        parsed.append(trade)
        previous_close = trade["closed_at_ms"]

    windows = _validate_windows(evaluation_windows)
    net_pnls = [trade["net_pnl"] for trade in parsed]
    equity = [starting]
    for pnl in net_pnls:
        equity.append(equity[-1] + pnl)
    if any(value <= 0 for value in equity):
        raise PerformanceAnalyticsError("equity path reached non-positive value")

    wins = [pnl for pnl in net_pnls if pnl > 0]
    losses = [-pnl for pnl in net_pnls if pnl < 0]
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = sum(losses, Decimal("0"))
    if gross_loss == 0:
        profit_factor = "INF" if gross_profit > 0 else "0.00000000"
    else:
        profit_factor = str(_q(gross_profit / gross_loss))
    expectancy = sum(net_pnls, Decimal("0")) / Decimal(len(net_pnls))
    max_drawdown, drawdown_duration_trades = _drawdown(equity)
    avg_equity = sum(equity[:-1], Decimal("0")) / Decimal(len(parsed))
    traded_notional = sum(
        (trade["entry_notional"] + trade["exit_notional"] for trade in parsed),
        Decimal("0"),
    )
    turnover = traded_notional / avg_equity
    observation_start = min(trade["opened_at_ms"] for trade in parsed)
    observation_end = max(trade["closed_at_ms"] for trade in parsed)
    observation_ms = observation_end - observation_start
    exposure_ms = sum(trade["closed_at_ms"] - trade["opened_at_ms"] for trade in parsed)
    exposure_ratio = Decimal(exposure_ms) / Decimal(observation_ms) if observation_ms > 0 else Decimal("0")

    core = {
        "schema_version": SCHEMA_VERSION,
        "source_binding_sha256": source_binding,
        "paper_only": True,
        "analytics_authority": False,
        "promotion_authority": False,
        "trade_count": len(parsed),
        "initial_equity": str(_q(starting)),
        "final_equity": str(_q(equity[-1])),
        "net_pnl": str(_q(sum(net_pnls, Decimal("0")))),
        "win_rate": str(_q(Decimal(len(wins)) / Decimal(len(parsed)), Q6)),
        "profit_factor": profit_factor,
        "expectancy": str(_q(expectancy)),
        "max_drawdown_pct": str(_q(max_drawdown * Decimal("100"), Q6)),
        "drawdown_duration_trades": drawdown_duration_trades,
        "turnover_ratio": str(_q(turnover, Q6)),
        "exposure_ratio": str(_q(exposure_ratio, Q6)),
        "tail_loss_95_mean": str(_tail_loss(net_pnls)),
        "max_consecutive_losses": _consecutive_losses(net_pnls),
        "regime_breakdown": _regime_breakdown(parsed),
        "parameter_stability": _parameter_stability(windows),
    }
    return {**core, "analytics_sha256": _digest(core)}
