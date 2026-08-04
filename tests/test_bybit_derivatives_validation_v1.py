from __future__ import annotations

import math

import pandas as pd

from bybit_derivatives_validation_v1 import (
    InstrumentSpec,
    Position,
    RiskTier,
    adverse_fill_price,
    apply_trade,
    choose_risk_tier,
    expected_funding_count,
    funding_cashflow,
    margin_requirements,
    minute_vwap,
    normalized_target_quantity,
)


def test_linear_position_accounting_handles_partial_close_and_flip() -> None:
    position = Position()
    assert apply_trade(position, 2.0, 100.0) == 0.0
    assert position.quantity == 2.0
    assert position.average_entry == 100.0

    realized = apply_trade(position, -1.0, 110.0)
    assert realized == 10.0
    assert position.quantity == 1.0
    assert position.average_entry == 100.0

    realized = apply_trade(position, -2.0, 90.0)
    assert realized == -10.0
    assert position.quantity == -1.0
    assert position.average_entry == 90.0


def test_funding_cashflow_uses_exchange_sign_convention() -> None:
    assert funding_cashflow(1.0, 10_000.0, 0.0001) == -1.0
    assert funding_cashflow(-1.0, 10_000.0, 0.0001) == 1.0
    assert funding_cashflow(1.0, 10_000.0, -0.0001) == 1.0


def test_minute_vwap_uses_turnover_over_volume() -> None:
    frame = pd.DataFrame({"volume": [2.0, 3.0], "turnover": [200.0, 330.0]})
    assert minute_vwap(frame) == 106.0


def test_adverse_fill_price_penalizes_buy_and_sell() -> None:
    profile = {
        "spread_bps": 4.0,
        "impact_floor_bps": 3.0,
        "impact_bps_per_ten_percent": 10.0,
    }
    buy, buy_bps = adverse_fill_price(1.0, 100.0, 1000.0, 100_000.0, profile)
    sell, sell_bps = adverse_fill_price(-1.0, 100.0, 1000.0, 100_000.0, profile)
    assert buy_bps == sell_bps
    assert buy > 100.0
    assert sell < 100.0


def test_quantity_rounding_respects_step_and_minimums() -> None:
    spec = InstrumentSpec(
        symbol="BTCUSDT",
        tick_size=0.1,
        quantity_step=0.001,
        minimum_quantity=0.001,
        minimum_notional=5.0,
        maximum_market_quantity=100.0,
        maximum_leverage=100.0,
        funding_interval_minutes=480,
    )
    quantity = normalized_target_quantity(1000.0, 30_000.0, spec)
    assert math.isclose(quantity, 0.033)
    assert normalized_target_quantity(1.0, 30_000.0, spec) == 0.0


def test_margin_uses_matching_risk_tier_and_close_fee() -> None:
    positions = [Position(quantity=1.0, average_entry=100.0)]
    tiers = [[
        RiskTier(1000.0, 0.01, 0.02, 0.0, 50.0),
        RiskTier(10_000.0, 0.02, 0.04, 10.0, 25.0),
    ]]
    initial, maintenance, details = margin_requirements(
        positions,
        mark_prices=pd.Series([100.0]).to_numpy(),
        risk_tiers=tiers,
        account_leverage=2.0,
        close_fee_rate=0.001,
    )
    assert math.isclose(initial, 50.1)
    assert math.isclose(maintenance, 1.1)
    assert details[0]["tier_limit"] == 1000.0
    assert choose_risk_tier(2000.0, tiers[0]).risk_limit_value == 10_000.0


def test_expected_funding_count_for_eight_hour_interval() -> None:
    start = pd.Timestamp("2026-01-01T00:00:00Z")
    end = pd.Timestamp("2026-01-02T00:00:00Z")
    assert expected_funding_count(start, end, 480) == 3
