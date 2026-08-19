from decimal import Decimal

import pytest

from paper_exchange_simulator import PaperExchangeSimulationError, simulate_paper_order


def order(**changes):
    value = {
        "order_id": "paper-order-1",
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": "0.03",
        "reference_price": "60000",
        "fee_rate": "0.001",
        "slippage_bps": "10",
    }
    value.update(changes)
    return value


def profile(**changes):
    value = {"latency_ms": 25, "per_fill_quantity": "0.01", "max_fills": 3}
    value.update(changes)
    return value


def test_multi_fill_order_is_deterministic_and_fully_accounted():
    first = simulate_paper_order(order=order(), profile=profile())
    second = simulate_paper_order(order=order(), profile=profile())
    assert first == second
    assert first.status == "FILLED"
    assert first.filled_quantity == Decimal("0.03")
    assert first.remaining_quantity == Decimal("0.00")
    assert [fill.quantity for fill in first.fills] == [Decimal("0.01")] * 3
    assert [fill.latency_ms for fill in first.fills] == [25, 50, 75]
    assert [fill.fill_id for fill in first.fills] == [
        "paper-order-1:fill:1", "paper-order-1:fill:2", "paper-order-1:fill:3"
    ]
    assert all(fill.paper_trading_only for fill in first.fills)
    assert first.paper_trading_only is True
    assert first.total_fee == sum((fill.fee for fill in first.fills), Decimal("0"))
    assert first.total_slippage_cost == sum((fill.slippage_cost for fill in first.fills), Decimal("0"))


def test_bounded_fill_budget_truthfully_returns_partial_remainder_without_overfill():
    result = simulate_paper_order(order=order(quantity="0.05"), profile=profile(max_fills=2))
    assert result.status == "PARTIALLY_FILLED"
    assert result.filled_quantity == Decimal("0.02")
    assert result.remaining_quantity == Decimal("0.03")
    assert result.filled_quantity + result.remaining_quantity == result.requested_quantity
    assert all(fill.quantity <= Decimal("0.01") for fill in result.fills)


def test_single_fill_profile_preserves_existing_full_fill_shape():
    result = simulate_paper_order(
        order=order(quantity="0.01"),
        profile=profile(per_fill_quantity="0.01", max_fills=1, latency_ms=0),
    )
    assert result.status == "FILLED"
    assert len(result.fills) == 1
    assert result.fills[0].price == Decimal("60060.00000000")
    assert result.fills[0].fee == Decimal("0.60060000")
    assert result.fills[0].slippage_cost == Decimal("0.60000000")


def test_sell_slippage_is_adverse_and_deterministic():
    result = simulate_paper_order(
        order=order(side="sell", quantity="0.01"),
        profile=profile(per_fill_quantity="0.01", max_fills=1),
    )
    assert result.fills[0].price == Decimal("59940.00000000")
    assert result.total_slippage_cost == Decimal("0.60000000")


@pytest.mark.parametrize(
    ("bad_order", "bad_profile", "message"),
    [
        ({"quantity": 0.01}, {}, "floating point"),
        ({"slippage_bps": "101"}, {}, "slippage"),
        ({"fee_rate": "0.02"}, {}, "fee_rate"),
        ({}, {"latency_ms": 60001}, "latency_ms"),
        ({}, {"per_fill_quantity": "0"}, "per_fill_quantity"),
        ({}, {"max_fills": 0}, "max_fills"),
    ],
)
def test_invalid_or_unbounded_simulation_inputs_fail_closed(bad_order, bad_profile, message):
    with pytest.raises(PaperExchangeSimulationError, match=message):
        simulate_paper_order(order=order(**bad_order), profile=profile(**bad_profile))


def test_unknown_live_or_credential_fields_are_denied_by_exact_schema():
    live = order()
    live["live_order"] = True
    with pytest.raises(PaperExchangeSimulationError, match="schema mismatch"):
        simulate_paper_order(order=live, profile=profile())

    credential = order()
    credential["api_key"] = "secret"
    with pytest.raises(PaperExchangeSimulationError, match="schema mismatch"):
        simulate_paper_order(order=credential, profile=profile())
