from copy import deepcopy
from decimal import Decimal

import pytest

from deterministic_risk import RiskDecision
from paper_event_store import GENESIS_DIGEST, build_event, replay
from paper_execution import PaperExecutionError, execute_paper_command


TIME = "2026-08-17T00:00:05Z"


def provenance(kind="automatic"):
    return {
        "kind": kind,
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


def approved(signal_id="sig-1", proposed="600"):
    return RiskDecision(
        allowed=True, reason_code="risk_allowed", policy_id="paper-risk",
        policy_version="1.0.0", signal_id=signal_id,
        proposed_notional=Decimal(proposed), resulting_exposure=Decimal(proposed),
    )


def command(operation="open", **changes):
    value = {
        "operation": operation, "symbol": "BTCUSDT", "side": "long",
        "quantity": "0.01", "reference_price": "60000", "stop_price": "58000",
        "target_price": "64000", "fee_rate": "0.001", "slippage_bps": "10",
        "currency": "USDT",
    }
    value.update(changes)
    return value


def run(state, cmd, signal_id="sig-1", kind="automatic", correlation="run-1"):
    return execute_paper_command(
        command=cmd, state=state, risk_decision=approved(signal_id, str(Decimal(str(cmd["quantity"])) * Decimal(str(cmd["reference_price"])))),
        occurred_at=TIME, provenance=provenance(kind), correlation_id=correlation,
        causation_id=signal_id,
    )


def test_open_emits_attributable_events_and_reconstructs_accounting():
    result = run(initial_state(), command())
    kinds = [event["event_type"] for event in result.events]
    assert kinds == [
        "order_intent_recorded", "risk_decision_recorded", "simulated_fill_recorded",
        "position_opened", "stop_set", "target_set", "fee_recorded",
        "slippage_recorded", "equity_snapshot_recorded",
    ]
    assert result.fill_price == Decimal("60060.00000000")
    assert result.fee == Decimal("0.60060000")
    assert result.slippage_cost == Decimal("0.60000000")
    assert result.state.positions == (
        ("BTCUSDT", "long", Decimal("0.01"), Decimal("60060.00000000")),
    )
    assert result.state.cash == Decimal("9998.79940000")
    assert all(event["paper_trading_only"] is True for event in result.events)
    assert all(event["causation_id"] == "sig-1" for event in result.events)


def test_close_reconstructs_realized_pnl_and_removes_protection():
    opened = run(initial_state(), command()).state
    closed = run(
        opened,
        command("close", reference_price="62000", stop_price="63000", target_price="59000"),
        signal_id="sig-2", correlation="run-2",
    )
    assert closed.state.positions == ()
    assert closed.state.stops == ()
    assert closed.state.targets == ()
    assert closed.realized_pnl == Decimal("13.80000000")
    assert closed.state.realized_pnl == Decimal("13.80000000")


def test_reduce_and_reverse_are_deterministic():
    opened = run(initial_state(), command(quantity="0.02"), correlation="open").state
    reduced = run(
        opened,
        command("reduce", quantity="0.01", reference_price="61000", stop_price="62000", target_price="58000"),
        signal_id="sig-2", correlation="reduce",
    )
    assert reduced.state.positions[0][2] == Decimal("0.01")

    reversed_result = run(
        reduced.state,
        command("reverse", side="short", quantity="0.01", reference_price="59000", stop_price="61000", target_price="55000"),
        signal_id="sig-3", correlation="reverse",
    )
    assert reversed_result.state.positions[0][1] == "short"
    assert reversed_result.state.positions[0][2] == Decimal("0.01")


def test_manual_provenance_uses_identical_execution_path():
    result = run(initial_state(), command(), kind="manual")
    assert {event["provenance"]["kind"] for event in result.events} == {"manual"}


def test_denied_or_mismatched_risk_cannot_execute():
    denied = approved()
    denied = RiskDecision(**{**denied.__dict__, "allowed": False, "reason_code": "position_size_limit"})
    with pytest.raises(PaperExecutionError, match="risk approval"):
        execute_paper_command(
            command=command(), state=initial_state(), risk_decision=denied,
            occurred_at=TIME, provenance=provenance(), correlation_id="run",
            causation_id="sig-1",
        )
    with pytest.raises(PaperExecutionError, match="causation mismatch"):
        run(initial_state(), command(), signal_id="other")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"slippage_bps": "101"}, "slippage"),
        ({"fee_rate": "0.02"}, "fee_rate"),
        ({"quantity": 0.01}, "floating point"),
        ({"quantity": "NaN"}, "finite"),
        ({"operation": "live"}, "unsupported paper"),
    ],
)
def test_bounds_and_malformed_commands_fail_closed(changes, message):
    with pytest.raises(PaperExecutionError, match=message):
        run(initial_state(), command(**changes))


def test_position_transition_invariants_fail_closed():
    with pytest.raises(PaperExecutionError, match="existing position"):
        run(initial_state(), command("close"))
    opened = run(initial_state(), command(), correlation="first").state
    with pytest.raises(PaperExecutionError, match="existing position"):
        run(opened, command(), signal_id="sig-2")
    with pytest.raises(PaperExecutionError, match="smaller"):
        run(opened, command("reduce", quantity="0.01", reference_price="61000", stop_price="62000", target_price="58000"), signal_id="sig-2")
    with pytest.raises(PaperExecutionError, match="reverse quantity"):
        run(opened, command("reverse", side="short", quantity="0.02", stop_price="62000", target_price="56000"), signal_id="sig-2")


def test_kill_switch_session_currency_and_unknown_fields_fail_closed():
    blocked = initial_state()
    blocked = blocked.__class__(**{**blocked.__dict__, "kill_switch_enabled": True})
    with pytest.raises(PaperExecutionError, match="blocked"):
        run(blocked, command())
    with pytest.raises(PaperExecutionError, match="currency mismatch"):
        run(initial_state(), command(currency="USD"))
    unknown = command()
    unknown["live_order"] = True
    with pytest.raises(PaperExecutionError, match="schema mismatch"):
        run(initial_state(), unknown)


def test_same_inputs_produce_identical_events_and_state_without_mutation():
    state = initial_state()
    cmd = command()
    original = deepcopy(cmd)
    first = run(state, cmd)
    second = run(state, cmd)
    assert first == second
    assert cmd == original
