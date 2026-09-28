"""Regression and adversarial tests for an ISOLATED research ledger.

These are NOT current owner-profile migration/activation tests. Active Paper
v1 and its immutable existing event stream remain unchanged.
"""
from copy import deepcopy
from decimal import Decimal

import pytest

import nexus_isolated_paper_tranche_ledger as t


SHA = "a" * 40
EVIDENCE = "b" * 64
WHEN = "2026-09-28T00:00:00Z"


def book():
    return t.new_book(profile_id="safe-test-clone", source_sha=SHA)


def open_one(state, i=0, *, symbol="BTCUSDT", strategy="composite-structure", quantity="1", price="5", stop="4", target="6", marks=None):
    return t.open_tranche(
        state, position_id=f"p-{i}", symbol=symbol,
        timeframe="minute15", strategy_id=strategy,
        strategy_version="1.0.0", risk_budget_id="budget-test",
        evidence_sha256=EVIDENCE, quantity=quantity,
        entry=price, stop=stop, target=target,
        opened_utc=WHEN, marks=marks,
    )


@pytest.mark.parametrize("sequential_count", [1, 3, 25, 150])
def test_no_arbitrary_limit_on_sequential_completed_trades(sequential_count):
    state = book()
    for index in range(sequential_count):
        state = open_one(state, index)
        state = t.close_tranche(
            state, position_id=f"p-{index}", exit_price="5",
            closed_utc="2026-09-28T00:15:00Z",
            reason="time_exit",
        )
    assert len(state["history"]) == sequential_count
    assert len(state["positions"]) == 0
    assert len(state["events"]) == sequential_count * 2
    assert {p["position_id"] for p in state["history"]} == {
        f"p-{i}" for i in range(sequential_count)
    }
    assert Decimal(state["cash"]) < Decimal("500")  # entry and exit fees apply
    assert t.verify_book(state) == state


@pytest.mark.parametrize("simultaneous_count", [1, 2, 4])
def test_same_strategy_same_symbol_parallel_independent_tranches(simultaneous_count):
    state = book()
    for index in range(simultaneous_count):
        state = open_one(state, index, marks={"BTCUSDT": "5"} if index else None)
    assert len(state["positions"]) == simultaneous_count
    assert t.mark_to_market(state, {"BTCUSDT": "5"})["open_position_count"] == simultaneous_count
    # Close one exact lot; all other lots/stops/targets stay intact.
    chosen = f"p-{simultaneous_count - 1}"
    before = {p["position_id"]: p for p in state["positions"] if p["position_id"] != chosen}
    state = t.close_tranche(state, position_id=chosen, exit_price="6",
                            closed_utc="2026-09-28T00:15:00Z", reason="target",
                            remaining_marks={"BTCUSDT": "5"})
    assert {p["position_id"]: p for p in state["positions"]} == before
    assert len(state["history"]) == 1
    assert state["history"][0]["position_id"] == chosen
    assert Decimal(state["history"][0]["net_pnl"]) < Decimal("1")
    assert t.verify_book(state) == state


def test_pessimistic_same_bar_stop_wins_and_gap_through_is_worse():
    state = open_one(book())
    both = t.bracket_exits(state, symbol="BTCUSDT",
                           candle_open="5", candle_high="6", candle_low="4")
    assert both == [{"position_id": "p-0", "exit_price": "4", "reason": "stop"}]
    gap = t.bracket_exits(state, symbol="BTCUSDT",
                          candle_open="3.5", candle_high="6", candle_low="3.0")
    assert gap[0]["exit_price"] == "3.5"
    state = t.close_tranche(state, position_id=both[0]["position_id"],
                            exit_price=both[0]["exit_price"], reason=both[0]["reason"],
                            closed_utc="2026-09-28T00:15:00Z")
    assert state["history"][0]["exit_reason"] == "stop"


def test_symbol_cap_is_monetary_not_a_position_count_quota():
    state = book()
    for i in range(9):
        state = open_one(state, i, marks={"BTCUSDT": "5"} if i else None)
    with pytest.raises(t.TrancheRiskRejected, match="SYMBOL_EXPOSURE_LIMIT"):
        open_one(state, 9, marks={"BTCUSDT": "5"})
    assert len(state["positions"]) == 9


def test_aggregate_cap_with_multiple_symbols():
    state = book()
    for i, symbol in enumerate(("BTCUSDT", "ETHUSDT", "SOLUSDT")):
        marks = {s: "100" for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
        state = open_one(state, i, symbol=symbol, quantity="0.4",
                         price="100", stop="99", target="102", marks=marks)
    with pytest.raises(t.TrancheRiskRejected, match="AGGREGATE_EXPOSURE_LIMIT"):
        open_one(state, 4, symbol="XRPUSDT", quantity="0.4",
                 price="100", stop="99", target="102",
                 marks={"BTCUSDT": "100", "ETHUSDT": "100", "SOLUSDT": "100"})


def test_no_fabricated_market_marks_or_duplicate_position_ids():
    state = open_one(book())
    with pytest.raises(t.TrancheRiskRejected, match="MARKET_PRICE_MISSING"):
        open_one(state, 2)
    with pytest.raises(t.TrancheRiskRejected, match="DUPLICATE_POSITION_ID"):
        open_one(state, 0)
    with pytest.raises(t.TrancheRiskRejected, match="POSITION_NOT_OPEN"):
        t.close_tranche(state, position_id="unknown", exit_price="5",
                        closed_utc=WHEN, reason="time_exit")


def test_single_position_cap_and_real_stop_risk_preserved():
    with pytest.raises(t.TrancheRiskRejected, match="POSITION_SIZE_LIMIT"):
        open_one(book(), quantity="11")
    with pytest.raises(t.TrancheRiskRejected, match="STOP_RISK_LIMIT"):
        open_one(book(), quantity="1", price="40", stop="1", target="45")


def test_daily_loss_and_drawdown_remain_final_denials():
    losing = open_one(book(), quantity="0.4", price="100", stop="99", target="102")
    losing = t.close_tranche(
        losing, position_id="p-0", exit_price="0.01",
        closed_utc="2026-09-28T00:15:00Z", reason="stop",
    )
    with pytest.raises(t.TrancheRiskRejected, match="SESSION_LOSS_LIMIT"):
        open_one(losing, 2)
    stressed = book()
    stressed = open_one(stressed, 0, symbol="BTCUSDT", quantity="0.4",
                        price="100", stop="99", target="102")
    stressed = open_one(stressed, 1, symbol="ETHUSDT", quantity="0.4",
                        price="100", stop="99", target="102", marks={"BTCUSDT": "100"})
    with pytest.raises(t.TrancheRiskRejected, match="DRAWDOWN_LIMIT"):
        open_one(stressed, 2, symbol="SOLUSDT", quantity="0.1",
                 price="100", stop="99", target="102",
                 marks={"BTCUSDT": "0.01", "ETHUSDT": "0.01"})


def test_book_digest_chain_authority_and_input_immutability():
    source = book()
    original = deepcopy(source)
    after = open_one(source)
    assert source == original  # no in-place mutation of owner-like input
    tampered = deepcopy(after)
    tampered["positions"][0]["target"] = "9999999"
    with pytest.raises(t.TrancheError, match="digest"):
        t.verify_book(tampered)
    tampered = deepcopy(after)
    tampered["events"][0]["previous_digest"] = "bad"
    with pytest.raises(t.TrancheError, match="digest"):
        t.verify_book(tampered)
    tampered = deepcopy(after)
    tampered["live_trading_authority"] = True
    with pytest.raises(t.TrancheError, match="digest|authority"):
        t.verify_book(tampered)


def test_bad_costs_and_inputs_never_create_lots():
    with pytest.raises(t.TrancheError, match="fee"):
        t.open_tranche(
            book(), position_id="f", symbol="BTCUSDT", timeframe="minute15",
            strategy_id="s", strategy_version="1", risk_budget_id="b",
            evidence_sha256=EVIDENCE, quantity="1", entry="5", stop="4",
            target="6", opened_utc=WHEN, entry_fee_bps="-1",
        )
    with pytest.raises(t.TrancheError, match="decimal|invalid"):
        open_one(book(), quantity="Infinity")
    with pytest.raises(t.TrancheError, match="protective"):
        open_one(book(), price="5", stop="6", target="4")


def test_timestamp_finality_timezone_and_exits_are_causal():
    with pytest.raises(t.TrancheError, match="UTC"):
        t.open_tranche(
            book(), position_id="bad", symbol="BTCUSDT", timeframe="minute15",
            strategy_id="s", strategy_version="1", risk_budget_id="b",
            evidence_sha256=EVIDENCE, quantity="1", entry="5", stop="4",
            target="6", opened_utc="2026-09-28T00:00:00",
        )
    state = open_one(book())
    with pytest.raises(t.TrancheError, match="predates entry"):
        t.close_tranche(
            state, position_id="p-0", exit_price="5",
            closed_utc="2026-09-27T23:59:59Z", reason="time_exit",
        )
    with pytest.raises(t.TrancheError, match="UTC"):
        t.close_tranche(
            state, position_id="p-0", exit_price="5",
            closed_utc="2026-09-28T00:15:00+03:30", reason="time_exit",
        )


def test_kill_switch_fails_closed_and_does_not_release_existing_tranches():
    state = open_one(book())
    halted = t.trip_kill_switch(state, reason="research-circuit")
    assert halted["kill_switch"] is True
    assert len(halted["positions"]) == 1
    assert t.verify_book(halted) == halted
    assert t.trip_kill_switch(halted, reason="same") == halted
    with pytest.raises(t.TrancheRiskRejected, match="KILL_SWITCH"):
        open_one(halted, 2, marks={"BTCUSDT": "5"})
    # A risk-reducing close must still be possible when halted.
    closed = t.close_tranche(
        halted, position_id="p-0", exit_price="4",
        closed_utc="2026-09-28T00:15:00Z", reason="kill_switch_exit",
    )
    assert not closed["positions"]
    assert closed["kill_switch"] is True
