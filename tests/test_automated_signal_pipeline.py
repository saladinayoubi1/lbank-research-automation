from copy import deepcopy

import pytest

from automated_signal_pipeline import AutomatedSignalPipelineError, run_automated_signal_pipeline
from paper_event_store import GENESIS_DIGEST, build_event, replay


OCCURRED = "2026-08-17T00:05:00Z"
DIGEST = "a" * 64


def provenance():
    return {
        "kind": "automatic",
        "source_id": "setup",
        "source_timestamp": "2026-08-17T00:00:00Z",
        "received_timestamp": "2026-08-17T00:00:01Z",
        "timeframe": "minute15",
        "confidence": "1",
        "strategy_version": "1.0.0",
        "policy_version": "1.0.0",
    }


def portfolio_state():
    account = build_event(
        event_id="account:1", event_type="demo_account_opened", aggregate_id="paper-1",
        sequence=1, occurred_at="2026-08-17T00:00:01Z", correlation_id="setup",
        causation_id="setup-account", provenance=provenance(),
        previous_event_digest=GENESIS_DIGEST,
        payload={"currency": "USDT", "opening_cash": "10000"},
    )
    session = build_event(
        event_id="account:2", event_type="session_boundary_recorded", aggregate_id="paper-1",
        sequence=2, occurred_at="2026-08-17T00:00:02Z", correlation_id="setup",
        causation_id="setup-session", provenance=provenance(),
        previous_event_digest=account["event_digest"], payload={"boundary": "open"},
    )
    return replay([account, session]).state


def dataset(**changes):
    value = {
        "dataset_id": "btc-15m", "dataset_revision": "rev-42", "source_id": "lbank-public",
        "source_timestamp": "2026-08-17T00:00:00Z", "received_timestamp": "2026-08-17T00:00:01Z",
        "symbol": "BTCUSDT", "timeframe": "minute15", "readiness_status": "ready",
        "provenance_digest": DIGEST,
    }
    value.update(changes)
    return value


def qualification(**changes):
    value = {
        "artifact_id": "qualification-7", "artifact_digest": "b" * 64,
        "strategy_id": "trend", "strategy_version": "1.0.0", "dataset_id": "btc-15m",
        "dataset_revision": "rev-42", "status": "paper_eligible",
        "qualified_at": "2026-08-16T23:59:00Z",
    }
    value.update(changes)
    return value


def regime(**changes):
    value = {
        "regime_id": "regime-1", "regime_version": "1.0.0", "label": "trend-up",
        "confidence": "0.85", "source_timestamp": "2026-08-17T00:00:00Z",
        "dataset_id": "btc-15m", "dataset_revision": "rev-42", "symbol": "BTCUSDT",
        "timeframe": "minute15",
    }
    value.update(changes)
    return value


def decision(**changes):
    value = {
        "decision_id": "decision-1", "operation": "open", "side": "long", "quantity": "0.01",
        "reference_price": "60000", "stop_price": "58800", "target_price": "62400",
        "confidence": "0.80", "strategy_id": "trend", "strategy_version": "1.0.0",
        "dataset_id": "btc-15m", "dataset_revision": "rev-42", "regime_id": "regime-1",
        "regime_version": "1.0.0", "symbol": "BTCUSDT", "timeframe": "minute15",
        "source_timestamp": "2026-08-17T00:00:00Z", "correlation_id": "mission-1",
        "causation_id": "regime-1", "risk_policy_version": "1.0.0",
    }
    value.update(changes)
    return value


def risk_state(**changes):
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
        "min_target_distance_fraction": "0.01", "supported_symbols": ["BTCUSDT"],
        "supported_timeframes": ["minute15"],
        "eligible_strategies": [{"id": "trend", "version": "1.0.0"}],
    }
    value.update(changes)
    return value


def run(**changes):
    args = {
        "dataset": dataset(), "qualification": qualification(), "regime": regime(),
        "decision": decision(), "risk_state": risk_state(), "risk_policy": policy(),
        "portfolio_state": portfolio_state(), "occurred_at": OCCURRED,
        "fee_rate": "0.001", "slippage_bps": "10",
    }
    args.update(changes)
    return run_automated_signal_pipeline(**args)


def test_full_ready_qualified_regime_decision_risk_execution_path_is_paper_only():
    result = run()
    assert result.risk_decision.allowed is True
    assert result.execution is not None
    assert result.state.positions[0][0:3] == ("BTCUSDT", "long", result.execution.state.positions[0][2])
    assert result.state.positions[0][2].as_tuple().exponent == -2
    kinds = [event["event_type"] for event in result.events]
    assert kinds[0] == "signal_recorded"
    assert "risk_decision_recorded" in kinds
    assert "simulated_fill_recorded" in kinds
    assert "position_opened" in kinds
    assert all(event["paper_trading_only"] is True for event in result.events)
    assert result.events[1]["causation_id"] == result.signal["signal_id"]


def test_signal_binds_every_gate9_provenance_identity():
    signal = run().signal
    required = {
        "source_id", "dataset_id", "dataset_revision", "dataset_provenance_digest",
        "source_timestamp", "received_timestamp", "timeframe", "confidence",
        "strategy_id", "strategy_version", "qualification_artifact_id",
        "qualification_artifact_digest", "regime_id", "regime_version", "regime_label",
        "decision_id", "risk_policy_version", "correlation_id", "causation_id",
    }
    assert required <= set(signal)
    assert signal["paper_trading_only"] is True
    assert signal["provenance_kind"] == "automatic"


def test_risk_denial_records_rejection_and_never_executes():
    result = run(decision=decision(quantity="0.02"))
    assert result.risk_decision.allowed is False
    assert result.risk_decision.reason_code == "position_size_limit"
    assert result.execution is None
    assert [event["event_type"] for event in result.events] == [
        "signal_recorded", "risk_rejection_recorded"
    ]
    assert result.state.positions == ()


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("dataset", dataset(readiness_status="blocked"), "not ready"),
        ("qualification", qualification(status="research_only"), "not paper eligible"),
        ("qualification", qualification(dataset_revision="other"), "qualification dataset"),
        ("regime", regime(dataset_revision="other"), "regime dataset"),
        ("decision", decision(strategy_version="2.0.0"), "strategy binding"),
        ("decision", decision(regime_version="2.0.0"), "regime binding"),
        ("decision", decision(risk_policy_version="2.0.0"), "risk policy binding"),
        ("decision", decision(operation="close"), "only authorizes paper open"),
    ],
)
def test_binding_failures_stop_before_risk_or_execution(argument, value, message):
    with pytest.raises(AutomatedSignalPipelineError, match=message):
        run(**{argument: value})


def test_unknown_or_live_or_malformed_fields_fail_closed():
    with_live = decision()
    with_live["live_order"] = True
    with pytest.raises(AutomatedSignalPipelineError, match="schema mismatch"):
        run(decision=with_live)
    with pytest.raises(AutomatedSignalPipelineError, match="floating point"):
        run(decision=decision(quantity=0.01))
    with pytest.raises(AutomatedSignalPipelineError, match="between 0 and 1"):
        run(decision=decision(confidence="1.1"))


def test_same_inputs_are_deterministic_and_not_mutated():
    args = {
        "dataset": dataset(), "qualification": qualification(), "regime": regime(),
        "decision": decision(), "risk_state": risk_state(), "risk_policy": policy(),
        "portfolio_state": portfolio_state(), "occurred_at": OCCURRED,
        "fee_rate": "0.001", "slippage_bps": "10",
    }
    original = deepcopy(args)
    first = run_automated_signal_pipeline(**args)
    second = run_automated_signal_pipeline(**args)
    assert first == second
    assert args == original
