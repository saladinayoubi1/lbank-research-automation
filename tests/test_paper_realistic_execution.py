from decimal import Decimal

import pytest

from deterministic_risk import RiskDecision
from paper_event_store import GENESIS_DIGEST, build_event, replay
from paper_execution import PaperExecutionError, execute_paper_command


TIME = "2026-08-17T00:00:05Z"


def provenance():
    return {
        "kind": "automatic",
        "source_id": "validated-dataset",
        "source_timestamp": "2026-08-17T00:00:00Z",
        "received_timestamp": "2026-08-17T00:00:01Z",
        "timeframe": "minute15",
        "confidence": "0.9",
        "strategy_version": "1.0.0",
        "policy_version": "1.0.0",
    }


def initial_state():
    first = build_event(
        event_id="account:1", event_type="demo_account_opened", aggregate_id="paper-1",
        sequence=1, occurred_at="2026-08-17T00:00:01Z", correlation_id="setup",
        causation_id="setup-account", provenance=provenance(),
        previous_event_digest=GENESIS_DIGEST,
        payload={"currency": "USDT", "opening_cash": "10000"},
    )
    second = build_event(
        event_id="account:2", event_type="session_boundary_recorded", aggregate_id="paper-1",
        sequence=2, occurred_at="2026-08-17T00:00:02Z", correlation_id="setup",
        causation_id="setup-session", provenance=provenance(),
        previous_event_digest=first["event_digest"], payload={"boundary": "open"},
    )
    return replay([first, second]).state


def command(operation="open", **changes):
    value = {
        "operation": operation, "symbol": "BTCUSDT", "side": "long",
        "quantity": "0.05", "reference_price": "60000", "stop_price": "58000",
        "target_price": "64000", "fee_rate": "0.001", "slippage_bps": "10",
        "currency": "USDT",
    }
    value.update(changes)
    return value


def approved(cmd, signal_id):
    return RiskDecision(
        allowed=True,
        reason_code="risk_allowed",
        policy_id="paper-risk",
        policy_version="1.0.0",
        signal_id=signal_id,
        proposed_notional=Decimal(str(cmd["quantity"])) * Decimal(str(cmd["reference_price"])),
        resulting_exposure=Decimal(str(cmd["quantity"])) * Decimal(str(cmd["reference_price"])),
    )


def execute(state, cmd, signal_id, *, profile=None, correlation="run"):
    return execute_paper_command(
        command=cmd,
        state=state,
        risk_decision=approved(cmd, signal_id),
        occurred_at=TIME,
        provenance=provenance(),
        correlation_id=correlation,
        causation_id=signal_id,
        execution_profile=profile,
    )


def partial_profile():
    return {"latency_ms": 25, "per_fill_quantity": "0.01", "max_fills": 2}


def test_partial_open_replays_only_filled_quantity_and_truthful_remainder():
    result = execute(initial_state(), command(), "sig-open", profile=partial_profile())
    assert result.execution_status == "PARTIALLY_FILLED"
    assert result.filled_quantity == Decimal("0.02")
    assert result.remaining_quantity == Decimal("0.03")
    assert result.state.positions == (("BTCUSDT", "long", Decimal("0.02"), Decimal("60060.00000000")),)
    fills = [event for event in result.events if event["event_type"] == "simulated_fill_recorded"]
    assert len(fills) == 2
    assert [event["payload"]["quantity"] for event in fills] == ["0.01", "0.01"]
    assert result.fee == Decimal("1.20120000")
    assert result.slippage_cost == Decimal("1.20000000")


def test_partial_close_becomes_reduction_and_preserves_protection():
    opened = execute(initial_state(), command(), "sig-open", correlation="open")
    close_cmd = command(
        "close", quantity="0.05", reference_price="62000", stop_price="63000", target_price="59000"
    )
    closed = execute(opened.state, close_cmd, "sig-close", profile=partial_profile(), correlation="close")
    assert closed.execution_status == "PARTIALLY_FILLED"
    assert closed.state.positions[0][2] == Decimal("0.03")
    assert closed.state.stops == (("BTCUSDT", Decimal("58000")),)
    assert closed.state.targets == (("BTCUSDT", Decimal("64000")),)
    assert "position_reduced" in [event["event_type"] for event in closed.events]
    assert "position_closed" not in [event["event_type"] for event in closed.events]


def test_partial_reverse_fails_before_any_state_is_applied():
    opened = execute(initial_state(), command(), "sig-open", correlation="open")
    reverse_cmd = command(
        "reverse", side="short", quantity="0.05", stop_price="62000", target_price="56000"
    )
    before = opened.state
    with pytest.raises(PaperExecutionError, match="partial reverse"):
        execute(before, reverse_cmd, "sig-reverse", profile=partial_profile(), correlation="reverse")
    assert opened.state == before


def test_default_profile_preserves_full_fill_execution_behavior():
    result = execute(initial_state(), command(quantity="0.01"), "sig-default")
    assert result.execution_status == "FILLED"
    assert result.filled_quantity == Decimal("0.01")
    assert result.remaining_quantity == Decimal("0")
    assert len([event for event in result.events if event["event_type"] == "simulated_fill_recorded"]) == 1
    assert result.fill_price == Decimal("60060.00000000")


def test_realistic_profile_does_not_weaken_risk_amount_binding():
    cmd = command()
    decision = approved(cmd, "sig")
    bad = RiskDecision(**{**decision.__dict__, "proposed_notional": Decimal("1")})
    with pytest.raises(PaperExecutionError, match="risk approval amount mismatch"):
        execute_paper_command(
            command=cmd,
            state=initial_state(),
            risk_decision=bad,
            occurred_at=TIME,
            provenance=provenance(),
            correlation_id="risk",
            causation_id="sig",
            execution_profile=partial_profile(),
        )
