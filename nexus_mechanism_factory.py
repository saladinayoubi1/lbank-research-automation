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
SYNTH_SCHEMA = "nexus.mechanism-synthesizer.v1"
AUTHORITY = "research-only-no-auto-promotion"
ROOT = Path(__file__).resolve().parent
DEFAULT_CONTRACT = ROOT / "research" / "mechanism_factory_v1.json"
DEFAULT_SYNTH_CONTRACT = ROOT / "research" / "mechanism_synthesizer_v1.json"
ID_RE = re.compile(r"^(?:factory|synth)_[a-z][a-z0-9_]{2,72}$")
PACK_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,48}$")

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


def _normalize_candidates(
    candidates: Any,
    *,
    topology_seen: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= 64:
        raise MechanismFactoryError("mechanism factory candidate count invalid")
    out: dict[str, dict[str, Any]] = {}
    seen = set() if topology_seen is None else set(topology_seen)
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
            not isinstance(family, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{2,72}", family)
            or not isinstance(hypothesis, str)
            or not 20 <= len(hypothesis) <= 500
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
        if topology_digest in seen:
            raise MechanismFactoryError("duplicate factory topology")
        seen.add(topology_digest)
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


def _validate_authority(raw: Mapping[str, Any], *, schema: str) -> None:
    if (
        raw.get("schema") != schema
        or raw.get("authority") != AUTHORITY
        or raw.get("selection_basis") != "training_partition_only"
        or raw.get("no_minimum_trade_count_gate") is not True
        or raw.get("auto_demo_promotion") is not False
        or raw.get("live_trading_authority") is not False
    ):
        raise MechanismFactoryError("mechanism factory authority contract invalid")


def load_factory_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise MechanismFactoryError("mechanism factory contract missing or unsafe")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MechanismFactoryError("mechanism factory root must be an object")
    _validate_authority(raw, schema=SCHEMA)
    return _normalize_candidates(raw.get("candidates"))


def synthesize_factory_contracts(
    path: Path = DEFAULT_SYNTH_CONTRACT,
    *,
    existing: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise MechanismFactoryError("mechanism synthesizer contract missing or unsafe")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise MechanismFactoryError("mechanism synthesizer root must be an object")
    _validate_authority(raw, schema=SYNTH_SCHEMA)
    contexts = raw.get("contexts")
    entries = raw.get("entries")
    if not isinstance(contexts, list) or not 1 <= len(contexts) <= 16:
        raise MechanismFactoryError("mechanism synthesizer contexts invalid")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 12:
        raise MechanismFactoryError("mechanism synthesizer entries invalid")

    entry_map: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"id", "family", "description", "conditions"}:
            raise MechanismFactoryError("mechanism synthesizer entry schema invalid")
        ident = entry["id"]
        if not isinstance(ident, str) or not PACK_ID_RE.fullmatch(ident) or ident in entry_map:
            raise MechanismFactoryError("mechanism synthesizer entry id invalid or duplicated")
        if (
            not isinstance(entry["family"], str)
            or not PACK_ID_RE.fullmatch(entry["family"])
            or not isinstance(entry["description"], str)
            or not 12 <= len(entry["description"]) <= 300
            or not isinstance(entry["conditions"], list)
        ):
            raise MechanismFactoryError("mechanism synthesizer entry metadata invalid")
        normalized = [_validate_condition(x, stage="entry") for x in entry["conditions"]]
        if not 2 <= len(normalized) <= 8:
            raise MechanismFactoryError("mechanism synthesizer entry condition count invalid")
        entry_map[ident] = {**entry, "conditions": normalized}

    candidates: list[dict[str, Any]] = []
    context_ids: set[str] = set()
    for context in contexts:
        expected = {
            "id", "family", "peer_required", "description",
            "conditions", "compatible_entries",
        }
        if not isinstance(context, dict) or set(context) != expected:
            raise MechanismFactoryError("mechanism synthesizer context schema invalid")
        ident = context["id"]
        if not isinstance(ident, str) or not PACK_ID_RE.fullmatch(ident) or ident in context_ids:
            raise MechanismFactoryError("mechanism synthesizer context id invalid or duplicated")
        context_ids.add(ident)
        if (
            not isinstance(context["family"], str)
            or not PACK_ID_RE.fullmatch(context["family"])
            or not isinstance(context["peer_required"], bool)
            or not isinstance(context["description"], str)
            or not 12 <= len(context["description"]) <= 300
            or not isinstance(context["conditions"], list)
            or not isinstance(context["compatible_entries"], list)
        ):
            raise MechanismFactoryError("mechanism synthesizer context metadata invalid")
        normalized_context = [
            _validate_condition(x, stage="context") for x in context["conditions"]
        ]
        if not 2 <= len(normalized_context) <= 8:
            raise MechanismFactoryError("mechanism synthesizer context condition count invalid")
        used = {c["field"] for c in normalized_context}
        used |= {c.get("other") for c in normalized_context if c.get("other")}
        if bool(used & PEER_FIELDS) != context["peer_required"]:
            raise MechanismFactoryError("synthesizer peer_required mismatch")
        compatible = context["compatible_entries"]
        if (
            not compatible
            or len(compatible) != len(set(compatible))
            or any(item not in entry_map for item in compatible)
        ):
            raise MechanismFactoryError("mechanism synthesizer compatibility invalid")
        for entry_id in compatible:
            entry = entry_map[entry_id]
            candidate_id = f"synth_{ident}_{entry_id}"
            if len(candidate_id) > 79:
                candidate_id = f"synth_{_digest([ident, entry_id])[:24]}"
            candidates.append({
                "id": candidate_id,
                "family": f"{context['family']}_{entry['family']}"[:72],
                "hypothesis": (
                    f"{context['description'].capitalize()} may persist only when "
                    f"{entry['description']}."
                ),
                "peer_required": context["peer_required"],
                "context": normalized_context,
                "entry": entry["conditions"],
            })

    if not 1 <= len(candidates) <= 64:
        raise MechanismFactoryError("synthesized candidate count invalid")
    existing_specs = dict(existing or {})
    topology_seen = {
        str(item.get("topology_digest"))
        for item in existing_specs.values()
        if item.get("topology_digest")
    }
    synthesized = _normalize_candidates(candidates, topology_seen=topology_seen)
    if set(synthesized) & set(existing_specs):
        raise MechanismFactoryError("synthesized candidate id collides with existing factory")
    return synthesized


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
