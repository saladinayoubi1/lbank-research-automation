from copy import deepcopy
from decimal import Decimal

import pytest

from paper_futures_model import (
    MODEL_VERSION,
    PaperFuturesModelError,
    evaluate_paper_futures_position,
)


def position(**changes):
    value = {
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": "0.01",
        "entry_price": "60000",
        "leverage": 10,
        "maintenance_margin_rate": "0.005",
        "collateral": "100",
    }
    value.update(changes)
    return value


def market(**changes):
    value = {"mark_price": "62000", "funding_rate": "0.0001", "funding_intervals": 1}
    value.update(changes)
    return value


def test_long_snapshot_is_deterministic_and_margin_accounted():
    first = evaluate_paper_futures_position(position=position(), market=market())
    second = evaluate_paper_futures_position(
        position=deepcopy(position()), market=deepcopy(market())
    )
    assert first == second
    assert first.model_version == MODEL_VERSION
    assert first.paper_trading_only is True
    assert first.entry_notional == Decimal("600.00000000")
    assert first.initial_margin == Decimal("60.00000000")
    assert first.mark_notional == Decimal("620.00000000")
    assert first.maintenance_margin == Decimal("3.10000000")
    assert first.unrealized_pnl == Decimal("20.00000000")
    assert first.funding_cashflow == Decimal("-0.06200000")
    assert first.equity == Decimal("119.93800000")
    assert first.margin_buffer == Decimal("116.83800000")
    assert first.liquidation_triggered is False
    assert first.reason_code == "MARGIN_HEALTHY"


def test_short_positive_funding_receives_cashflow_and_marks_pnl_correctly():
    result = evaluate_paper_futures_position(
        position=position(side="short"),
        market=market(mark_price="58000"),
    )
    assert result.unrealized_pnl == Decimal("20.00000000")
    assert result.funding_cashflow == Decimal("0.05800000")
    assert result.equity == Decimal("120.05800000")
    assert result.liquidation_triggered is False


def test_negative_funding_reverses_long_short_cashflow_direction():
    long_result = evaluate_paper_futures_position(
        position=position(), market=market(funding_rate="-0.0002")
    )
    short_result = evaluate_paper_futures_position(
        position=position(side="short"), market=market(funding_rate="-0.0002")
    )
    assert long_result.funding_cashflow == Decimal("0.12400000")
    assert short_result.funding_cashflow == Decimal("-0.12400000")


def test_liquidation_threshold_is_fail_closed_and_explicit():
    result = evaluate_paper_futures_position(
        position=position(collateral="60"),
        market=market(mark_price="50000", funding_rate="0", funding_intervals=0),
    )
    assert result.unrealized_pnl == Decimal("-100.00000000")
    assert result.equity == Decimal("-40.00000000")
    assert result.maintenance_margin == Decimal("2.50000000")
    assert result.margin_buffer == Decimal("-42.50000000")
    assert result.liquidation_triggered is True
    assert result.reason_code == "LIQUIDATION_THRESHOLD_BREACHED"


def test_multiple_funding_intervals_accumulate_deterministically():
    result = evaluate_paper_futures_position(
        position=position(), market=market(funding_intervals=3)
    )
    assert result.funding_cashflow == Decimal("-0.18600000")


@pytest.mark.parametrize(
    ("position_changes", "market_changes", "message"),
    [
        ({"quantity": 0.01}, {}, "floating point"),
        ({"leverage": 0}, {}, "leverage"),
        ({"leverage": 101}, {}, "leverage"),
        ({"maintenance_margin_rate": "0.1"}, {}, "initial margin rate"),
        ({"collateral": "10"}, {}, "initial margin"),
        ({"side": "buy"}, {}, "long or short"),
        ({}, {"funding_rate": "0.0101"}, "funding_rate"),
        ({}, {"funding_intervals": -1}, "funding_intervals"),
        ({}, {"funding_intervals": 10001}, "funding_intervals"),
        ({}, {"mark_price": "NaN"}, "finite"),
    ],
)
def test_invalid_or_unbounded_inputs_fail_closed(position_changes, market_changes, message):
    with pytest.raises(PaperFuturesModelError, match=message):
        evaluate_paper_futures_position(
            position=position(**position_changes), market=market(**market_changes)
        )


def test_unknown_live_or_credential_fields_are_rejected_by_exact_schema():
    live = position()
    live["live_order"] = True
    with pytest.raises(PaperFuturesModelError, match="schema mismatch"):
        evaluate_paper_futures_position(position=live, market=market())

    credential = position()
    credential["api_key"] = "secret"
    with pytest.raises(PaperFuturesModelError, match="schema mismatch"):
        evaluate_paper_futures_position(position=credential, market=market())

    exchange = market()
    exchange["exchange_order_id"] = "no"
    with pytest.raises(PaperFuturesModelError, match="schema mismatch"):
        evaluate_paper_futures_position(position=position(), market=exchange)
