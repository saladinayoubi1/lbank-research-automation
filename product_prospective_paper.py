from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "nexus.bybit-prospective-paper-forward.v1"
EVENT_SCHEMA = "nexus.bybit-prospective-paper-forward-event.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
SNAPSHOT_RELATIVE_PATH = Path("prospective_paper") / "bybit_prospective_paper_forward_v1.json"
MAX_SNAPSHOT_BYTES = 5_000_000


class ProductProspectivePaperError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProductProspectivePaperError("prospective Paper state is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ProductProspectivePaperError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProductProspectivePaperError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise ProductProspectivePaperError(f"{label} must be finite")
    return number


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "contract_version": "nexus.product-prospective-paper.v1",
        "available": False,
        "read_only": True,
        "reason": reason,
        "paper_only": True,
        "live_trading_authority": False,
        "status": "unavailable",
        "positions": [],
        "profiles": {},
    }


def _verify_state(state: Mapping[str, Any]) -> None:
    if not isinstance(state, Mapping):
        raise ProductProspectivePaperError("prospective Paper state must be an object")
    core = dict(state)
    claimed = core.pop("state_digest", None)
    if not isinstance(claimed, str) or claimed != _digest(core):
        raise ProductProspectivePaperError("prospective Paper state digest mismatch")
    if state.get("schema_version") != SCHEMA:
        raise ProductProspectivePaperError("prospective Paper schema mismatch")
    if state.get("paper_only") is not True:
        raise ProductProspectivePaperError("prospective Paper authority is not paper-only")
    if state.get("live_trading_enabled") is not False:
        raise ProductProspectivePaperError("prospective Paper live authority widened")
    if state.get("private_credentials_used") is not False:
        raise ProductProspectivePaperError("prospective Paper private credentials detected")
    if state.get("automatic_live_promotion") is not False:
        raise ProductProspectivePaperError("prospective Paper auto-promotion detected")

    events = state.get("events")
    count = state.get("completed_bar_count")
    if not isinstance(events, list) or isinstance(count, bool) or not isinstance(count, int) or count != len(events):
        raise ProductProspectivePaperError("prospective Paper event count mismatch")
    previous = "0" * 64
    for sequence, event in enumerate(events, start=1):
        if not isinstance(event, Mapping):
            raise ProductProspectivePaperError("prospective Paper event is not an object")
        unsigned = dict(event)
        event_digest = unsigned.pop("event_digest", None)
        if (
            unsigned.get("schema_version") != EVENT_SCHEMA
            or unsigned.get("sequence") != sequence
            or unsigned.get("previous_event_digest") != previous
            or unsigned.get("paper_only") is not True
            or unsigned.get("live_trading_enabled") is not False
            or event_digest != _digest(unsigned)
        ):
            raise ProductProspectivePaperError("prospective Paper event chain rejected")
        previous = str(event_digest)

    profiles = state.get("profiles")
    if not isinstance(profiles, Mapping) or set(profiles) != {"conservative", "stress"}:
        raise ProductProspectivePaperError("prospective Paper profiles mismatch")
    for name, profile in profiles.items():
        if not isinstance(profile, Mapping):
            raise ProductProspectivePaperError(f"{name} profile is invalid")
        for field in ("wallet", "equity", "equity_high", "maximum_drawdown"):
            _finite_number(profile.get(field), f"{name}.{field}")
        positions = profile.get("positions")
        if not isinstance(positions, list) or len(positions) != len(SYMBOLS):
            raise ProductProspectivePaperError(f"{name} positions mismatch")
        for index, row in enumerate(positions):
            if not isinstance(row, Mapping):
                raise ProductProspectivePaperError(f"{name} position {index} is invalid")
            _finite_number(row.get("quantity"), f"{name}.positions[{index}].quantity")
            entry = _finite_number(row.get("average_entry"), f"{name}.positions[{index}].average_entry")
            if entry < 0:
                raise ProductProspectivePaperError(f"{name} position entry is negative")


def _profile_snapshot(name: str, profile: Mapping[str, Any]) -> dict[str, Any]:
    wallet = _finite_number(profile["wallet"], f"{name}.wallet")
    equity = _finite_number(profile["equity"], f"{name}.equity")
    positions: list[dict[str, Any]] = []
    for symbol, row in zip(SYMBOLS, profile["positions"], strict=True):
        quantity = _finite_number(row["quantity"], f"{name}.{symbol}.quantity")
        if abs(quantity) <= 1e-15:
            continue
        entry = _finite_number(row["average_entry"], f"{name}.{symbol}.average_entry")
        positions.append(
            {
                "symbol": symbol,
                "side": "long" if quantity > 0 else "short",
                "quantity": abs(quantity),
                "signed_quantity": quantity,
                "entry_price": entry,
                "profile": name,
                "source": "prospective_forward",
            }
        )
    unrealized = equity - wallet
    if len(positions) == 1:
        positions[0]["unrealized_pnl"] = unrealized
    return {
        "wallet": wallet,
        "equity": equity,
        "equity_high": _finite_number(profile["equity_high"], f"{name}.equity_high"),
        "maximum_drawdown": _finite_number(profile["maximum_drawdown"], f"{name}.maximum_drawdown"),
        "fill_count": int(profile.get("fill_count", 0)),
        "orders": int(profile.get("orders", 0)),
        "fees": _finite_number(profile.get("fees", 0.0), f"{name}.fees"),
        "funding_cashflow": _finite_number(profile.get("funding_cashflow", 0.0), f"{name}.funding_cashflow"),
        "margin_rejections": int(profile.get("margin_rejections", 0)),
        "liquidations": int(profile.get("liquidations", 0)),
        "unrealized_pnl": unrealized,
        "positions": positions,
    }


def load_prospective_paper_snapshot(product_data_root: Path) -> dict[str, Any]:
    path = Path(product_data_root) / SNAPSHOT_RELATIVE_PATH
    if not path.is_file():
        return _unavailable("snapshot_missing")
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_SNAPSHOT_BYTES:
            return _unavailable("snapshot_size_invalid")
        state = json.loads(path.read_text(encoding="utf-8"))
        _verify_state(state)
        profiles = {
            name: _profile_snapshot(name, state["profiles"][name])
            for name in ("conservative", "stress")
        }
        return {
            "contract_version": "nexus.product-prospective-paper.v1",
            "available": True,
            "read_only": True,
            "reason": None,
            "source": "bybit_prospective_paper_forward_v1",
            "paper_only": True,
            "live_trading_authority": False,
            "status": str(state.get("status", "unknown")),
            "decision": str(state.get("decision", "unknown")),
            "strategy_id": str(state.get("strategy_id", "")),
            "completed_bar_count": int(state["completed_bar_count"]),
            "last_execution_utc": state.get("last_execution_utc"),
            "state_digest": str(state["state_digest"]),
            "active_profile": "conservative",
            "positions": profiles["conservative"]["positions"],
            "profiles": profiles,
        }
    except (OSError, UnicodeError, json.JSONDecodeError, ProductProspectivePaperError, TypeError, ValueError):
        return _unavailable("snapshot_invalid")
