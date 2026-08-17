from copy import deepcopy

import pytest

from deterministic_risk import RiskInputError, evaluate_risk


def signal(**changes):
    value = {
        "signal_id": "sig-1", "symbol": "BTCUSDT", "timeframe": "minute15",
        "strategy_id": "trend", "strategy_version": "1.0.0", "side": "long",
        "quantity": "0.01", "reference_price": "60000", "stop_price": "58800",
        "target_price": "62400", "source_timestamp": "2026-08-17T00:00:00Z",
        "correlation_id": "run-1", "causation_id": "decision-1",
        "provenance_kind": "automatic",
    }
    value.update(changes)
    return value


def state(**changes):
    value = {
        "equity": "10000", "daily_start_equity": "10000", "daily_realized_pnl": "0",
        "current_exposure": "0", "position_exposure": "0", "session_open": True,
        "signals_today": 0, "seen_signal_ids": [], "kill_switch": False,
        "data_circuit_open": False, "strategy_circuit_open": False,
        "provider_circuit_open": False,
    }
    value.update(changes)
    return value


def policy(**changes):
    value = {
        "policy_id": "paper-risk", "policy_version": "1.0.0",
        "max_position_fraction": "0.10", "max_aggregate_fraction": "0.30",
        "max_daily_loss_fraction": "0.03", "max_drawdown_fraction": "0.05",
        "max_signals_per_session": 10, "max_signal_age_seconds": 900,
        "min_stop_distance_fraction": "0.005", "max_stop_distance_fraction": "0.05",
        "min_target_distance_fraction": "0.01",
        "supported_symbols": ["BTCUSDT"], "supported_timeframes": ["minute15"],
        "eligible_strategies": [{"id": "trend", "version": "1.0.0"}],
    }
    value.update(changes)
    return value


NOW = "2026-08-17T00:05:00Z"


def decide(sig=None, st=None, pol=None):
    return evaluate_risk(sig or signal(), st or state(), pol or policy(), evaluated_at=NOW)


def test_valid_paper_signal_is_allowed_with_deterministic_amounts():
    decision = decide()
    assert decision.allowed is True
    assert decision.reason_code == "risk_allowed"
    assert str(decision.proposed_notional) == "600.00"
    assert decision.policy_version == "1.0.0"


@pytest.mark.parametrize(
    ("sig_changes", "state_changes", "policy_changes", "reason"),
    [
        ({"source_timestamp": "2026-08-16T00:00:00Z"}, {}, {}, "signal_stale"),
        ({}, {"seen_signal_ids": ["sig-1"]}, {}, "signal_duplicate"),
        ({"symbol": "ETHUSDT"}, {}, {}, "symbol_unsupported"),
        ({"timeframe": "hour1"}, {}, {}, "timeframe_unsupported"),
        ({"strategy_version": "2.0.0"}, {}, {}, "strategy_ineligible"),
        ({}, {"session_open": False}, {}, "session_closed"),
        ({}, {"signals_today": 10}, {}, "session_signal_limit"),
        ({}, {"kill_switch": True}, {}, "kill_switch_enabled"),
        ({}, {"data_circuit_open": True}, {}, "data_circuit_open"),
        ({}, {"strategy_circuit_open": True}, {}, "strategy_circuit_open"),
        ({}, {"provider_circuit_open": True}, {}, "provider_circuit_open"),
        ({}, {"daily_realized_pnl": "-400"}, {}, "daily_loss_limit"),
        ({}, {"equity": "9400"}, {}, "drawdown_limit"),
        ({"quantity": "0.02"}, {}, {}, "position_size_limit"),
        ({}, {"current_exposure": "2500"}, {}, "aggregate_exposure_limit"),
        ({"stop_price": "59950"}, {}, {}, "stop_distance_invalid"),
        ({"target_price": "60100"}, {}, {}, "target_distance_invalid"),
        ({"stop_price": "61000"}, {}, {}, "protective_prices_invalid"),
    ],
)
def test_each_policy_boundary_denies_with_stable_reason(sig_changes, state_changes, policy_changes, reason):
    decision = decide(signal(**sig_changes), state(**state_changes), policy(**policy_changes))
    assert decision.allowed is False
    assert decision.reason_code == reason


def test_manual_signal_uses_same_risk_path():
    allowed = decide(signal(provenance_kind="manual"))
    denied = decide(signal(provenance_kind="manual", quantity="0.02"))
    assert allowed.allowed is True
    assert denied.reason_code == "position_size_limit"


@pytest.mark.parametrize("field", ["quantity", "reference_price", "stop_price", "target_price"])
@pytest.mark.parametrize("value", [1.5, "NaN", "Infinity", "0", "-1"])
def test_malformed_numeric_inputs_fail_closed(field, value):
    with pytest.raises(RiskInputError):
        decide(signal(**{field: value}))


def test_unknown_fields_and_future_timestamp_fail_closed():
    unknown = signal()
    unknown["live_order"] = True
    with pytest.raises(RiskInputError, match="schema mismatch"):
        decide(unknown)
    assert decide(signal(source_timestamp="2026-08-17T00:06:00Z")).reason_code == "signal_timestamp_future"


def test_inputs_are_not_mutated_and_repeated_decision_is_identical():
    sig, st, pol = signal(), state(), policy()
    originals = deepcopy((sig, st, pol))
    assert decide(sig, st, pol) == decide(sig, st, pol)
    assert (sig, st, pol) == originals
