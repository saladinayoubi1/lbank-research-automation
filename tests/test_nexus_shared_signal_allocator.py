import pytest

from nexus_shared_signal_allocator import SharedAllocatorError, aggregate_targets


def test_same_direction_signals_share_one_portfolio_and_hit_caps():
    result = aggregate_targets(
        {"research_a": [0.5, 0.0], "research_b": [0.5, 0.0]},
        gross_cap=0.95, asset_cap=0.60,
    )
    assert result["per_strategy_fixed_cash"] is False
    assert result["raw_net_target"] == [1.0, 0.0]
    assert result["target_weights"] == [0.60, 0.0]
    assert result["gross_after_caps"] == pytest.approx(0.60)


def test_opposing_signals_net_before_execution_not_before_funding():
    result = aggregate_targets(
        {"research_a": [0.5, 0.2], "research_b": [-0.3, 0.1]},
        gross_cap=0.95, asset_cap=0.60,
    )
    assert result["target_weights"] == pytest.approx([0.2, 0.3])
    assert result["contributions"]["research_a"] == [0.5, 0.2]
    assert result["contributions"]["research_b"] == [-0.3, 0.1]


def test_gross_cap_scales_net_portfolio_without_cash_slices():
    result = aggregate_targets(
        {"a": [0.6, 0.6], "b": [0.1, 0.1]},
        gross_cap=0.80, asset_cap=0.60,
    )
    assert result["target_weights"] == pytest.approx([0.4, 0.4])
    assert result["gross_after_caps"] == pytest.approx(0.8)


@pytest.mark.parametrize("signals", [
    {"bad": [float("nan"), 0.0]},
    {"bad": [1.1, 0.0]},
    {"": [0.1, 0.0]},
])
def test_invalid_signal_intents_fail_closed(signals):
    with pytest.raises(SharedAllocatorError):
        aggregate_targets(signals)
