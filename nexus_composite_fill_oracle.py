"""Independent Decimal accounting oracle for composite research-only executions.

A distinct implementation from nexus_composite_strategy_research.backtest.
Consumes already-verified CLOSED-candle feature frames and generated decision
signals, independently prices next-open fills, brackets, gaps, same-bar
adverse priority, entry/exit fees, slippage, position size and risk halts.
This is a deterministic QA cross-check, NOT independent market data, statistical
edge, a pristine forward test, owner-Paper, or Live trading authority.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from collections.abc import Mapping, Sequence
from typing import Any

START_CASH = Decimal("10000")
ONE = Decimal("1")
BPS = Decimal("10000")
TOL_PNL = Decimal("0.0001")
TOL_PCT = Decimal("0.00001")
TOL_TURNOVER = Decimal("0.0002")


class CompositeFillOracleError(ValueError):
    pass


def _num(value: Any, name: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise CompositeFillOracleError(f"oracle {name} is not numeric")
    try:
        v = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise CompositeFillOracleError(f"oracle {name} cannot be decoded") from exc
    if not v.is_finite():
        raise CompositeFillOracleError(f"oracle {name} must be finite")
    return v


def _within(got: Decimal, expected: Any, name: str, tolerance: Decimal) -> None:
    actual = _num(expected, name)
    if abs(got - actual) > tolerance:
        raise CompositeFillOracleError(
            f"independent fill oracle mismatch: {name}={actual} expected~{got}"
        )


def recompute(frame: Any, signals: Sequence[bool], *,
              fee_bps: float, slip_bps: float, risk_variant: int) -> dict[str, Any]:
    """Recompute accounting without calling the source engine or using its state.

    A bar-close decision fills at NEXT bar open. Conservative ambiguity rule:
    same-bar target & stop => stop. At most one collateral-backed long; no
    leverage; max 64 bars, daily -5% pause, cumulative -10% drawdown halt.
    """
    if type(risk_variant) is not int or risk_variant not in (0, 1):
        raise CompositeFillOracleError("unknown independent risk variant")
    if len(frame) < 2 or len(frame) != len(signals):
        raise CompositeFillOracleError("oracle requires aligned chronological signals")
    fee = _num(fee_bps, "fee_bps") / BPS
    slip = _num(slip_bps, "slippage_bps") / BPS
    if fee < 0 or slip < 0 or fee > Decimal("0.1") or slip > Decimal("0.1"):
        raise CompositeFillOracleError("oracle execution cost outside bounds")
    stop_multiplier, reward_multiplier = (
        (Decimal("1.5"), Decimal("2"))
        if risk_variant == 0
        else (Decimal("2"), Decimal("2.5"))
    )
    with localcontext() as context:
        context.prec = 36
        balance = START_CASH
        watermark = START_CASH
        max_dd = Decimal("0")
        open_lot: dict[str, Any] | None = None
        next_atr: Decimal | None = None
        current_day = None
        baseline = START_CASH
        paused = False
        stopped = False
        closed = wins = exposure = 0
        gain = loss = turnover = Decimal("0")
        fills: list[dict[str, Any]] = []
        previous = None

        for idx, row in enumerate(frame.itertuples(index=False)):
            timestamp = row.decision_at
            if getattr(timestamp, "tzinfo", None) is None:
                raise CompositeFillOracleError("oracle requires UTC-bound decision timestamps")
            moment = timestamp.value
            if previous is not None and moment <= previous:
                raise CompositeFillOracleError("nonmonotonic fill decision bar")
            previous = moment
            d = timestamp.floor("D")
            op = _num(row.open, "open")
            hi = _num(row.high, "high")
            lo = _num(row.low, "low")
            cl = _num(row.close, "close")
            if not (Decimal("0") < lo <= min(op, cl) <= max(op, cl) <= hi):
                raise CompositeFillOracleError("OHLC inconsistent before fill audit")
            if d != current_day:
                current_day = d
                baseline = balance + (open_lot["quantity"] * op if open_lot else 0)
                paused = False
            entered = False
            if open_lot is None and next_atr is not None and not stopped and not paused:
                entry_atr = next_atr
                next_atr = None
                entry_price = op * (ONE + slip)
                stop_price = entry_price - entry_atr * stop_multiplier
                target_price = entry_price + entry_atr * stop_multiplier * reward_multiplier
                if stop_price > 0 and target_price.is_finite():
                    budget = balance * Decimal("0.001")
                    capital_qty = balance * Decimal("0.1") / (entry_price * (ONE + fee))
                    risk_qty = budget / (entry_price - stop_price)
                    quantity = min(capital_qty, risk_qty)
                    paid = quantity * entry_price
                    in_fee = paid * fee
                    if quantity > 0 and paid + in_fee <= balance:
                        balance -= paid + in_fee
                        open_lot = {
                            "quantity": quantity, "entry": entry_price,
                            "entry_fee": in_fee, "stop": stop_price,
                            "target": target_price, "bars": 0,
                        }
                        turnover += paid
                        entered = True
                        fills.append({
                            "bar": idx, "side": "BUY", "price": entry_price,
                            "quantity": quantity, "fee": in_fee,
                        })
            if open_lot is not None:
                exposure += 1
                open_lot["bars"] += 1
                exit_quote = None
                reason = None
                if lo <= open_lot["stop"]:
                    exit_quote = min(op, open_lot["stop"])
                    reason = "stop"
                elif hi >= open_lot["target"]:
                    exit_quote = open_lot["target"]
                    reason = "target"
                elif open_lot["bars"] >= 64 or idx == len(frame) - 1:
                    exit_quote = cl
                    reason = "time_or_terminal"
                if exit_quote is not None:
                    exit_price = max(Decimal("0"), exit_quote * (ONE - slip))
                    size = open_lot["quantity"]
                    proceeds = size * exit_price
                    out_fee = proceeds * fee
                    balance += proceeds - out_fee
                    profit = size * (exit_price - open_lot["entry"]) - open_lot["entry_fee"] - out_fee
                    gain += max(Decimal("0"), profit)
                    loss += max(Decimal("0"), -profit)
                    wins += int(profit > 0)
                    closed += 1
                    turnover += proceeds
                    fills.append({
                        "bar": idx, "side": "SELL", "price": exit_price,
                        "quantity": size, "fee": out_fee, "pnl": profit,
                        "reason": reason,
                    })
                    open_lot = None
            mark = balance + (open_lot["quantity"] * cl if open_lot else 0)
            watermark = max(watermark, mark)
            max_dd = max(max_dd, ONE - mark / watermark)
            if mark < baseline * Decimal("0.95"):
                paused = True
            if max_dd > Decimal("0.10"):
                stopped = True
            if open_lot is None and not entered and not stopped and not paused and idx < len(frame) - 1:
                if bool(signals[idx]):
                    atr = _num(row.atr, "atr")
                    if atr > 0:
                        next_atr = atr
        if open_lot is not None:
            raise CompositeFillOracleError("unliquidated position at data end")
        net = balance - START_CASH
        return {
            "net_pnl_usdt": net,
            "net_return_pct": net / START_CASH * 100,
            "max_drawdown_pct": max_dd * 100,
            "closed_round_trips": closed,
            "win_rate_pct": Decimal(wins) / Decimal(closed) * 100 if closed else None,
            "profit_factor": gain / loss if loss > 0 else None,
            "profit_factor_status": (
                "AVAILABLE" if loss > 0 else "NOT_AVAILABLE_NO_REALIZED_LOSSES"
            ),
            "turnover_usdt": turnover,
            "exposure_bar_ratio": Decimal(exposure) / Decimal(len(frame)),
            "halted_on_drawdown": stopped,
            "trade_count_limit": None,
            "concurrent_risk_model":
                "one_collateral_backed_net_long_per_symbol;10pct_position_budget",
            "fills": fills,
        }


def verify_fills(frame: Any, signals: Sequence[bool], *,
                 fee_bps: float, slip_bps: float, risk_variant: int,
                 observed: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on a *distinct* accounting implementation's discrepancy."""
    if not isinstance(observed, Mapping):
        raise CompositeFillOracleError("oracle observed profile missing")
    own = recompute(frame, signals, fee_bps=fee_bps, slip_bps=slip_bps,
                    risk_variant=risk_variant)
    for key, tol in (
        ("net_pnl_usdt", TOL_PNL),
        ("net_return_pct", TOL_PCT),
        ("max_drawdown_pct", TOL_PCT),
        ("turnover_usdt", TOL_TURNOVER),
        ("exposure_bar_ratio", TOL_PCT),
    ):
        _within(own[key], observed.get(key), key, tol)
    for key in (
        "closed_round_trips", "profit_factor_status", "halted_on_drawdown",
        "trade_count_limit", "concurrent_risk_model",
    ):
        if own[key] != observed.get(key):
            raise CompositeFillOracleError(f"independent fill oracle mismatch: {key}")
    for key, tolerance in (
        ("win_rate_pct", Decimal("0.00001")),
        ("profit_factor", Decimal("0.00002")),
    ):
        if own[key] is None:
            if observed.get(key) is not None:
                raise CompositeFillOracleError(f"independent fill oracle mismatch: {key}")
        else:
            _within(own[key], observed.get(key), key, tolerance)
    if (
        _num(observed.get("fee_bps"), "fee_bps") != _num(fee_bps, "fee_bps")
        or _num(observed.get("slippage_bps"), "slippage_bps")
            != _num(slip_bps, "slippage_bps")
    ):
        raise CompositeFillOracleError("independent fill oracle cost profile changed")
    return {
        "decision": "PASS_RESEARCH_ONLY",
        "closed_round_trips": own["closed_round_trips"],
        "evaluated_fills": len(own["fills"]),
        "owner_demo_admission": False,
        "live_trading_authority": False,
    }
