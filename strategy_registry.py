from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from phase5_data_binding import CanonicalDataError, validate_canonical_dataset
from phase5_strategy_factory import EXPERIMENT_SCHEMA, QUALIFICATION_SCHEMA
from nexus_strategy_qualification_gate import verify_qualification
from nexus_composite_strategy_qualification_gate import verify_composite_qualification


REGISTRY_SCHEMA = "nexus.phase7-strategy-registry.v1"
MODERN_REGISTRY_SCHEMA = "nexus.strategy-registry-record.v2"
MODERN_REGISTRY_VERIFY_SCHEMA = "nexus.strategy-registry-record-verification.v2"
COMPOSITE_REGISTRY_SCHEMA = "nexus.composite-strategy-registry-record.v1"
COMPOSITE_REGISTRY_VERIFY_SCHEMA = "nexus.composite-strategy-registry-record-verification.v1"
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


def build_qualified_strategy_record(
    qualification: Mapping[str, Any],
    qualification_verification: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a REG-50 immutable record from one exact successful QUAL-42 artifact.

    Registration does not activate the strategy.  Demo matrix membership and
    Runtime/Paper authority remain false until a later reviewed activation path.
    """
    if not isinstance(qualification, Mapping) or not isinstance(qualification_verification, Mapping):
        raise StrategyRegistryError("modern registry admission requires qualification and verification")
    computed = verify_qualification(qualification)
    if computed.get("decision") != "pass" or dict(qualification_verification) != computed:
        raise StrategyRegistryError("QUAL-42 verification is missing, stale, or rejected")
    if (
        qualification.get("decision") != "QUALIFIED_FOR_REGISTRY"
        or qualification.get("qualified") is not True
        or qualification.get("registry_admission_allowed") is not True
        or qualification.get("registry_mutation_performed") is not False
        or qualification.get("runtime_activation_authority") is not False
        or qualification.get("paper_execution_authority") is not False
        or qualification.get("automatic_strategy_promotion") is not False
        or qualification.get("live_trading_authority") is not False
        or qualification.get("paper_only") is not True
    ):
        raise StrategyRegistryError("QUAL-42 does not authorize registry admission")

    config = qualification.get("strategy_config")
    runtime_evidence = qualification.get("runtime_evidence")
    if not isinstance(config, Mapping) or not config:
        raise StrategyRegistryError("QUAL-42 strategy config is unavailable")
    if qualification.get("strategy_config_digest") != _digest(dict(config)):
        raise StrategyRegistryError("QUAL-42 strategy config digest mismatch")
    if not isinstance(runtime_evidence, list) or not runtime_evidence:
        raise StrategyRegistryError("QUAL-42 runtime evidence is unavailable")
    if qualification.get("runtime_evidence_digest") != _digest(runtime_evidence):
        raise StrategyRegistryError("QUAL-42 runtime evidence digest mismatch")

    family = qualification.get("family")
    timeframe = qualification.get("timeframe")
    variant_id = qualification.get("variant_id")
    if (
        not isinstance(family, str) or not family or len(family) > 80
        or not isinstance(timeframe, str) or not timeframe or len(timeframe) > 80
        or not isinstance(variant_id, str) or not variant_id or len(variant_id) > 160
    ):
        raise StrategyRegistryError("QUAL-42 strategy identity fields are invalid")
    strategy_id = _digest({
        "family": family,
        "timeframe": timeframe,
        "strategy_config_digest": qualification["strategy_config_digest"],
    })
    strategy_version = _digest({
        "strategy_id": strategy_id,
        "qualification_digest": qualification["qualification_digest"],
    })
    core = {
        "schema_version": MODERN_REGISTRY_SCHEMA,
        "system_map_node": "REG-50",
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "family": family,
        "timeframe": timeframe,
        "variant_id": variant_id,
        "config": dict(config),
        "config_sha256": qualification["strategy_config_digest"],
        "source_sha": qualification["source_sha"],
        "proposal_digest": qualification["proposal_digest"],
        "proposal_result_digest": qualification["proposal_result_digest"],
        "requalification_digest": qualification["requalification_digest"],
        "requalification_verification_digest": qualification["requalification_verification_digest"],
        "qa_task_digest": qualification["qa_task_digest"],
        "qa_receipt_digest": qualification["qa_receipt_digest"],
        "qualification_digest": qualification["qualification_digest"],
        "qualification_verification_digest": qualification_verification["verification_digest"],
        "qualification_artifact": dict(qualification),
        "qualification_verification": dict(qualification_verification),
        "runtime_evidence": [dict(row) for row in runtime_evidence],
        "runtime_evidence_digest": qualification["runtime_evidence_digest"],
        "lifecycle_state": "QUALIFIED_CANDIDATE",
        "demo_matrix_member": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "paper_only": True,
        "live_execution_allowed": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "record_digest": _digest(core)}


def verify_qualified_strategy_record(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "identity": False,
        "provenance": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("record_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == MODERN_REGISTRY_SCHEMA
            and core.get("system_map_node") == "REG-50"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        expected_id = _digest({
            "family": core.get("family"),
            "timeframe": core.get("timeframe"),
            "strategy_config_digest": core.get("config_sha256"),
        })
        expected_version = _digest({
            "strategy_id": expected_id,
            "qualification_digest": core.get("qualification_digest"),
        })
        checks["identity"] = bool(
            core.get("strategy_id") == expected_id
            and core.get("strategy_version") == expected_version
            and isinstance(core.get("family"), str)
            and bool(core.get("family"))
            and len(core.get("family")) <= 80
            and isinstance(core.get("timeframe"), str)
            and bool(core.get("timeframe"))
            and len(core.get("timeframe")) <= 80
            and isinstance(core.get("variant_id"), str)
            and bool(core.get("variant_id"))
            and len(core.get("variant_id")) <= 160
            and isinstance(core.get("config"), Mapping)
            and bool(core.get("config"))
            and core.get("config_sha256") == _digest(dict(core.get("config")))
        )
        runtime_evidence = core.get("runtime_evidence")
        runtime_rows_valid = bool(
            isinstance(runtime_evidence, list)
            and 1 <= len(runtime_evidence) <= 16
            and len({
                row.get("symbol")
                for row in runtime_evidence
                if isinstance(row, Mapping) and isinstance(row.get("symbol"), str)
            }) == len(runtime_evidence)
            and all(
                isinstance(row, Mapping)
                and isinstance(row.get("symbol"), str)
                and bool(row.get("symbol"))
                and len(row.get("symbol")) <= 40
                and _HEX64.fullmatch(str(row.get("dataset_binding_sha256", "")))
                and _HEX64.fullmatch(str(row.get("pipeline_digest", "")))
                and _HEX64.fullmatch(str(row.get("qualification_digest", "")))
                and type(row.get("last_open_time_ms")) is int
                and row.get("last_open_time_ms") > 0
                for row in runtime_evidence
            )
        )
        embedded_qualification = core.get("qualification_artifact")
        embedded_verification = core.get("qualification_verification")
        computed_verification = (
            verify_qualification(embedded_qualification)
            if isinstance(embedded_qualification, Mapping)
            else None
        )
        qualification_bound = bool(
            isinstance(embedded_qualification, Mapping)
            and isinstance(embedded_verification, Mapping)
            and isinstance(computed_verification, Mapping)
            and computed_verification.get("decision") == "pass"
            and dict(embedded_verification) == dict(computed_verification)
            and embedded_qualification.get("decision") == "QUALIFIED_FOR_REGISTRY"
            and embedded_qualification.get("qualified") is True
            and embedded_qualification.get("registry_admission_allowed") is True
            and embedded_qualification.get("qualification_digest") == core.get("qualification_digest")
            and embedded_verification.get("verification_digest")
                == core.get("qualification_verification_digest")
            and embedded_qualification.get("source_sha") == core.get("source_sha")
            and embedded_qualification.get("proposal_digest") == core.get("proposal_digest")
            and embedded_qualification.get("proposal_result_digest") == core.get("proposal_result_digest")
            and embedded_qualification.get("requalification_digest") == core.get("requalification_digest")
            and embedded_qualification.get("requalification_verification_digest")
                == core.get("requalification_verification_digest")
            and embedded_qualification.get("qa_task_digest") == core.get("qa_task_digest")
            and embedded_qualification.get("qa_receipt_digest") == core.get("qa_receipt_digest")
            and embedded_qualification.get("family") == core.get("family")
            and embedded_qualification.get("timeframe") == core.get("timeframe")
            and embedded_qualification.get("variant_id") == core.get("variant_id")
            and embedded_qualification.get("strategy_config") == core.get("config")
            and embedded_qualification.get("strategy_config_digest") == core.get("config_sha256")
            and embedded_qualification.get("runtime_evidence") == runtime_evidence
            and embedded_qualification.get("runtime_evidence_digest")
                == core.get("runtime_evidence_digest")
        )
        checks["provenance"] = bool(
            _SHA40.fullmatch(str(core.get("source_sha", "")))
            and _HEX64.fullmatch(str(core.get("proposal_digest", "")))
            and _HEX64.fullmatch(str(core.get("proposal_result_digest", "")))
            and _HEX64.fullmatch(str(core.get("requalification_digest", "")))
            and _HEX64.fullmatch(str(core.get("requalification_verification_digest", "")))
            and _HEX64.fullmatch(str(core.get("qa_task_digest", "")))
            and _HEX64.fullmatch(str(core.get("qa_receipt_digest", "")))
            and _HEX64.fullmatch(str(core.get("qualification_digest", "")))
            and _HEX64.fullmatch(str(core.get("qualification_verification_digest", "")))
            and runtime_rows_valid
            and core.get("runtime_evidence_digest") == _digest(runtime_evidence)
            and qualification_bound
        )
        checks["authority"] = bool(
            core.get("lifecycle_state") == "QUALIFIED_CANDIDATE"
            and core.get("demo_matrix_member") is False
            and core.get("runtime_activation_authority") is False
            and core.get("paper_execution_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("paper_only") is True
            and core.get("live_execution_allowed") is False
            and core.get("deterministic_risk_final_authority") is True
        )
    except Exception:
        pass
    decision = "pass" if all(checks.values()) else "reject"
    result = {
        "schema_version": MODERN_REGISTRY_VERIFY_SCHEMA,
        "decision": decision,
        "checks": checks,
        "record_digest": value.get("record_digest"),
    }
    return {**result, "verification_digest": _digest(result)}



def build_composite_qualified_strategy_record(
    qualification: Mapping[str, Any],
    qualification_verification: Mapping[str, Any],
) -> dict[str, Any]:
    """Build one immutable REG-50 record from exact composite QUAL-42 proof.

    This is a typed record in the existing Strategy Registry.  It does not
    create Demo membership or Runtime/Paper authority.
    """
    if (
        not isinstance(qualification, Mapping)
        or not isinstance(qualification_verification, Mapping)
    ):
        raise StrategyRegistryError(
            "composite registry admission requires qualification and verification"
        )
    computed = verify_composite_qualification(qualification)
    if (
        computed.get("decision") != "pass"
        or dict(qualification_verification) != computed
    ):
        raise StrategyRegistryError(
            "composite QUAL-42 verification is missing, stale, or rejected"
        )
    if (
        qualification.get("decision") != "QUALIFIED_FOR_REGISTRY"
        or qualification.get("qualified") is not True
        or qualification.get("registry_admission_allowed") is not True
        or qualification.get("registry_mutation_performed") is not False
        or qualification.get("runtime_activation_authority") is not False
        or qualification.get("paper_execution_authority") is not False
        or qualification.get("automatic_strategy_promotion") is not False
        or qualification.get("live_trading_authority") is not False
        or qualification.get("paper_only") is not True
    ):
        raise StrategyRegistryError(
            "composite QUAL-42 does not authorize registry admission"
        )

    config = qualification.get("strategy_config")
    runtime_evidence = qualification.get("runtime_evidence")
    mechanism = qualification.get("mechanism")
    timeframe = qualification.get("timeframe")
    config_fingerprint = qualification.get("config_fingerprint")
    if not isinstance(config, Mapping) or not config:
        raise StrategyRegistryError("composite QUAL-42 strategy config is unavailable")
    if qualification.get("strategy_config_digest") != _digest(dict(config)):
        raise StrategyRegistryError("composite QUAL-42 config digest mismatch")
    if (
        not isinstance(runtime_evidence, list)
        or not runtime_evidence
        or qualification.get("runtime_evidence_digest") != _digest(runtime_evidence)
    ):
        raise StrategyRegistryError(
            "composite QUAL-42 runtime evidence binding is invalid"
        )
    if (
        not isinstance(mechanism, str)
        or not mechanism
        or len(mechanism) > 120
        or not isinstance(timeframe, str)
        or not timeframe
        or len(timeframe) > 120
        or not _HEX64.fullmatch(str(config_fingerprint or ""))
    ):
        raise StrategyRegistryError(
            "composite QUAL-42 strategy identity fields are invalid"
        )

    strategy_id = _digest({
        "origin_kind": "composite_mechanism",
        "mechanism": mechanism,
        "timeframe": timeframe,
        "strategy_config_digest": qualification["strategy_config_digest"],
    })
    strategy_version = _digest({
        "strategy_id": strategy_id,
        "qualification_digest": qualification["qualification_digest"],
    })
    core = {
        "schema_version": COMPOSITE_REGISTRY_SCHEMA,
        "system_map_node": "REG-50",
        "origin_kind": "composite_mechanism",
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "family": "composite_mechanism",
        "mechanism": mechanism,
        "timeframe": timeframe,
        "variant_id": config_fingerprint,
        "config": dict(config),
        "config_sha256": qualification["strategy_config_digest"],
        "config_fingerprint": config_fingerprint,
        "source_sha": qualification["source_sha"],
        "producer_workflow_run_id": qualification["producer_workflow_run_id"],
        "candidate_digest": qualification["candidate_digest"],
        "requalification_digest": qualification["requalification_digest"],
        "requalification_verification_digest":
            qualification["requalification_verification_digest"],
        "qa_task_digest": qualification["qa_task_digest"],
        "qa_receipt_digest": qualification["qa_receipt_digest"],
        "qualification_digest": qualification["qualification_digest"],
        "qualification_verification_digest":
            qualification_verification["verification_digest"],
        "qualification_artifact": dict(qualification),
        "qualification_verification": dict(qualification_verification),
        "runtime_as_of_ms": qualification["runtime_as_of_ms"],
        "runtime_evidence": [dict(row) for row in runtime_evidence],
        "runtime_evidence_digest": qualification["runtime_evidence_digest"],
        "lifecycle_state": "QUALIFIED_CANDIDATE",
        "demo_matrix_member": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "paper_only": True,
        "live_execution_allowed": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "record_digest": _digest(core)}


def verify_composite_qualified_strategy_record(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "identity": False,
        "provenance": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("record_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == COMPOSITE_REGISTRY_SCHEMA
            and core.get("system_map_node") == "REG-50"
            and core.get("origin_kind") == "composite_mechanism"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)

        config = core.get("config")
        mechanism = core.get("mechanism")
        timeframe = core.get("timeframe")
        config_digest = core.get("config_sha256")
        expected_id = _digest({
            "origin_kind": "composite_mechanism",
            "mechanism": mechanism,
            "timeframe": timeframe,
            "strategy_config_digest": config_digest,
        })
        expected_version = _digest({
            "strategy_id": expected_id,
            "qualification_digest": core.get("qualification_digest"),
        })
        checks["identity"] = bool(
            core.get("family") == "composite_mechanism"
            and isinstance(mechanism, str)
            and bool(mechanism)
            and len(mechanism) <= 120
            and isinstance(timeframe, str)
            and bool(timeframe)
            and len(timeframe) <= 120
            and isinstance(config, Mapping)
            and bool(config)
            and config_digest == _digest(dict(config))
            and _HEX64.fullmatch(str(core.get("config_fingerprint", "")))
            and core.get("variant_id") == core.get("config_fingerprint")
            and core.get("strategy_id") == expected_id
            and core.get("strategy_version") == expected_version
        )

        embedded_qualification = core.get("qualification_artifact")
        embedded_verification = core.get("qualification_verification")
        computed_qualification = (
            verify_composite_qualification(embedded_qualification)
            if isinstance(embedded_qualification, Mapping)
            else None
        )
        runtime_evidence = core.get("runtime_evidence")
        qualification_bound = bool(
            isinstance(embedded_qualification, Mapping)
            and isinstance(embedded_verification, Mapping)
            and isinstance(computed_qualification, Mapping)
            and computed_qualification.get("decision") == "pass"
            and dict(embedded_verification) == dict(computed_qualification)
            and embedded_qualification.get("decision") == "QUALIFIED_FOR_REGISTRY"
            and embedded_qualification.get("qualified") is True
            and embedded_qualification.get("registry_admission_allowed") is True
            and embedded_qualification.get("source_sha") == core.get("source_sha")
            and embedded_qualification.get("producer_workflow_run_id")
                == core.get("producer_workflow_run_id")
            and embedded_qualification.get("candidate_digest")
                == core.get("candidate_digest")
            and embedded_qualification.get("requalification_digest")
                == core.get("requalification_digest")
            and embedded_qualification.get("requalification_verification_digest")
                == core.get("requalification_verification_digest")
            and embedded_qualification.get("qa_task_digest")
                == core.get("qa_task_digest")
            and embedded_qualification.get("qa_receipt_digest")
                == core.get("qa_receipt_digest")
            and embedded_qualification.get("qualification_digest")
                == core.get("qualification_digest")
            and embedded_verification.get("verification_digest")
                == core.get("qualification_verification_digest")
            and embedded_qualification.get("mechanism") == mechanism
            and embedded_qualification.get("timeframe") == timeframe
            and embedded_qualification.get("strategy_config") == config
            and embedded_qualification.get("strategy_config_digest") == config_digest
            and embedded_qualification.get("config_fingerprint")
                == core.get("config_fingerprint")
            and embedded_qualification.get("runtime_as_of_ms")
                == core.get("runtime_as_of_ms")
            and embedded_qualification.get("runtime_evidence") == runtime_evidence
            and embedded_qualification.get("runtime_evidence_digest")
                == core.get("runtime_evidence_digest")
        )
        checks["provenance"] = bool(
            _SHA40.fullmatch(str(core.get("source_sha", "")))
            and isinstance(core.get("producer_workflow_run_id"), int)
            and not isinstance(core.get("producer_workflow_run_id"), bool)
            and core.get("producer_workflow_run_id") > 0
            and all(
                _HEX64.fullmatch(str(core.get(field, "")))
                for field in (
                    "candidate_digest",
                    "requalification_digest",
                    "requalification_verification_digest",
                    "qa_task_digest",
                    "qa_receipt_digest",
                    "qualification_digest",
                    "qualification_verification_digest",
                    "runtime_evidence_digest",
                )
            )
            and isinstance(runtime_evidence, list)
            and bool(runtime_evidence)
            and core.get("runtime_evidence_digest") == _digest(runtime_evidence)
            and qualification_bound
        )
        checks["authority"] = bool(
            core.get("lifecycle_state") == "QUALIFIED_CANDIDATE"
            and core.get("demo_matrix_member") is False
            and core.get("runtime_activation_authority") is False
            and core.get("paper_execution_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("paper_only") is True
            and core.get("live_execution_allowed") is False
            and core.get("deterministic_risk_final_authority") is True
        )
    except Exception:
        pass

    decision = "pass" if all(checks.values()) else "reject"
    result = {
        "schema_version": COMPOSITE_REGISTRY_VERIFY_SCHEMA,
        "decision": decision,
        "checks": checks,
        "record_digest": value.get("record_digest"),
    }
    return {**result, "verification_digest": _digest(result)}
