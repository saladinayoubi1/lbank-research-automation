"""Independent, lot-aware RESEARCH Paper ledger; no owner-profile migration.

Each open tranche is keyed by position_id, not symbol. There is deliberately no
numeric cap on trade or position COUNT: monetary, cash, stop-risk, drawdown and
per-symbol exposure limits always apply. This module has NO broker access, does
not modify current ProductRuntime/Paper v1, and cannot promote strategies.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

SCHEMA = "nexus.isolated-research-paper-tranches.v1"
POLICY = {
    "max_position_fraction": "0.10",
    "max_symbol_fraction": "0.10",
    "max_aggregate_fraction": "0.30",
    "max_stop_risk_fraction": "0.01",
    "max_drawdown_fraction": "0.10",
    "max_session_loss_fraction": "0.05",
}
_SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_EXIT_REASONS = {
    "stop", "target", "time_exit", "regime_exit",
    "manual_paper", "kill_switch_exit",
}


class TrancheError(ValueError):
    pass


class TrancheRiskRejected(TrancheError):
    def __init__(self, reason_code: str):
        self.reason_code = reason_code
        super().__init__(reason_code)


def _decimal(value: Any, name: str, *, strictly_positive: bool = False) -> Decimal:
    if isinstance(value, (float, bool)):
        raise TrancheError(f"{name} must be an exact decimal value")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TrancheError(f"{name} is not a decimal") from exc
    if not result.is_finite() or (strictly_positive and result <= 0):
        raise TrancheError(f"{name} is invalid")
    return result


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _seal(book: Mapping[str, Any]) -> dict[str, Any]:
    core = dict(book)
    core.pop("book_digest", None)
    return {**core, "book_digest": _digest(core)}


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise TrancheError(f"{name} must be a bounded identifier")
    if any(c in value for c in ("/", "\\", "\n", "\r", "\0")):
        raise TrancheError(f"{name} contains forbidden characters")
    return value


def _policy(policy: Mapping[str, Any]) -> dict[str, str]:
    if set(policy) != set(POLICY):
        raise TrancheError("risk policy schema mismatch")
    parsed = {key: _decimal(value, key) for key, value in policy.items()}
    if any(not 0 < value <= 1 for value in parsed.values()):
        raise TrancheError("monetary risk limits must be in (0,1]")
    if not (
        parsed["max_stop_risk_fraction"] <= parsed["max_position_fraction"]
        <= parsed["max_symbol_fraction"]
        <= parsed["max_aggregate_fraction"]
    ):
        raise TrancheError("risk budget hierarchy is invalid")
    return {key: str(value) for key, value in parsed.items()}


def new_book(
    *,
    profile_id: str,
    source_sha: str,
    opening_cash: str = "500",
    policy: Mapping[str, Any] = POLICY,
) -> dict[str, Any]:
    """Create a NEW isolated profile; never restore/reset the owner's journal."""
    _identifier(profile_id, "profile_id")
    if not _SOURCE_RE.fullmatch(source_sha):
        raise TrancheError("source SHA must be a concrete Git commit")
    starting = _decimal(opening_cash, "opening_cash", strictly_positive=True)
    core = {
        "schema_version": SCHEMA,
        "profile_kind": "isolated_research_paper",
        "profile_id": profile_id,
        "source_sha": source_sha,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
        "starting_cash": str(starting),
        "cash": str(starting),
        "realized_pnl": "0",
        "fees_paid": "0",
        "peak_equity": str(starting),
        "session_start_equity": str(starting),
        "session_realized_pnl": "0",
        "positions": [],
        "history": [],
        "events": [],
        "last_event_digest": "0" * 64,
        "kill_switch": False,
        "risk_policy": _policy(policy),
    }
    return _seal(core)


def verify_book(value: Mapping[str, Any]) -> dict[str, Any]:
    """Reject partial edits, reordered events, duplicate lots or authority drift."""
    if not isinstance(value, Mapping):
        raise TrancheError("tranche book must be an object")
    book = deepcopy(dict(value))
    claimed = book.pop("book_digest", None)
    if claimed != _digest(book) or book.get("schema_version") != SCHEMA:
        raise TrancheError("tranche book digest/schema mismatch")
    if (
        book.get("profile_kind") != "isolated_research_paper"
        or book.get("research_only") is not True
        or book.get("paper_only") is not True
        or book.get("live_trading_authority") is not False
        or book.get("automatic_strategy_promotion") is not False
        or not _SOURCE_RE.fullmatch(str(book.get("source_sha", "")))
    ):
        raise TrancheError("tranche authority/provenance mismatch")
    _identifier(book.get("profile_id"), "profile_id")
    _policy(book["risk_policy"])
    previous = "0" * 64
    if not isinstance(book.get("events"), list):
        raise TrancheError("tranche event chain unavailable")
    for index, event in enumerate(book["events"]):
        if not isinstance(event, dict) or event.get("sequence") != index + 1:
            raise TrancheError("tranche event sequence mismatch")
        core = dict(event)
        digest = core.pop("digest", None)
        if event.get("previous_digest") != previous or digest != _digest(core):
            raise TrancheError("tranche event digest chain mismatch")
        previous = digest
    if previous != book.get("last_event_digest"):
        raise TrancheError("tranche last event digest mismatch")
    if not isinstance(book.get("positions"), list) or not isinstance(book.get("history"), list):
        raise TrancheError("tranche positions/history unavailable")
    ids: set[str] = set()
    for row in book["positions"] + book["history"]:
        if not isinstance(row, dict):
            raise TrancheError("tranche position entry invalid")
        lot_id = _identifier(row.get("position_id"), "position_id")
        if lot_id in ids:
            raise TrancheError("duplicate lot identity")
        ids.add(lot_id)
        quantity = _decimal(row.get("quantity"), "quantity", strictly_positive=True)
        entry = _decimal(row.get("entry"), "entry", strictly_positive=True)
        stop = _decimal(row.get("stop"), "stop", strictly_positive=True)
        target = _decimal(row.get("target"), "target", strictly_positive=True)
        _decimal(row.get("entry_fee"), "entry_fee")
        _identifier(row.get("symbol"), "symbol")
        _identifier(row.get("strategy_id"), "strategy_id")
        _identifier(row.get("strategy_version"), "strategy_version")
        _identifier(row.get("risk_budget_id"), "risk_budget_id")
        _identifier(row.get("opened_utc"), "opened_utc")
        if quantity <= 0 or not stop < entry < target:
            raise TrancheError("tranche stop/entry/target invalid")
    for field in ("starting_cash", "cash", "peak_equity", "session_start_equity"):
        _decimal(book.get(field), field, strictly_positive=(field != "cash"))
    if _decimal(book["cash"], "cash") < 0:
        raise TrancheError("negative available simulated cash")
    if not isinstance(book.get("kill_switch"), bool):
        raise TrancheError("tranche kill switch invalid")
    return value if isinstance(value, dict) else dict(value)


def _mark_equity(book: Mapping[str, Any], marks: Mapping[str, Any] | None) -> tuple[Decimal, dict[str, Decimal]]:
    known = {} if marks is None else {
        str(symbol): _decimal(price, "mark_price", strictly_positive=True)
        for symbol, price in marks.items()
    }
    missing = {lot["symbol"] for lot in book["positions"]}.difference(known)
    if missing:
        raise TrancheRiskRejected("MARKET_PRICE_MISSING_FAIL_CLOSED")
    equity = _decimal(book["cash"], "cash") + sum(
        (_decimal(lot["quantity"], "quantity") * known[lot["symbol"]]
         for lot in book["positions"]), Decimal(0)
    )
    return equity, known


def mark_to_market(book: Mapping[str, Any], marks: Mapping[str, Any]) -> dict[str, str]:
    verify_book(book)
    equity, known = _mark_equity(book, marks)
    return {
        "equity": str(equity),
        "unrealized_pnl": str(sum(
            (_decimal(lot["quantity"], "quantity")
             * (known[lot["symbol"]] - _decimal(lot["entry"], "entry"))
             for lot in book["positions"]), Decimal(0)
        )),
        "open_position_count": len(book["positions"]),
        "completed_round_trips": len(book["history"]),
    }


def _commit(book: Mapping[str, Any], operation: str, position: Mapping[str, Any]) -> dict[str, Any]:
    next_book = deepcopy(dict(book))
    next_book.pop("book_digest", None)
    core = {
        "sequence": len(next_book["events"]) + 1,
        "previous_digest": next_book["last_event_digest"],
        "operation": operation,
        "position": dict(position),
    }
    event = {**core, "digest": _digest(core)}
    next_book["events"].append(event)
    next_book["last_event_digest"] = event["digest"]
    return _seal(next_book)


def open_tranche(
    book: Mapping[str, Any],
    *,
    position_id: str, symbol: str, timeframe: str, strategy_id: str,
    strategy_version: str, risk_budget_id: str, evidence_sha256: str,
    quantity: str, entry: str, stop: str, target: str,
    opened_utc: str, entry_fee_bps: str = "10",
    marks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """A new logical lot, independently stop/target-attributed; no count quota."""
    verify_book(book)
    if book["kill_switch"]:
        raise TrancheRiskRejected("KILL_SWITCH_ENABLED")
    for key, value in (
        ("position_id", position_id), ("symbol", symbol), ("timeframe", timeframe),
        ("strategy_id", strategy_id), ("strategy_version", strategy_version),
        ("risk_budget_id", risk_budget_id), ("opened_utc", opened_utc),
    ):
        _identifier(value, key)
    if not _DIGEST_RE.fullmatch(evidence_sha256):
        raise TrancheError("research evidence digest is required")
    if any(row["position_id"] == position_id for row in book["positions"] + book["history"]):
        raise TrancheRiskRejected("DUPLICATE_POSITION_ID")
    qty = _decimal(quantity, "quantity", strictly_positive=True)
    price = _decimal(entry, "entry", strictly_positive=True)
    stop_price = _decimal(stop, "stop", strictly_positive=True)
    target_price = _decimal(target, "target", strictly_positive=True)
    fee_bps = _decimal(entry_fee_bps, "entry_fee_bps")
    if not stop_price < price < target_price or not 0 <= fee_bps <= 100:
        raise TrancheError("invalid long-only protective prices or simulated fee")
    current_equity, known = _mark_equity(book, marks)
    policy = {key: Decimal(value) for key, value in book["risk_policy"].items()}
    prior_peak = _decimal(book["peak_equity"], "peak_equity")
    session_start = _decimal(book["session_start_equity"], "session_start_equity")
    if current_equity < prior_peak * (1 - policy["max_drawdown_fraction"]):
        raise TrancheRiskRejected("DRAWDOWN_LIMIT")
    if _decimal(book["session_realized_pnl"], "session_realized_pnl") < -session_start * policy["max_session_loss_fraction"]:
        raise TrancheRiskRejected("SESSION_LOSS_LIMIT")
    notional = qty * price
    fee = notional * fee_bps / Decimal(10_000)
    cash = _decimal(book["cash"], "cash")
    if notional + fee > cash:
        raise TrancheRiskRejected("AVAILABLE_CASH_LIMIT")
    if notional > current_equity * policy["max_position_fraction"]:
        raise TrancheRiskRejected("POSITION_SIZE_LIMIT")
    if qty * (price - stop_price) > current_equity * policy["max_stop_risk_fraction"]:
        raise TrancheRiskRejected("STOP_RISK_LIMIT")
    symbol_exposure = sum(
        (_decimal(lot["quantity"], "quantity") * known[lot["symbol"]]
         for lot in book["positions"] if lot["symbol"] == symbol), Decimal(0)
    )
    total_exposure = sum(
        (_decimal(lot["quantity"], "quantity") * known[lot["symbol"]]
         for lot in book["positions"]), Decimal(0)
    )
    if symbol_exposure + notional > current_equity * policy["max_symbol_fraction"]:
        raise TrancheRiskRejected("SYMBOL_EXPOSURE_LIMIT")
    if total_exposure + notional > current_equity * policy["max_aggregate_fraction"]:
        raise TrancheRiskRejected("AGGREGATE_EXPOSURE_LIMIT")
    lot = {
        "position_id": position_id, "symbol": symbol, "timeframe": timeframe,
        "strategy_id": strategy_id, "strategy_version": strategy_version,
        "risk_budget_id": risk_budget_id, "evidence_sha256": evidence_sha256,
        "quantity": str(qty), "entry": str(price), "stop": str(stop_price),
        "target": str(target_price), "opened_utc": opened_utc,
        "entry_fee": str(fee),
    }
    result = deepcopy(dict(book))
    result.pop("book_digest", None)
    result["positions"].append(lot)
    result["cash"] = str(cash - notional - fee)
    result["fees_paid"] = str(_decimal(book["fees_paid"], "fees_paid") + fee)
    result["peak_equity"] = str(max(prior_peak, current_equity))
    return _commit(result, "open", lot)


def close_tranche(
    book: Mapping[str, Any],
    *,
    position_id: str, exit_price: str, closed_utc: str,
    reason: str, exit_fee_bps: str = "10",
    remaining_marks: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    verify_book(book)
    _identifier(position_id, "position_id")
    _identifier(closed_utc, "closed_utc")
    if reason not in _EXIT_REASONS:
        raise TrancheError("unsupported isolated Paper exit reason")
    price = _decimal(exit_price, "exit_price", strictly_positive=True)
    fee_bps = _decimal(exit_fee_bps, "exit_fee_bps")
    if not 0 <= fee_bps <= 100:
        raise TrancheError("exit fee outside simulated Paper bounds")
    matching = [lot for lot in book["positions"] if lot["position_id"] == position_id]
    if len(matching) != 1:
        raise TrancheRiskRejected("POSITION_NOT_OPEN")
    lot = matching[0]
    result = deepcopy(dict(book))
    result.pop("book_digest", None)
    result["positions"] = [row for row in book["positions"] if row["position_id"] != position_id]
    _mark_equity(result, remaining_marks)
    qty = _decimal(lot["quantity"], "quantity")
    entry = _decimal(lot["entry"], "entry")
    fee = qty * price * fee_bps / Decimal(10_000)
    pnl = qty * (price - entry) - _decimal(lot["entry_fee"], "entry_fee") - fee
    completed = {
        **lot, "exit": str(price), "exit_fee": str(fee), "net_pnl": str(pnl),
        "closed_utc": closed_utc, "exit_reason": reason,
    }
    result["history"].append(completed)
    result["cash"] = str(_decimal(book["cash"], "cash") + qty * price - fee)
    result["realized_pnl"] = str(_decimal(book["realized_pnl"], "realized_pnl") + pnl)
    result["session_realized_pnl"] = str(_decimal(book["session_realized_pnl"], "session_realized_pnl") + pnl)
    result["fees_paid"] = str(_decimal(book["fees_paid"], "fees_paid") + fee)
    return _commit(result, "close", completed)


def bracket_exits(
    book: Mapping[str, Any], *,
    symbol: str, candle_open: str, candle_high: str, candle_low: str,
) -> list[dict[str, str]]:
    """Completed-candle inspection. Ambiguous stop/target ALWAYS stops first."""
    verify_book(book)
    opening = _decimal(candle_open, "candle_open", strictly_positive=True)
    high = _decimal(candle_high, "candle_high", strictly_positive=True)
    low = _decimal(candle_low, "candle_low", strictly_positive=True)
    if not low <= opening <= high:
        raise TrancheError("completed candle OHLC invariant invalid")
    results: list[dict[str, str]] = []
    for lot in book["positions"]:
        if lot["symbol"] != symbol:
            continue
        stop = Decimal(lot["stop"])
        target = Decimal(lot["target"])
        if low <= stop:
            results.append({
                "position_id": lot["position_id"],
                "exit_price": str(min(opening, stop)),
                "reason": "stop",
            })
        elif high >= target:
            results.append({
                "position_id": lot["position_id"],
                "exit_price": str(target),
                "reason": "target",
            })
    return results
