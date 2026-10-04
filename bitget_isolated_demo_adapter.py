"""Fail-closed Bitget normalization for an isolated Demo candidate.

This module has no transport, credentials, exchange-order, Paper mutation, strategy
promotion, or Live authority.  It only normalizes already-received public Bitget
payloads while preserving provider-native quantity, fee, funding and risk semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Mapping, Sequence


ADAPTER_VERSION = "nexus.bitget-isolated-demo-adapter.v1"
PROVIDER = "bitget"
PRODUCT_TYPE = "USDT-FUTURES"
SCOPE = "isolated_demo_candidate"
DEMO_REPLACEMENT_AUTHORIZED = False
PAPER_MUTATION_AUTHORITY = False
STRATEGY_PROMOTION_AUTHORITY = False
LIVE_TRADING_AUTHORITY = False


class BitgetDemoAdapterError(ValueError):
    pass


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, float):
        raise BitgetDemoAdapterError(f"{field} must not use binary floating point")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise BitgetDemoAdapterError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise BitgetDemoAdapterError(f"{field} must be finite")
    if positive and parsed <= 0:
        raise BitgetDemoAdapterError(f"{field} must be positive")
    return parsed


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise BitgetDemoAdapterError(f"{field} must be an integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise BitgetDemoAdapterError(f"{field} must be an integer") from exc
    if str(parsed) != str(value):
        raise BitgetDemoAdapterError(f"{field} must be an integer")
    if parsed < minimum:
        raise BitgetDemoAdapterError(f"{field} must be >= {minimum}")
    return parsed


@dataclass(frozen=True)
class BitgetInstrument:
    symbol: str
    minimum_quantity: Decimal
    quantity_step: Decimal
    minimum_notional: Decimal
    price_tick: Decimal
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    funding_interval_hours: int
    provider: str = PROVIDER
    product_type: str = PRODUCT_TYPE
    scope: str = SCOPE
    demo_replacement_authorized: bool = DEMO_REPLACEMENT_AUTHORIZED


@dataclass(frozen=True)
class BitgetBar:
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Decimal
    quote_volume: Decimal
    provider: str = PROVIDER
    closed: bool = True


@dataclass(frozen=True)
class BitgetFundingPoint:
    timestamp_ms: int
    rate: Decimal
    provider: str = PROVIDER


@dataclass(frozen=True)
class BitgetRiskTier:
    level: int
    start_unit: Decimal
    end_unit: Decimal
    leverage: Decimal
    maintenance_margin_rate: Decimal
    provider: str = PROVIDER


def parse_instrument(payload: Mapping[str, Any], *, expected_symbol: str) -> BitgetInstrument:
    """Normalize one public Bitget contract row using its native field meanings."""
    if not isinstance(payload, Mapping):
        raise BitgetDemoAdapterError("instrument must be a mapping")
    required = {
        "symbol", "minTradeNum", "sizeMultiplier", "minTradeUSDT",
        "pricePlace", "priceEndStep", "makerFeeRate", "takerFeeRate",
        "fundInterval",
    }
    if not required.issubset(payload):
        raise BitgetDemoAdapterError("instrument schema missing required native fields")
    symbol = payload["symbol"]
    if symbol != expected_symbol or not isinstance(symbol, str) or len(symbol) > 32:
        raise BitgetDemoAdapterError("instrument symbol mismatch")
    price_places = _integer(payload["pricePlace"], "pricePlace", minimum=0)
    if price_places > 18:
        raise BitgetDemoAdapterError("pricePlace outside bounded range")
    price_end_step = _decimal(payload["priceEndStep"], "priceEndStep", positive=True)
    price_tick = price_end_step * (Decimal(10) ** -price_places)
    maker = _decimal(payload["makerFeeRate"], "makerFeeRate")
    taker = _decimal(payload["takerFeeRate"], "takerFeeRate")
    if maker < 0 or taker < 0 or maker > Decimal("0.01") or taker > Decimal("0.01"):
        raise BitgetDemoAdapterError("fee rate outside bounded range")
    funding_hours = _integer(payload["fundInterval"], "fundInterval", minimum=1)
    if funding_hours > 24:
        raise BitgetDemoAdapterError("fundInterval outside bounded range")
    return BitgetInstrument(
        symbol=symbol,
        minimum_quantity=_decimal(payload["minTradeNum"], "minTradeNum", positive=True),
        quantity_step=_decimal(payload["sizeMultiplier"], "sizeMultiplier", positive=True),
        minimum_notional=_decimal(payload["minTradeUSDT"], "minTradeUSDT", positive=True),
        price_tick=price_tick,
        maker_fee_rate=maker,
        taker_fee_rate=taker,
        funding_interval_hours=funding_hours,
    )


def floor_to_step(value: Any, step: Decimal, *, field: str) -> Decimal:
    parsed = _decimal(value, field, positive=True)
    if step <= 0:
        raise BitgetDemoAdapterError(f"{field} step must be positive")
    units = (parsed / step).to_integral_value(rounding=ROUND_DOWN)
    return units * step


def normalized_demo_quantity(
    *, target_notional: Any, price: Any, instrument: BitgetInstrument
) -> Decimal:
    """Return a native Bitget quantity, or zero when provider minimums fail."""
    notional = _decimal(target_notional, "target_notional", positive=True)
    price_value = _decimal(price, "price", positive=True)
    quantity = floor_to_step(
        notional / price_value, instrument.quantity_step, field="quantity"
    )
    if quantity < instrument.minimum_quantity:
        return Decimal(0)
    if quantity * price_value < instrument.minimum_notional:
        return Decimal(0)
    return quantity


def normalized_demo_price(*, price: Any, instrument: BitgetInstrument) -> Decimal:
    return floor_to_step(price, instrument.price_tick, field="price")


def parse_closed_bars(
    rows: Sequence[Sequence[Any]],
    *,
    interval_ms: int,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[BitgetBar, ...]:
    """Normalize an exact closed window; missing/duplicate/open bars fail closed."""
    if interval_ms <= 0 or start_ms < 0 or end_exclusive_ms <= start_ms:
        raise BitgetDemoAdapterError("invalid bar window")
    if (end_exclusive_ms - start_ms) % interval_ms:
        raise BitgetDemoAdapterError("bar window is not interval aligned")
    expected = list(range(start_ms, end_exclusive_ms, interval_ms))
    parsed: dict[int, BitgetBar] = {}
    for row in rows:
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) < 7:
            raise BitgetDemoAdapterError("bar row schema mismatch")
        stamp = _integer(row[0], "bar timestamp", minimum=0)
        if stamp in parsed:
            raise BitgetDemoAdapterError("duplicate bar timestamp")
        values = [_decimal(row[index], f"bar[{index}]", positive=True) for index in range(1, 7)]
        open_price, high, low, close, base_volume, quote_volume = values
        if high < max(open_price, close) or low > min(open_price, close) or low > high:
            raise BitgetDemoAdapterError("bar OHLC invariant failed")
        parsed[stamp] = BitgetBar(
            stamp, open_price, high, low, close, base_volume, quote_volume
        )
    if sorted(parsed) != expected:
        raise BitgetDemoAdapterError("incomplete or out-of-window bar series")
    return tuple(parsed[stamp] for stamp in expected)


def parse_funding_points(
    rows: Sequence[Mapping[str, Any]], *, interval_hours: int
) -> tuple[BitgetFundingPoint, ...]:
    if interval_hours < 1 or interval_hours > 24:
        raise BitgetDemoAdapterError("funding interval outside bounded range")
    interval_ms = interval_hours * 60 * 60 * 1000
    points: list[BitgetFundingPoint] = []
    for row in rows:
        if not isinstance(row, Mapping) or not {"fundingTime", "fundingRate"}.issubset(row):
            raise BitgetDemoAdapterError("funding row schema mismatch")
        stamp = _integer(row["fundingTime"], "fundingTime", minimum=0)
        if stamp % interval_ms:
            raise BitgetDemoAdapterError("funding timestamp is not interval aligned")
        rate = _decimal(row["fundingRate"], "fundingRate")
        if abs(rate) > Decimal("0.05"):
            raise BitgetDemoAdapterError("fundingRate outside bounded range")
        points.append(BitgetFundingPoint(stamp, rate))
    stamps = [point.timestamp_ms for point in points]
    if stamps != sorted(set(stamps)):
        raise BitgetDemoAdapterError("funding timestamps must be unique and sorted")
    return tuple(points)


def parse_risk_tiers(rows: Sequence[Mapping[str, Any]]) -> tuple[BitgetRiskTier, ...]:
    tiers: list[BitgetRiskTier] = []
    for row in rows:
        required = {"level", "startUnit", "endUnit", "leverage", "keepMarginRate"}
        if not isinstance(row, Mapping) or not required.issubset(row):
            raise BitgetDemoAdapterError("risk tier schema mismatch")
        tier = BitgetRiskTier(
            level=_integer(row["level"], "level", minimum=1),
            start_unit=_decimal(row["startUnit"], "startUnit"),
            end_unit=_decimal(row["endUnit"], "endUnit", positive=True),
            leverage=_decimal(row["leverage"], "leverage", positive=True),
            maintenance_margin_rate=_decimal(row["keepMarginRate"], "keepMarginRate"),
        )
        if tier.start_unit < 0 or tier.end_unit <= tier.start_unit:
            raise BitgetDemoAdapterError("invalid risk tier range")
        if tier.leverage > Decimal(200):
            raise BitgetDemoAdapterError("risk tier leverage outside bounded range")
        if not Decimal(0) <= tier.maintenance_margin_rate < Decimal(1):
            raise BitgetDemoAdapterError("risk tier margin outside bounded range")
        tiers.append(tier)
    if not tiers:
        raise BitgetDemoAdapterError("empty risk tiers")
    for index, tier in enumerate(tiers):
        if tier.level != index + 1:
            raise BitgetDemoAdapterError("risk tiers must have contiguous levels")
        if index and tier.start_unit != tiers[index - 1].end_unit:
            raise BitgetDemoAdapterError("risk tiers must have contiguous ranges")
    return tuple(tiers)
