from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from phase5_data_binding import CanonicalDataError, validate_canonical_dataset
from phase5_strategy_factory import EXPERIMENT_SCHEMA, QUALIFICATION_SCHEMA


REGISTRY_SCHEMA = "nexus.phase7-strategy-registry.v1"
HEALTH_SCHEMA = "nexus.phase7-strategy-health.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEALTH_KEYS = {
    "data_eligible",
    "performance_drop_pct",
    "execution_cost_increase_pct",
    "regime_mismatch",
    "correlation_shift_pct",
}


class StrategyRegistryError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyRegistryError("registry value is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise StrategyRegistryError(f"{field} must be finite numeric")
    return float(value)


def _validate_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value.lower()):
        raise StrategyRegistryError(f"{field} must be a SHA-256 digest")
    return value.lower()


def _validate_experiment(experiment: Mapping[str, Any]) -> None:
    if not isinstance(experiment, Mapping) or experiment.get("schema_version") != EXPERIMENT_SCHEMA:
        raise StrategyRegistryError("experiment schema mismatch")
    claimed = experiment.get("experiment_id")
    core = dict(experiment)
    core.pop("experiment_id", None)
    if claimed != _digest(core):
        raise StrategyRegistryError("experiment identity mismatch")
    code_sha = experiment.get("code_sha")
    if not isinstance(code_sha, str) or not _SHA40.fullmatch(code_sha.lower()):
        raise StrategyRegistryError("experiment code_sha invalid")
    if experiment.get("paper_only") is not True:
        raise StrategyRegistryError("experiment exceeds Paper authority")


def _validate_qualification(qualification: Mapping[str, Any]) -> None:
    if not isinstance(qualification, Mapping) or qualification.get("schema_version") != QUALIFICATION_SCHEMA:
        raise StrategyRegistryError("qualification schema mismatch")
    claimed = qualification.get("qualification_digest")
    core = dict(qualification)
    core.pop("qualification_digest", None)
    if claimed != _digest(core):
        raise StrategyRegistryError("qualification identity mismatch")
    if qualification.get("paper_only") is not True or qualification.get("live_execution_allowed") is not False:
        raise StrategyRegistryError("qualification exceeds Paper authority")
    if qualification.get("deterministic_risk_final_authority") is not True:
        raise StrategyRegistryError("deterministic Risk authority is required")


def build_strategy_record(
    dataset: Mapping[str, Any],
    experiment: Mapping[str, Any],
    qualification: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one immutable registry record from already-produced deterministic evidence."""
    try:
        dataset = validate_canonical_dataset(dataset)
    except CanonicalDataError as exc:
        raise StrategyRegistryError(f"canonical dataset rejected: {exc}") from exc
    _validate_experiment(experiment)
    _validate_qualification(qualification)
    if experiment.get("dataset_binding_sha256") != dataset["binding_sha256"]:
        raise StrategyRegistryError("experiment data revision mismatch")
    for field in ("experiment_id", "code_sha", "strategy_version", "family"):
        if qualification.get(field) != experiment.get(field):
            raise StrategyRegistryError(f"qualification binding mismatch: {field}")
    if qualification.get("dataset_binding_sha256") != dataset["binding_sha256"]:
        raise StrategyRegistryError("qualification data revision mismatch")
    if not isinstance(evidence, Mapping):
        raise StrategyRegistryError("qualification evidence must be a mapping")
    if _digest(dict(evidence)) != qualification.get("evidence_digest"):
        raise StrategyRegistryError("qualification evidence digest mismatch")

    row_count = int(dataset["row_count"])
    oos_start = max(1, int(row_count * 0.70))
    status = qualification.get("status")
    if status == "paper_candidate":
        lifecycle_state = "CANDIDATE"
    elif status == "killed":
        lifecycle_state = "REJECTED"
    else:
        raise StrategyRegistryError("unsupported qualification status")

    cost_model = dict(experiment["cost_model"])
    funding = cost_model.get("funding_bps")
    funding_model = (
        {"status": "MODELED", "funding_bps": funding}
        if funding is not None
        else {"status": "NOT_APPLICABLE", "reason_code": "CANONICAL_SPOT_DATASET"}
    )
    metrics = {
        key: evidence[key]
        for key in (
            "robustness_score",
            "cost_stress_loss_pct",
            "walk_forward_score",
            "oos_score",
            "max_drawdown_pct",
            "regime_pass_ratio",
            "benchmark_score",
            "uncertainty_width",
        )
        if key in evidence
    }
    core = {
        "schema_version": REGISTRY_SCHEMA,
        "strategy_id": _digest({"family": experiment["family"], "hypothesis": experiment["hypothesis"]}),
        "strategy_version": experiment["strategy_version"],
        "family": experiment["family"],
        "hypothesis": experiment["hypothesis"],
        "config_sha256": _digest(dict(experiment["config"])),
        "config": dict(experiment["config"]),
        "dataset_binding_sha256": dataset["binding_sha256"],
        "provenance_manifest_sha256": dataset["manifest_sha256"],
        "code_sha": experiment["code_sha"],
        "is_window": {"start_index": 0, "end_index_exclusive": oos_start},
        "oos_window": {"start_index": oos_start, "end_index_exclusive": row_count},
        "cost_model": cost_model,
        "funding_model": funding_model,
        "regime_evaluation": {
            "method": "ordered_non_overlapping_thirds",
            "pass_ratio": evidence.get("regime_pass_ratio"),
        },
        "metrics": metrics,
        "kill_criteria": dict(experiment["kill_criteria"]),
        "experiment_id": experiment["experiment_id"],
        "qualification_digest": qualification["qualification_digest"],
        "evidence_digest": qualification["evidence_digest"],
        "lifecycle_state": lifecycle_state,
        "kill_reasons": list(qualification.get("kill_reasons", [])),
        "paper_only": True,
        "live_execution_allowed": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "record_digest": _digest(core)}


def evaluate_strategy_health(record: Mapping[str, Any], signals: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministically classify strategy health without granting promotion authority."""
    if not isinstance(record, Mapping) or record.get("schema_version") != REGISTRY_SCHEMA:
        raise StrategyRegistryError("registry record schema mismatch")
    claimed = record.get("record_digest")
    core = dict(record)
    core.pop("record_digest", None)
    if claimed != _digest(core):
        raise StrategyRegistryError("registry record digest mismatch")
    if not isinstance(signals, Mapping) or set(signals) != HEALTH_KEYS:
        raise StrategyRegistryError("health signal schema mismatch")
    if not isinstance(signals["data_eligible"], bool) or not isinstance(signals["regime_mismatch"], bool):
        raise StrategyRegistryError("health boolean signals invalid")
    performance = _finite(signals["performance_drop_pct"], "performance_drop_pct")
    costs = _finite(signals["execution_cost_increase_pct"], "execution_cost_increase_pct")
    correlation = _finite(signals["correlation_shift_pct"], "correlation_shift_pct")
    if min(performance, costs, correlation) < 0:
        raise StrategyRegistryError("health drift percentages must be non-negative")

    reasons: list[str] = []
    if not signals["data_eligible"]:
        health = "QUARANTINED"
        reasons.append("DATA_INELIGIBLE")
    elif performance >= 50 or costs >= 100 or correlation >= 50:
        health = "QUARANTINED"
        reasons.append("SEVERE_DRIFT")
    elif performance >= 30 or costs >= 50 or correlation >= 30:
        health = "DEGRADED"
        reasons.append("MATERIAL_DRIFT")
    elif signals["regime_mismatch"] or performance >= 15 or costs >= 25 or correlation >= 15:
        health = "WATCH"
        reasons.append("WATCH_THRESHOLD")
        if signals["regime_mismatch"]:
            reasons.append("REGIME_MISMATCH")
    else:
        health = "HEALTHY"
        reasons.append("WITHIN_BOUNDS")

    result = {
        "schema_version": HEALTH_SCHEMA,
        "strategy_id": record["strategy_id"],
        "strategy_version": record["strategy_version"],
        "record_digest": _validate_digest(record["record_digest"], "record_digest"),
        "health_state": health,
        "reason_codes": reasons,
        "signals": dict(signals),
        "paper_only": True,
        "promotion_authority": False,
        "deterministic_risk_final_authority": True,
    }
    return {**result, "health_digest": _digest(result)}
