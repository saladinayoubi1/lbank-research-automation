from copy import deepcopy
from decimal import Decimal

import pytest

from paper_event_store import (
    GENESIS_DIGEST,
    PaperEventError,
    PortfolioState,
    build_event,
    replay,
    replay_or_previous,
    validate_event,
)


def provenance(*, kind="automatic", source="2026-08-17T00:00:00Z", received="2026-08-17T00:00:01Z", timeframe="minute15"):
    return {
        "kind": kind,
        "source_id": "market-data-validator",
        "source_timestamp": source,
        "received_timestamp": received,
        "timeframe": timeframe,
        "confidence": "0.95",
        "strategy_version": "strategy-v1",
        "policy_version": "risk-v1",
    }


def make_event(sequence, event_type, payload, previous=GENESIS_DIGEST, **overrides):
    values = {
        "event_id": f"event-{sequence}",
        "event_type": event_type,
        "aggregate_id": "paper-account-1",
        "sequence": sequence,
        "occurred_at": f"2026-08-17T00:00:{sequence + 1:02d}Z",
        "correlation_id": "run-1",
        "causation_id": f"cause-{sequence}",
        "provenance": provenance(),
        "previous_event_digest": previous,
        "payload": payload,
    }
    values.update(overrides)
    return build_event(**values)


def account_event():
    return make_event(1, "demo_account_opened", {"currency": "USDT", "opening_cash": "10000.00"})


def test_canonical_event_digest_is_deterministic_and_decimal_safe():
    first = account_event()
    second = account_event()
    assert first == second
    assert first["payload"]["opening_cash"] == "10000.00"
    assert len(first["event_digest"]) == 64
    assert validate_event(first) == first


def test_replay_reconstructs_paper_portfolio_and_controls():
    opened = account_event()
    position = make_event(
        2,
        "position_opened",
        {"symbol": "BTCUSDT", "side": "long", "quantity": "0.25", "entry_price": "60000"},
        opened["event_digest"],
    )
    stop = make_event(3, "stop_set", {"symbol": "BTCUSDT", "price": "58000"}, position["event_digest"])
    target = make_event(4, "target_set", {"symbol": "BTCUSDT", "price": "65000"}, stop["event_digest"])
    fee = make_event(5, "fee_recorded", {"amount": "4.25", "currency": "USDT"}, target["event_digest"])
    snapshot = make_event(
        6,
        "equity_snapshot_recorded",
        {"cash": "9995.75", "equity": "10200.50", "unrealized_pnl": "204.75"},
        fee["event_digest"],
    )
    kill = make_event(
        7,
        "kill_switch_transitioned",
        {"enabled": True, "reason_code": "operator-test"},
        snapshot["event_digest"],
    )

    result = replay([opened, position, stop, target, fee, snapshot, kill])

    assert result.applied_events == 7
    assert result.state.cash == Decimal("9995.75")
    assert result.state.equity == Decimal("10200.50")
    assert result.state.positions == (("BTCUSDT", "long", Decimal("0.25"), Decimal("60000")),)
    assert result.state.stops == (("BTCUSDT", Decimal("58000")),)
    assert result.state.targets == (("BTCUSDT", Decimal("65000")),)
    assert result.state.kill_switch_enabled is True


def test_manual_and_automatic_provenance_remain_explicit():
    automatic = account_event()
    manual = make_event(
        2,
        "risk_rejection_recorded",
        {"reason_code": "manual-veto"},
        automatic["event_digest"],
        provenance=provenance(kind="manual"),
    )
    assert automatic["provenance"]["kind"] == "automatic"
    assert manual["provenance"]["kind"] == "manual"
    assert replay([automatic, manual]).applied_events == 2


@pytest.mark.parametrize("value", [1.5, "NaN", "Infinity", "-1", "0"])
def test_non_deterministic_or_non_positive_opening_cash_is_rejected(value):
    with pytest.raises(PaperEventError):
        make_event(1, "demo_account_opened", {"currency": "USDT", "opening_cash": value})


def test_stale_or_causally_invalid_provenance_is_rejected():
    with pytest.raises(PaperEventError, match="stale"):
        make_event(
            1,
            "signal_recorded",
            {"symbol": "BTCUSDT", "timeframe": "minute15", "side": "buy", "quantity": "1", "reference_price": "1"},
            provenance=provenance(source="2026-08-16T20:00:00Z"),
        )
    with pytest.raises(PaperEventError, match="causally"):
        make_event(1, "demo_account_opened", {"currency": "USDT", "opening_cash": "1"}, provenance=provenance(received="2026-08-17T00:00:05Z"))


def test_unknown_schema_and_live_authority_fields_are_denied():
    with pytest.raises(PaperEventError, match="unknown event type"):
        make_event(1, "live_order_submitted", {})
    with pytest.raises(PaperEventError, match="schema mismatch"):
        make_event(1, "demo_account_opened", {"currency": "USDT", "opening_cash": "1", "extra": "no"})
    with pytest.raises(PaperEventError, match="forbidden"):
        make_event(1, "demo_account_opened", {"currency": "USDT", "opening_cash": "1", "api_key": "secret"})


def test_tampering_chain_breaks_duplicates_and_reordering_are_rejected():
    first = account_event()
    second = make_event(2, "session_boundary_recorded", {"boundary": "open"}, first["event_digest"])
    tampered = deepcopy(second)
    tampered["payload"]["boundary"] = "close"
    with pytest.raises(PaperEventError, match="digest"):
        replay([first, tampered])

    duplicate_id = make_event(
        2, "session_boundary_recorded", {"boundary": "open"}, first["event_digest"], event_id=first["event_id"]
    )
    with pytest.raises(PaperEventError, match="duplicate event_id"):
        replay([first, duplicate_id])

    gap = make_event(3, "session_boundary_recorded", {"boundary": "open"}, first["event_digest"])
    with pytest.raises(PaperEventError, match="sequence"):
        replay([first, gap])

    earlier = make_event(
        2,
        "session_boundary_recorded",
        {"boundary": "open"},
        first["event_digest"],
        occurred_at="2026-08-17T00:00:00Z",
        provenance=provenance(source="2026-08-16T23:59:58Z", received="2026-08-16T23:59:59Z"),
    )
    with pytest.raises(PaperEventError, match="UTC-time ordered"):
        replay([first, earlier])


def test_failed_incremental_replay_preserves_last_valid_state():
    first = account_event()
    previous = replay([first]).state
    bad = make_event(3, "session_boundary_recorded", {"boundary": "open"}, previous.last_event_digest)
    recovered = replay_or_previous([bad], previous)
    assert recovered == replay_or_previous([], previous)
    assert recovered.state == previous
    assert recovered.applied_events == 0


def test_position_invariants_fail_closed():
    first = account_event()
    bad_close = make_event(
        2,
        "position_closed",
        {"symbol": "BTCUSDT", "exit_price": "60000", "realized_pnl": "0"},
        first["event_digest"],
    )
    with pytest.raises(PaperEventError, match="missing position"):
        replay([first, bad_close])


def test_same_stream_always_reconstructs_same_state():
    first = account_event()
    second = make_event(2, "session_boundary_recorded", {"boundary": "open"}, first["event_digest"])
    assert replay([first, second]).state == replay([deepcopy(first), deepcopy(second)]).state
