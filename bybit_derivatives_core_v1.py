from __future__ import annotations

import dataclasses
import math
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any

import numpy as np
import pandas as pd
import requests


class ValidationError(RuntimeError):
    pass


@dataclasses.dataclass
class Position:
    quantity: float = 0.0
    average_entry: float = 0.0


@dataclasses.dataclass(frozen=True)
class InstrumentSpec:
    symbol: str
    tick_size: float
    quantity_step: float
    minimum_quantity: float
    minimum_notional: float
    maximum_market_quantity: float
    maximum_leverage: float
    funding_interval_minutes: int


@dataclasses.dataclass(frozen=True)
class RiskTier:
    risk_limit_value: float
    maintenance_margin_rate: float
    initial_margin_rate: float
    maintenance_margin_deduction: float
    maximum_leverage: float


class Client:
    def __init__(self, bases: list[str], timeout: float, attempts: int, pause: float) -> None:
        self.bases = [x.rstrip('/') for x in bases]
        self.timeout = timeout
        self.attempts = attempts
        self.pause = pause
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'lbank-research-automation/derivatives-v1'
        self.preferred_base: str | None = None
        self.blocked_bases: set[str] = set()
        self.transport_failures: dict[str, int] = {}

    def _ordered_bases(self) -> list[str]:
        available = [base for base in self.bases if base not in self.blocked_bases]
        if self.preferred_base in available:
            return [self.preferred_base, *[base for base in available if base != self.preferred_base]]
        return available

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        attempts = 0
        while attempts < self.attempts:
            candidates = self._ordered_bases()
            if not candidates:
                break
            base = candidates[attempts % len(candidates)]
            attempts += 1
            try:
                response = self.session.get(
                    base + path,
                    params=params,
                    timeout=(5.0, self.timeout),
                )
                if response.status_code in {403, 404, 451}:
                    self.blocked_bases.add(base)
                    if self.preferred_base == base:
                        self.preferred_base = None
                    last = ValidationError(f'blocked HTTP {response.status_code} from {base}')
                    continue
                if response.status_code in {429, 500, 502, 503, 504}:
                    last = ValidationError(f'temporary HTTP {response.status_code} from {base}')
                    time.sleep(min(0.25 * attempts, 2.0))
                    continue
                response.raise_for_status()
                payload = response.json()
                ret_code = int(payload.get('retCode', -1))
                if ret_code != 0:
                    message = str(payload.get('retMsg'))
                    if ret_code in {10006, 10016}:
                        last = ValidationError(f'temporary Bybit error {ret_code}: {message}')
                        time.sleep(min(0.25 * attempts, 2.0))
                        continue
                    raise ValidationError(f'Bybit error {ret_code}: {message}')
                self.preferred_base = base
                self.transport_failures[base] = 0
                time.sleep(self.pause)
                return payload
            except (requests.RequestException, ValueError) as exc:
                last = exc
                failures = self.transport_failures.get(base, 0) + 1
                self.transport_failures[base] = failures
                if failures >= 2:
                    self.blocked_bases.add(base)
                    if self.preferred_base == base:
                        self.preferred_base = None
                continue
            except ValidationError as exc:
                last = exc
                raise
        raise ValidationError(
            f'Bybit request failed after {attempts} attempts; '
            f'blocked={sorted(self.blocked_bases)}; last={last}'
        )


def milliseconds(value: str | pd.Timestamp) -> int:
    timestamp = pd.Timestamp(value)
    timestamp = timestamp.tz_localize('UTC') if timestamp.tzinfo is None else timestamp.tz_convert('UTC')
    return int(timestamp.timestamp() * 1000)


def fetch_klines(
    client: Client,
    endpoint: str,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    include_volume: bool = False,
) -> pd.DataFrame:
    rows: dict[int, list[str]] = {}
    cursor = end_ms - 1
    while cursor >= start_ms:
        batch = client.get(endpoint, {
            'category': 'linear',
            'symbol': symbol,
            'interval': interval,
            'start': start_ms,
            'end': cursor,
            'limit': 1000,
        })['result'].get('list', [])
        if not batch:
            break
        for item in batch:
            stamp = int(item[0])
            if start_ms <= stamp < end_ms:
                rows[stamp] = item
        oldest = min(int(item[0]) for item in batch)
        if oldest <= start_ms:
            break
        if oldest >= cursor:
            raise ValidationError(f'kline pagination stalled: {symbol} {endpoint}')
        cursor = oldest - 1
    if not rows:
        raise ValidationError(f'no kline rows: {symbol} {endpoint}')
    items = [rows[key] for key in sorted(rows)]
    data: dict[str, Any] = {
        'timestamp': pd.to_datetime([int(x[0]) for x in items], unit='ms', utc=True),
        'open': [float(x[1]) for x in items],
        'high': [float(x[2]) for x in items],
        'low': [float(x[3]) for x in items],
        'close': [float(x[4]) for x in items],
    }
    if include_volume:
        data['volume'] = [float(x[5]) for x in items]
        data['turnover'] = [float(x[6]) for x in items]
    return pd.DataFrame(data)


def fetch_funding(client: Client, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    rows: dict[int, float] = {}
    cursor = end_ms - 1
    while cursor >= start_ms:
        batch = client.get('/v5/market/funding/history', {
            'category': 'linear',
            'symbol': symbol,
            'endTime': cursor,
            'limit': 200,
        })['result'].get('list', [])
        if not batch:
            break
        stamps = [int(x['fundingRateTimestamp']) for x in batch]
        for item, stamp in zip(batch, stamps):
            if start_ms <= stamp < end_ms:
                rows[stamp] = float(item['fundingRate'])
        oldest = min(stamps)
        if oldest <= start_ms:
            break
        if oldest >= cursor:
            raise ValidationError(f'funding pagination stalled: {symbol}')
        cursor = oldest - 1
    ordered = sorted(rows)
    return pd.DataFrame({
        'timestamp': pd.to_datetime(ordered, unit='ms', utc=True),
        'funding_rate': [rows[x] for x in ordered],
    })


def fetch_instrument(client: Client, symbol: str) -> InstrumentSpec:
    items = client.get('/v5/market/instruments-info', {
        'category': 'linear', 'symbol': symbol, 'limit': 1000,
    })['result'].get('list', [])
    if not items:
        raise ValidationError(f'no instrument specification: {symbol}')
    item = items[0]
    lot = item['lotSizeFilter']
    leverage = item['leverageFilter']
    price = item['priceFilter']
    return InstrumentSpec(
        symbol=symbol,
        tick_size=float(price['tickSize']),
        quantity_step=float(lot['qtyStep']),
        minimum_quantity=float(lot['minOrderQty']),
        minimum_notional=float(lot.get('minNotionalValue') or 0.0),
        maximum_market_quantity=float(
            lot.get('maxMktOrderQty') or lot.get('maxMarketOrderQty') or math.inf
        ),
        maximum_leverage=float(leverage['maxLeverage']),
        funding_interval_minutes=int(item.get('fundingInterval', 480)),
    )


def fetch_risk_tiers(client: Client, symbol: str) -> list[RiskTier]:
    items = client.get('/v5/market/risk-limit', {
        'category': 'linear', 'symbol': symbol,
    })['result'].get('list', [])
    if not items:
        raise ValidationError(f'no risk tiers: {symbol}')
    tiers = [
        RiskTier(
            risk_limit_value=float(x['riskLimitValue']),
            maintenance_margin_rate=float(x['maintenanceMargin']),
            initial_margin_rate=float(x.get('initialMargin') or 0.0),
            maintenance_margin_deduction=float(x.get('mmDeduction') or 0.0),
            maximum_leverage=float(x['maxLeverage']),
        )
        for x in items
    ]
    return sorted(tiers, key=lambda x: x.risk_limit_value)


def choose_risk_tier(notional: float, tiers: list[RiskTier]) -> RiskTier:
    if not tiers:
        raise ValidationError('empty risk tiers')
    return next((x for x in tiers if notional <= x.risk_limit_value + 1e-9), tiers[-1])


def floor_step(value: float, step: float) -> float:
    if step <= 0.0:
        return value
    scaled = (Decimal(str(abs(value))) / Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)
    return math.copysign(float(scaled * Decimal(str(step))), value)


def normalized_target_quantity(notional: float, price: float, spec: InstrumentSpec) -> float:
    if price <= 0.0:
        raise ValidationError(f'non-positive price: {spec.symbol}')
    quantity = floor_step(notional / price, spec.quantity_step)
    if abs(quantity) < spec.minimum_quantity or abs(quantity * price) < spec.minimum_notional:
        return 0.0
    if abs(quantity) > spec.maximum_market_quantity:
        raise ValidationError(f'maximum market quantity exceeded: {spec.symbol}')
    return quantity


def apply_trade(position: Position, delta: float, price: float) -> float:
    if abs(delta) <= 1e-15:
        return 0.0
    old = position.quantity
    entry = position.average_entry
    new = old + delta
    realized = 0.0
    if abs(old) <= 1e-15 or math.copysign(1.0, old) == math.copysign(1.0, delta):
        position.average_entry = (abs(old) * entry + abs(delta) * price) / (abs(old) + abs(delta))
    else:
        closed = min(abs(old), abs(delta))
        realized = closed * (price - entry) * math.copysign(1.0, old)
        if abs(new) <= 1e-15:
            position.average_entry = 0.0
        elif math.copysign(1.0, new) != math.copysign(1.0, old):
            position.average_entry = price
    position.quantity = 0.0 if abs(new) <= 1e-15 else new
    return realized


def funding_cashflow(quantity: float, mark_price: float, funding_rate: float) -> float:
    return -(quantity * mark_price * funding_rate)


def unrealized(position: Position, mark_price: float) -> float:
    return position.quantity * (mark_price - position.average_entry)


def margin_requirements(
    positions: list[Position],
    mark_prices: np.ndarray,
    risk_tiers: list[list[RiskTier]],
    account_leverage: float,
    close_fee_rate: float,
) -> tuple[float, float, list[dict[str, float]]]:
    initial = 0.0
    maintenance = 0.0
    details: list[dict[str, float]] = []
    for index, position in enumerate(positions):
        notional = abs(position.quantity) * float(mark_prices[index])
        if notional <= 0.0:
            details.append({'notional': 0.0, 'initial': 0.0, 'maintenance': 0.0, 'tier_limit': 0.0})
            continue
        tier = choose_risk_tier(notional, risk_tiers[index])
        effective_leverage = min(account_leverage, tier.maximum_leverage)
        initial_rate = max(1.0 / effective_leverage, tier.initial_margin_rate)
        initial_value = notional * initial_rate + notional * close_fee_rate
        maintenance_value = max(
            notional * tier.maintenance_margin_rate - tier.maintenance_margin_deduction,
            0.0,
        ) + notional * close_fee_rate
        initial += initial_value
        maintenance += maintenance_value
        details.append({
            'notional': float(notional),
            'initial': float(initial_value),
            'maintenance': float(maintenance_value),
            'tier_limit': float(tier.risk_limit_value),
        })
    return initial, maintenance, details


def minute_vwap(frame: pd.DataFrame) -> float | None:
    if frame.empty or frame['volume'].sum() <= 0.0 or frame['turnover'].sum() <= 0.0:
        return None
    return float(frame['turnover'].sum() / frame['volume'].sum())


def adverse_fill_price(
    side: float,
    vwap: float,
    notional: float,
    turnover: float,
    profile: dict[str, float],
) -> tuple[float, float]:
    bps = profile['spread_bps'] / 2.0 + profile['impact_floor_bps']
    bps += notional / max(turnover, 1.0) / 0.10 * profile['impact_bps_per_ten_percent']
    return vwap * (1.0 + math.copysign(bps / 10000.0, side)), float(bps)


def expected_funding_count(start: pd.Timestamp, end: pd.Timestamp, interval_minutes: int) -> int:
    return max(0, int((end - start).total_seconds() // (interval_minutes * 60)))
