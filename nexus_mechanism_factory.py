"""Bounded declarative causal-mechanism factory for NEXUS Strategy Finder.

The factory is research-only. It does not execute orders, does not mutate owner
Paper state, and cannot grant Demo/Live promotion authority. Candidate contracts
are data, not Python code: only a small reviewed condition grammar and whitelisted
causal features are accepted. This lets Strategy Finder advance to new mechanism
contracts without adding a new signal_for() branch for every candidate.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

SCHEMA = "nexus.mechanism-factory.v1"
AUTHORITY = "research-only-no-auto-promotion"
ROOT = Path(__file__).resolve().parent
DEFAULT_CONTRACT = ROOT / "research" / "mechanism_factory_v1.json"
ID_RE = re.compile(r"^factory_[a-z][a-z0-9_]{2,72}$")

CONTEXT_FIELDS = frozenset({
    "h4_up", "h4_range", "h1_compression", "h1_vol_ok",
    "lagged_own_return_1h", "lagged_own_return_4h",
    "own_return_1h_abs_baseline", "own_realized_volatility",
    "own_realized_volatility_baseline", "rel_vol_previous",
    "trend_efficiency_16", "trend_direction_16", "lagged_return_serial_corr",
    "lagged_lower_wick_absorption", "lower_wick_absorption_baseline",
    "own_volatility_of_volatility", "own_volatility_of_volatility_baseline",
    "cross_pair_relative_z_previous", "lagged_peer_impulse",
    "lagged_peer_impulse_baseline", "lagged_own_response",
    "relative_momentum_previous", "relative_momentum_baseline",
    "cross_pair_volatility_ratio", "cross_pair_volatility_ratio_baseline",
    "peer_realized_volatility", "peer_realized_volatility_baseline",
    "peer_beta_lagged", "lagged_peer_beta_residual", "peer_beta_residual_scale",
    "prior_day_high", "prior_day_low", "prior_day_close",
})
ENTRY_FIELDS = frozenset({
    "open", "high", "low", "close", "close_location", "body_efficiency",
    "rel_vol", "bar_proxy_vwap", "prior_hi", "prior_lo", "prior_range_mid",
    "prior_range_width_pct", "prior_day_high", "prior_day_low", "prior_day_close",
})
PEER_FIELDS = frozenset({
    "cross_pair_relative_z_previous", "lagged_peer_impulse",
    "lagged_peer_impulse_baseline", "lagged_own_response",
    "relative_momentum_previous", "relative_momentum_baseline",
    "cross_pair_volatility_ratio", "cross_pair_volatility_ratio_baseline",
    "peer_realized_volatility", "peer_realized_volatility_baseline",
    "peer_beta_lagged", "lagged_peer_beta_residual", "peer_beta_residual_scale",
})
OPS = frozenset({"eq", "gt", "ge", "lt", "le"})


class MechanismFactoryError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MechanismFactoryError(f"{label} must be numeric")
    out = float(value)
    if not np.isfinite(out):
        raise MechanismFactoryError(f"{label} must be finite")
    return out


def _validate_condition(raw: Any, *, stage: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise MechanismFactoryError("factory condition must be an object")
    allowed = {"field", "op", "value", "other", "scale"}
    if set(raw) - allowed:
        raise MechanismFactoryError("factory condition contains unsupported keys")
    field = raw.get("field")
    op = raw.get("op")
    if not isinstance(field, str) or op not in OPS:
        raise MechanismFactoryError("factory condition field/operator invalid")
    whitelist = CONTEXT_FIELDS if stage == "context" else ENTRY_FIELDS
    if field not in whitelist:
        raise MechanismFactoryError(f"{stage} field is not approved: {field}")
    has_value = "value" in raw
    has_other = "other" in raw
    if has_value == has_other:
        raise MechanismFactoryError("factory condition requires exactly one RHS form")
    result: dict[str, Any] = {"field": field, "op": op}
    if has_value:
        result["value"] = _number(raw["value"], "condition.value")
        if "scale" in raw:
            raise MechanismFactoryError("scalar condition cannot carry scale")
    else:
        other = raw["other"]
        if not isinstance(other, str) or other not in whitelist:
            raise MechanismFactoryError("factory condition other field is not approved")
        result["other"] = other
        result["scale"] = _number(raw.get("scale", 1.0), "condition.scale")
    return result


def load_factory_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise MechanismFactoryError("mechanism factory contract missing or unsafe")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MechanismFactoryError("mechanism factory root must be an object")
    if (
        raw.get("schema") != SCHEMA
        or raw.get("authority") != AUTHORITY
        or raw.get("selection_basis") != "training_partition_only"
        or raw.get("no_minimum_trade_count_gate") is not True
        or raw.get("auto_demo_promotion") is not False
        or raw.get("live_trading_authority") is not False
    ):
        raise MechanismFactoryError("mechanism factory authority contract invalid")
    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 32:
        raise MechanismFactoryError("mechanism factory candidate count invalid")

    out: dict[str, dict[str, Any]] = {}
    topology_seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            raise MechanismFactoryError("factory candidate must be an object")
        expected = {"id", "family", "hypothesis", "peer_required", "context", "entry"}
        if set(item) != expected:
            raise MechanismFactoryError("factory candidate schema mismatch")
        ident = item["id"]
        if not isinstance(ident, str) or not ID_RE.fullmatch(ident) or ident in out:
            raise MechanismFactoryError("factory candidate id invalid or duplicated")
        family = item["family"]
        hypothesis = item["hypothesis"]
        if (
            not isinstance(family, str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,72}", family)
            or not isinstance(hypothesis, str) or not 20 <= len(hypothesis) <= 500
            or not isinstance(item["peer_required"], bool)
        ):
            raise MechanismFactoryError("factory candidate metadata invalid")
        context_raw, entry_raw = item["context"], item["entry"]
        if not isinstance(context_raw, list) or not isinstance(entry_raw, list):
            raise MechanismFactoryError("factory candidate condition lists invalid")
        if not 2 <= len(context_raw) <= 8 or not 2 <= len(entry_raw) <= 8:
            raise MechanismFactoryError("factory candidate condition count out of bounds")
        context = [_validate_condition(x, stage="context") for x in context_raw]
        entry = [_validate_condition(x, stage="entry") for x in entry_raw]
        used = {c["field"] for c in context}
        used |= {c.get("other") for c in context if c.get("other")}
        peer_used = bool(used & PEER_FIELDS)
        if peer_used != item["peer_required"]:
            raise MechanismFactoryError("peer_required does not match candidate feature usage")
        topology = {"family": family, "peer_required": peer_used, "context": context, "entry": entry}
        topology_digest = _digest(topology)
        if topology_digest in topology_seen:
            raise MechanismFactoryError("duplicate factory topology")
        topology_seen.add(topology_digest)
        contract_core = {
            "id": ident,
            "family": family,
            "hypothesis": hypothesis,
            "peer_required": peer_used,
            "context": context,
            "entry": entry,
            "factory_schema": SCHEMA,
        }
        out[ident] = {
            **contract_core,
            "topology_digest": topology_digest,
            "contract_digest": _digest(contract_core),
        }
    return out


def factory_ids(specs: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(specs)


def factory_peer_ids(specs: Mapping[str, Mapping[str, Any]]) -> frozenset[str]:
    return frozenset(key for key, item in specs.items() if item["peer_required"] is True)


def factory_configs(specs: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple({
        "mechanism": ident,
        "risk_variant": 0,
        "entry_model": "closed_4h_1h_15m_next_open",
        "factory_contract_digest": specs[ident]["contract_digest"],
    } for ident in specs)


def _apply_condition(frame: pd.DataFrame, condition: Mapping[str, Any]) -> pd.Series:
    field = condition["field"]
    if field not in frame.columns:
        raise MechanismFactoryError(f"required factory feature missing: {field}")
    lhs = pd.to_numeric(frame[field], errors="coerce")
    if "other" in condition:
        other = condition["other"]
        if other not in frame.columns:
            raise MechanismFactoryError(f"required factory comparison feature missing: {other}")
        rhs = pd.to_numeric(frame[other], errors="coerce") * float(condition.get("scale", 1.0))
        finite = np.isfinite(lhs) & np.isfinite(rhs)
    else:
        rhs = float(condition["value"])
        finite = np.isfinite(lhs)
    op = condition["op"]
    if op == "eq":
        result = lhs == rhs
    elif op == "gt":
        result = lhs > rhs
    elif op == "ge":
        result = lhs >= rhs
    elif op == "lt":
        result = lhs < rhs
    elif op == "le":
        result = lhs <= rhs
    else:
        raise MechanismFactoryError("unreachable factory operator")
    return pd.Series(finite & result, index=frame.index).fillna(False)


def factory_signal(
    frame: pd.DataFrame,
    mechanism: str,
    *,
    specs: Mapping[str, Mapping[str, Any]],
    expected_contract_digest: str | None,
) -> np.ndarray:
    spec = specs.get(mechanism)
    if spec is None:
        raise MechanismFactoryError("unknown factory mechanism")
    if expected_contract_digest != spec["contract_digest"]:
        raise MechanismFactoryError("factory mechanism contract digest mismatch")
    mask = pd.Series(True, index=frame.index)
    for condition in (*spec["context"], *spec["entry"]):
        mask &= _apply_condition(frame, condition)
    return mask.fillna(False).to_numpy(dtype=bool)
