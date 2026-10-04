from decimal import Decimal

import pytest

from bitget_isolated_demo_adapter import (
    DEMO_REPLACEMENT_AUTHORIZED,
    LIVE_TRADING_AUTHORITY,
    PAPER_MUTATION_AUTHORITY,
    STRATEGY_PROMOTION_AUTHORITY,
    BitgetDemoAdapterError,
    normalized_demo_price,
    normalized_demo_quantity,
    parse_closed_bars,
    parse_funding_points,
    parse_instrument,
    parse_risk_tiers,
)


def instrument(symbol="BTCUSDT", **changes):
    value = {
        "symbol": symbol,
        "minTradeNum": "0.0001" if symbol == "BTCUSDT" else "0.01",
        "sizeMultiplier": "0.0001" if symbol == "BTCUSDT" else "0.01",
        "minTradeUSDT": "5",
        "pricePlace": "1",
        "priceEndStep": "1",
        "makerFeeRate": "0.0002",
        "takerFeeRate": "0.0006",
        "fundInterval": "8",
    }
    value.update(changes)
    return parse_instrument(value, expected_symbol=symbol)


def test_authority_is_explicitly_absent():
    assert DEMO_REPLACEMENT_AUTHORIZED is False
    assert PAPER_MUTATION_AUTHORITY is False
    assert STRATEGY_PROMOTION_AUTHORITY is False
    assert LIVE_TRADING_AUTHORITY is False
    assert instrument().scope == "isolated_demo_candidate"


def test_btc_and_eth_use_their_own_native_quantity_steps():
    btc = normalized_demo_quantity(
        target_notional="10.009", price="60000", instrument=instrument("BTCUSDT")
    )
    eth = normalized_demo_quantity(
        target_notional="2000", price="3000", instrument=instrument("ETHUSDT")
    )
    assert btc == Decimal("0.0001")
    assert eth == Decimal("0.66")


def test_provider_minimum_notional_returns_zero_and_price_floors_to_tick():
    spec = instrument()
    assert normalized_demo_quantity(
        target_notional="4.999", price="60000", instrument=spec
    ) == Decimal(0)
    assert normalized_demo_price(price="60000.19", instrument=spec) == Decimal("60000.1")


def test_native_fees_and_funding_interval_are_preserved():
    spec = instrument()
    assert spec.maker_fee_rate == Decimal("0.0002")
    assert spec.taker_fee_rate == Decimal("0.0006")
    assert spec.funding_interval_hours == 8
    assert spec.demo_replacement_authorized is False


def test_exact_closed_bar_window_is_sorted_and_decimal_safe():
    rows = [
        ["14400000", "101", "103", "100", "102", "10", "1020"],
        ["0", "100", "102", "99", "101", "12", "1212"],
    ]
    bars = parse_closed_bars(
        rows, interval_ms=14_400_000, start_ms=0, end_exclusive_ms=28_800_000
    )
    assert [bar.open_time_ms for bar in bars] == [0, 14_400_000]
    assert bars[1].close == Decimal("102")
    assert all(bar.provider == "bitget" and bar.closed for bar in bars)


@pytest.mark.parametrize(
    "rows,message",
    [
        ([["0", "100", "102", "99", "101", "12", "1212"]], "incomplete"),
        ([
            ["0", "100", "102", "99", "101", "12", "1212"],
            ["0", "100", "102", "99", "101", "12", "1212"],
        ], "duplicate"),
        ([
            ["0", "100", "98", "99", "101", "12", "1212"],
            ["14400000", "101", "103", "100", "102", "10", "1020"],
        ], "OHLC"),
    ],
)
def test_bad_bar_windows_fail_closed(rows, message):
    with pytest.raises(BitgetDemoAdapterError, match=message):
        parse_closed_bars(
            rows, interval_ms=14_400_000, start_ms=0, end_exclusive_ms=28_800_000
        )


def test_funding_points_require_native_eight_hour_alignment():
    points = parse_funding_points(
        [
            {"fundingTime": "0", "fundingRate": "0.0001"},
            {"fundingTime": "28800000", "fundingRate": "-0.0002"},
        ],
        interval_hours=8,
    )
    assert [point.rate for point in points] == [Decimal("0.0001"), Decimal("-0.0002")]
    with pytest.raises(BitgetDemoAdapterError, match="aligned"):
        parse_funding_points(
            [{"fundingTime": "1", "fundingRate": "0.0001"}], interval_hours=8
        )


def test_risk_tiers_preserve_contiguous_provider_ranges():
    tiers = parse_risk_tiers([
        {"level": "1", "startUnit": "0", "endUnit": "50000", "leverage": "125", "keepMarginRate": "0.004"},
        {"level": "2", "startUnit": "50000", "endUnit": "100000", "leverage": "100", "keepMarginRate": "0.005"},
    ])
    assert tiers[0].end_unit == tiers[1].start_unit
    assert tiers[0].leverage == Decimal("125")
    with pytest.raises(BitgetDemoAdapterError, match="contiguous"):
        parse_risk_tiers([
            {"level": "1", "startUnit": "0", "endUnit": "50000", "leverage": "125", "keepMarginRate": "0.004"},
            {"level": "2", "startUnit": "60000", "endUnit": "100000", "leverage": "100", "keepMarginRate": "0.005"},
        ])


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"symbol": "ETHUSDT"}, "symbol mismatch"),
        ({"sizeMultiplier": 0.0001}, "binary floating point"),
        ({"makerFeeRate": "0.1"}, "fee rate"),
        ({"fundInterval": "48"}, "fundInterval"),
        ({"apiKey": "must-not-matter", "minTradeNum": None}, "valid decimal"),
    ],
)
def test_invalid_provider_contracts_fail_closed(changes, message):
    payload = {
        "symbol": "BTCUSDT",
        "minTradeNum": "0.0001",
        "sizeMultiplier": "0.0001",
        "minTradeUSDT": "5",
        "pricePlace": "1",
        "priceEndStep": "1",
        "makerFeeRate": "0.0002",
        "takerFeeRate": "0.0006",
        "fundInterval": "8",
    }
    payload.update(changes)
    with pytest.raises(BitgetDemoAdapterError, match=message):
        parse_instrument(payload, expected_symbol="BTCUSDT")
