import pytest

from deterministic_risk import RiskInputError, evaluate_risk


NOW = "2026-08-17T00:05:00Z"


def _signal(**changes):
    value = {
        "signal_id": "sig-security-1",
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
        "strategy_id": "trend",
        "strategy_version": "1.0.0",
        "side": "long",
        "quantity": "0.01",
        "reference_price": "60000",
        "stop_price": "58800",
        "target_price": "62400",
        "source_timestamp": "2026-08-17T00:00:00Z",
        "correlation_id": "security-run",
        "causation_id": "security-decision",
        "provenance_kind": "automatic",
    }
    value.update(changes)
    return value


def _state(**changes):
    value = {
        "equity": "10000",
        "daily_start_equity": "10000",
        "daily_realized_pnl": "0",
        "current_exposure": "0",
        "position_exposure": "0",
        "session_open": True,
        "signals_today": 0,
        "seen_signal_ids": [],
        "kill_switch": False,
        "data_circuit_open": False,
        "strategy_circuit_open": False,
        "provider_circuit_open": False,
    }
    value.update(changes)
    return value


def _policy(**changes):
    value = {
        "policy_id": "paper-risk",
        "policy_version": "1.0.0",
        "max_position_fraction": "0.10",
        "max_aggregate_fraction": "0.30",
        "max_daily_loss_fraction": "0.03",
        "max_drawdown_fraction": "0.05",
        "max_signals_per_session": 10,
        "max_signal_age_seconds": 900,
        "min_stop_distance_fraction": "0.005",
        "max_stop_distance_fraction": "0.05",
        "min_target_distance_fraction": "0.01",
        "supported_symbols": ["BTCUSDT"],
        "supported_timeframes": ["minute15"],
        "eligible_strategies": [{"id": "trend", "version": "1.0.0"}],
    }
    value.update(changes)
    return value


def _evaluate(*, signal=None, state=None, policy=None):
    return evaluate_risk(
        signal or _signal(),
        state or _state(),
        policy or _policy(),
        evaluated_at=NOW,
    )


def test_oversized_fraction_policy_cannot_disable_exposure_limits():
    poisoned = _policy(max_position_fraction="100", max_aggregate_fraction="100")
    with pytest.raises(RiskInputError, match="must be <= 1"):
        _evaluate(signal=_signal(quantity="1"), policy=poisoned)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_position_fraction", "NaN"),
        ("max_aggregate_fraction", "Infinity"),
        ("max_daily_loss_fraction", "1.0001"),
        ("max_drawdown_fraction", "2"),
        ("min_stop_distance_fraction", "0"),
        ("max_stop_distance_fraction", "-0.1"),
        ("min_target_distance_fraction", "5"),
    ],
)
def test_nonfinite_out_of_range_and_nonpositive_policy_fractions_fail_closed(field, value):
    with pytest.raises(RiskInputError):
        _evaluate(policy=_policy(**{field: value}))


def test_cross_field_policy_invariants_fail_closed():
    with pytest.raises(RiskInputError, match="max_position_fraction"):
        _evaluate(policy=_policy(max_position_fraction="0.50", max_aggregate_fraction="0.40"))
    with pytest.raises(RiskInputError, match="min_stop_distance_fraction"):
        _evaluate(policy=_policy(min_stop_distance_fraction="0.10", max_stop_distance_fraction="0.05"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_signals_per_session", True),
        ("max_signals_per_session", 0),
        ("max_signals_per_session", "10"),
        ("max_signal_age_seconds", False),
        ("max_signal_age_seconds", -1),
        ("max_signal_age_seconds", "900"),
    ],
)
def test_integer_policy_controls_reject_bool_strings_and_nonpositive_values(field, value):
    with pytest.raises(RiskInputError, match="positive integer"):
        _evaluate(policy=_policy(**{field: value}))


def test_policy_membership_collections_cannot_be_smuggled_as_strings_or_malformed_entries():
    with pytest.raises(RiskInputError, match="supported_symbols"):
        _evaluate(policy=_policy(supported_symbols="BTCUSDT"))
    with pytest.raises(RiskInputError, match="entry schema mismatch"):
        _evaluate(policy=_policy(eligible_strategies=[{"id": "trend"}]))


def test_negative_exposure_state_cannot_reduce_resulting_exposure_math():
    with pytest.raises(RiskInputError, match="non-negative"):
        _evaluate(state=_state(current_exposure="-100000"))


def test_valid_policy_remains_deterministic_after_security_validation():
    first = _evaluate()
    second = _evaluate()
    assert first == second
    assert first.allowed is True
    assert first.reason_code == "risk_allowed"
