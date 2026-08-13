from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Iterable

import pandas as pd

REQUIRED_MARKET_COLUMNS = ["timestamp", "open", "high", "low", "close"]
FILL_COLUMNS = [
    "signal_time",
    "execution_time",
    "reason",
    "side",
    "target_exposure",
    "quantity_change",
    "position_after",
    "reference_price",
    "fill_price",
    "notional",
    "fee",
    "cash_after",
]
EQUITY_COLUMNS = [
    "timestamp",
    "cash",
    "position_quantity",
    "close",
    "equity",
    "net_exposure",
    "drawdown",
]


class BacktestError(RuntimeError):
    pass


@dataclass(frozen=True)
class BacktestConfig:
    initial_cash: float = 10_000.0
    fee_bps: float = 0.0
    slippage_bps: float = 0.0
    max_abs_exposure: float = 1.0
    liquidate_at_end: bool = True

    def __post_init__(self) -> None:
        values = {
            "initial_cash": self.initial_cash,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "max_abs_exposure": self.max_abs_exposure,
        }
        for name, value in values.items():
            if not isfinite(float(value)):
                raise BacktestError(f"{name} must be finite")

        if self.initial_cash <= 0:
            raise BacktestError("initial_cash must be positive")
        if self.fee_bps < 0:
            raise BacktestError("fee_bps cannot be negative")
        if self.slippage_bps < 0:
            raise BacktestError("slippage_bps cannot be negative")
        if self.max_abs_exposure <= 0:
            raise BacktestError("max_abs_exposure must be positive")


@dataclass(frozen=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    metrics: dict[str, float | int | bool]


def _validate_market_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in REQUIRED_MARKET_COLUMNS if column not in frame]
    if missing:
        raise BacktestError(f"Market frame is missing columns: {missing}")
    if frame.empty:
        raise BacktestError("Market frame cannot be empty")

    normalized = frame.copy()
    try:
        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"], utc=True, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise BacktestError("Market frame contains an invalid timestamp") from exc

    if normalized["timestamp"].duplicated().any():
        raise BacktestError("Market timestamps must be unique")
    if not normalized["timestamp"].is_monotonic_increasing:
        raise BacktestError("Market timestamps must be sorted ascending")

    for column in ["open", "high", "low", "close"]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        if normalized[column].isna().any():
            raise BacktestError(f"Market column contains non-numeric values: {column}")
        if not normalized[column].map(lambda value: isfinite(float(value))).all():
            raise BacktestError(f"Market column contains non-finite values: {column}")
        if (normalized[column] <= 0).any():
            raise BacktestError(f"Market column must be positive: {column}")

    valid_high = normalized["high"] >= normalized[["open", "close", "low"]].max(
        axis=1
    )
    valid_low = normalized["low"] <= normalized[["open", "close", "high"]].min(
        axis=1
    )
    if not (valid_high & valid_low).all():
        raise BacktestError("Market frame contains invalid OHLC relationships")

    return normalized.reset_index(drop=True)


def _validate_target_exposures(
    target_exposures: Iterable[float],
    expected_length: int,
    max_abs_exposure: float,
) -> pd.Series:
    targets = pd.Series(list(target_exposures), dtype="float64")
    if len(targets) != expected_length:
        raise BacktestError(
            "Target exposure length must equal market-frame length: "
            f"{len(targets)} != {expected_length}"
        )
    if targets.isna().any() or not targets.map(isfinite).all():
        raise BacktestError("Target exposures must be finite numbers")
    if (targets.abs() > max_abs_exposure + 1e-12).any():
        raise BacktestError(
            "Target exposure exceeds max_abs_exposure: "
            f"{targets.abs().max()} > {max_abs_exposure}"
        )
    return targets.reset_index(drop=True)


def _fill_price(reference_price: float, quantity_change: float, slippage_rate: float) -> float:
    if quantity_change > 0:
        return reference_price * (1.0 + slippage_rate)
    return reference_price * (1.0 - slippage_rate)


def _cost_aware_quantity_change(
    *,
    cash: float,
    quantity: float,
    reference_price: float,
    target_exposure: float,
    fee_rate: float,
    slippage_rate: float,
) -> float:
    """Solve the trade size so post-trade exposure includes fees and slippage.

    Sizing from pre-trade equity alone can create a small unintended leveraged
    position when costs are non-zero (for example a 100% long target leaves
    negative cash after entry fees). This solver prices the intended trade side
    first and solves the post-cost exposure identity at the reference price.
    """

    equity_before = cash + quantity * reference_price
    numerator = target_exposure * equity_before - quantity * reference_price
    if abs(numerator) <= 1e-12:
        return 0.0

    direction = 1.0 if numerator > 0 else -1.0
    fill_price = _fill_price(reference_price, direction, slippage_rate)

    if direction > 0:
        cost_drag_per_unit = (fill_price - reference_price) + fill_price * fee_rate
        denominator = reference_price + target_exposure * cost_drag_per_unit
    else:
        cost_drag_per_unit = (reference_price - fill_price) + fill_price * fee_rate
        denominator = reference_price - target_exposure * cost_drag_per_unit

    if not isfinite(denominator) or denominator <= 0:
        raise BacktestError("Cost-aware target sizing produced an invalid denominator")

    quantity_change = numerator / denominator
    if not isfinite(quantity_change):
        raise BacktestError("Cost-aware target sizing produced a non-finite quantity")
    return quantity_change


def _empty_fills() -> pd.DataFrame:
    return pd.DataFrame(columns=FILL_COLUMNS)


def _calculate_drawdown(equity: pd.Series) -> pd.Series:
    running_peak = equity.cummax()
    return equity / running_peak - 1.0


def run_target_exposure_backtest(
    market_frame: pd.DataFrame,
    target_exposures: Iterable[float],
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Run a pure single-series target-exposure simulation.

    A target emitted for candle ``t`` is executed at candle ``t+1`` open. The
    first candle therefore cannot contain an execution, and the final target
    is intentionally ignored because no next candle exists.
    """

    resolved_config = config or BacktestConfig()
    market = _validate_market_frame(market_frame)
    targets = _validate_target_exposures(
        target_exposures,
        expected_length=len(market),
        max_abs_exposure=resolved_config.max_abs_exposure,
    )

    fee_rate = resolved_config.fee_bps / 10_000.0
    slippage_rate = resolved_config.slippage_bps / 10_000.0
    cash = float(resolved_config.initial_cash)
    quantity = 0.0
    fills: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []
    tolerance = 1e-12

    for index, candle in market.iterrows():
        if index > 0:
            target_exposure = float(targets.iloc[index - 1])
            reference_price = float(candle["open"])
            equity_at_open = cash + quantity * reference_price
            if not isfinite(equity_at_open):
                raise BacktestError("Equity became non-finite before execution")

            quantity_change = _cost_aware_quantity_change(
                cash=cash,
                quantity=quantity,
                reference_price=reference_price,
                target_exposure=target_exposure,
                fee_rate=fee_rate,
                slippage_rate=slippage_rate,
            )

            if abs(quantity_change) > tolerance:
                fill_price = _fill_price(
                    reference_price,
                    quantity_change,
                    slippage_rate,
                )
                notional = abs(quantity_change * fill_price)
                fee = notional * fee_rate
                cash -= quantity_change * fill_price + fee
                quantity += quantity_change

                fills.append(
                    {
                        "signal_time": market.iloc[index - 1]["timestamp"],
                        "execution_time": candle["timestamp"],
                        "reason": "target_rebalance",
                        "side": "buy" if quantity_change > 0 else "sell",
                        "target_exposure": target_exposure,
                        "quantity_change": quantity_change,
                        "position_after": quantity,
                        "reference_price": reference_price,
                        "fill_price": fill_price,
                        "notional": notional,
                        "fee": fee,
                        "cash_after": cash,
                    }
                )

        close_price = float(candle["close"])
        equity = cash + quantity * close_price
        if not isfinite(equity):
            raise BacktestError("Equity became non-finite at candle close")

        net_exposure = 0.0 if equity == 0 else quantity * close_price / equity
        equity_rows.append(
            {
                "timestamp": candle["timestamp"],
                "cash": cash,
                "position_quantity": quantity,
                "close": close_price,
                "equity": equity,
                "net_exposure": net_exposure,
            }
        )

    if resolved_config.liquidate_at_end and abs(quantity) > tolerance:
        final_candle = market.iloc[-1]
        reference_price = float(final_candle["close"])
        quantity_change = -quantity
        fill_price = _fill_price(reference_price, quantity_change, slippage_rate)
        notional = abs(quantity_change * fill_price)
        fee = notional * fee_rate
        cash -= quantity_change * fill_price + fee
        quantity = 0.0

        fills.append(
            {
                "signal_time": pd.NaT,
                "execution_time": final_candle["timestamp"],
                "reason": "end_liquidation",
                "side": "buy" if quantity_change > 0 else "sell",
                "target_exposure": 0.0,
                "quantity_change": quantity_change,
                "position_after": quantity,
                "reference_price": reference_price,
                "fill_price": fill_price,
                "notional": notional,
                "fee": fee,
                "cash_after": cash,
            }
        )

        equity_rows[-1]["cash"] = cash
        equity_rows[-1]["position_quantity"] = 0.0
        equity_rows[-1]["equity"] = cash
        equity_rows[-1]["net_exposure"] = 0.0

    equity_curve = pd.DataFrame(equity_rows)
    equity_curve["drawdown"] = _calculate_drawdown(equity_curve["equity"])
    equity_curve = equity_curve[EQUITY_COLUMNS]

    fills_frame = pd.DataFrame(fills, columns=FILL_COLUMNS) if fills else _empty_fills()
    total_fees = float(fills_frame["fee"].sum()) if not fills_frame.empty else 0.0
    total_notional = (
        float(fills_frame["notional"].sum()) if not fills_frame.empty else 0.0
    )
    final_equity = float(equity_curve.iloc[-1]["equity"])
    max_drawdown = float(-equity_curve["drawdown"].min())
    average_abs_exposure = float(equity_curve["net_exposure"].abs().mean())

    metrics: dict[str, float | int | bool] = {
        "initial_cash": float(resolved_config.initial_cash),
        "final_equity": final_equity,
        "net_pnl": final_equity - float(resolved_config.initial_cash),
        "total_return": final_equity / float(resolved_config.initial_cash) - 1.0,
        "max_drawdown": max_drawdown,
        "fill_count": int(len(fills_frame)),
        "total_fees": total_fees,
        "total_notional": total_notional,
        "turnover_on_initial_cash": total_notional
        / float(resolved_config.initial_cash),
        "average_abs_exposure": average_abs_exposure,
        "bars": int(len(equity_curve)),
        "liquidated_at_end": bool(resolved_config.liquidate_at_end),
    }

    return BacktestResult(
        equity_curve=equity_curve,
        fills=fills_frame,
        metrics=metrics,
    )
