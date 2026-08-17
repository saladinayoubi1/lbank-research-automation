from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from phase5_data_binding import CanonicalDataError, validate_canonical_dataset

EXPERIMENT_SCHEMA = "nexus.phase5-strategy-experiment.v1"
QUALIFICATION_SCHEMA = "nexus.phase5-strategy-qualification.v1"
ALLOWED_FAMILIES = {"trend_breakout", "momentum", "mean_reversion"}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class StrategyFactoryError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyFactoryError("strategy evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _bounded_text(value: Any, field: str, *, limit: int = 240) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise StrategyFactoryError(f"{field} must be a non-empty bounded string")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise StrategyFactoryError(f"{field} must be finite numeric evidence")
    return float(value)


def _validate_sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value.lower()):
        raise StrategyFactoryError("code_sha must be a 40-character Git SHA")
    return value.lower()


def build_experiment(
    dataset: Mapping[str, Any],
    *,
    hypothesis: str,
    family: str,
    strategy_version: str,
    config: Mapping[str, Any],
    code_sha: str,
    cost_model: Mapping[str, Any],
    kill_criteria: Mapping[str, Any],
) -> dict[str, Any]:
    """Preregister one immutable research experiment before evaluation."""
    try:
        canonical_dataset = validate_canonical_dataset(dataset)
    except CanonicalDataError as exc:
        raise StrategyFactoryError(f"Gate 7 dataset rejected: {exc}") from exc
    hypothesis = _bounded_text(hypothesis, "hypothesis", limit=1000)
    family = _bounded_text(family, "family", limit=64)
    if family not in ALLOWED_FAMILIES:
        raise StrategyFactoryError("strategy family is not approved")
    strategy_version = _bounded_text(strategy_version, "strategy_version", limit=80)
    code_sha = _validate_sha(code_sha)
    if not isinstance(config, Mapping) or not config:
        raise StrategyFactoryError("strategy config must be a non-empty mapping")
    if not isinstance(cost_model, Mapping) or not cost_model:
        raise StrategyFactoryError("cost model must be a non-empty mapping")
    if not isinstance(kill_criteria, Mapping):
        raise StrategyFactoryError("kill criteria must be a mapping")
    expected_kills = {
        "min_robustness_score", "max_cost_stress_loss_pct", "min_walk_forward_score",
        "min_oos_score", "max_drawdown_pct", "min_regime_pass_ratio", "max_failure_mode_severity",
    }
    if set(kill_criteria) != expected_kills:
        raise StrategyFactoryError("kill criteria schema mismatch")
    normalized_kills = {key: _finite(kill_criteria[key], f"kill_criteria.{key}") for key in sorted(expected_kills)}
    core = {
        "schema_version": EXPERIMENT_SCHEMA,
        "paper_only": True,
        "dataset_binding_sha256": canonical_dataset["binding_sha256"],
        "instrument": canonical_dataset["instrument"],
        "market": canonical_dataset["market"],
        "timeframe": canonical_dataset["manifest_timeframe"],
        "hypothesis": hypothesis,
        "family": family,
        "strategy_version": strategy_version,
        "config": dict(config),
        "code_sha": code_sha,
        "cost_model": dict(cost_model),
        "kill_criteria": normalized_kills,
    }
    _canonical_json(core)
    return {**core, "experiment_id": _digest(core)}


def qualify(
    dataset: Mapping[str, Any],
    experiment: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the frozen Gate-6 promotion path and return Paper Candidate or kill.

    This function intentionally consumes a Gate-7 artifact, never raw market
    rows. An ad-hoc backtest result cannot bypass preregistration or the staged
    controls below.
    """
    dataset = validate_canonical_dataset(dataset)
    if not isinstance(experiment, Mapping) or experiment.get("schema_version") != EXPERIMENT_SCHEMA:
        raise StrategyFactoryError("experiment schema mismatch")
    expected_experiment = dict(experiment)
    claimed_experiment_id = expected_experiment.pop("experiment_id", None)
    if claimed_experiment_id != _digest(expected_experiment):
        raise StrategyFactoryError("experiment identity mismatch")
    if experiment.get("dataset_binding_sha256") != dataset["binding_sha256"]:
        raise StrategyFactoryError("experiment is bound to a different data revision")
    if experiment.get("paper_only") is not True:
        raise StrategyFactoryError("experiment widened authority beyond paper scope")

    required_evidence = {
        "evidence_refs", "hypothesis_supported", "preregistered", "robustness_score",
        "cost_stress_loss_pct", "walk_forward_score", "oos_score", "max_drawdown_pct",
        "regime_pass_ratio", "failure_mode_severity", "benchmark_score", "uncertainty_width",
        "survivorship_control", "lookahead_control", "data_snooping_control",
    }
    if not isinstance(evidence, Mapping) or set(evidence) != required_evidence:
        raise StrategyFactoryError("qualification evidence schema mismatch")
    refs = evidence["evidence_refs"]
    if not isinstance(refs, list) or not refs or len(refs) > 32 or any(not isinstance(ref, str) or not ref for ref in refs):
        raise StrategyFactoryError("evidence_refs must be a non-empty bounded list")
    for control in ("hypothesis_supported", "preregistered", "survivorship_control", "lookahead_control", "data_snooping_control"):
        if not isinstance(evidence[control], bool):
            raise StrategyFactoryError(f"{control} must be boolean")

    numeric = {key: _finite(evidence[key], key) for key in (
        "robustness_score", "cost_stress_loss_pct", "walk_forward_score", "oos_score",
        "max_drawdown_pct", "regime_pass_ratio", "failure_mode_severity", "benchmark_score",
        "uncertainty_width",
    )}
    kills = experiment["kill_criteria"]
    reasons: list[str] = []
    if not evidence["hypothesis_supported"]:
        reasons.append("HYPOTHESIS_UNSUPPORTED")
    if not evidence["preregistered"]:
        reasons.append("NOT_PREREGISTERED")
    if not evidence["survivorship_control"]:
        reasons.append("SURVIVORSHIP_CONTROL_FAILED")
    if not evidence["lookahead_control"]:
        reasons.append("LOOKAHEAD_CONTROL_FAILED")
    if not evidence["data_snooping_control"]:
        reasons.append("DATA_SNOOPING_CONTROL_FAILED")
    if numeric["robustness_score"] < kills["min_robustness_score"]:
        reasons.append("ROBUSTNESS_KILL")
    if numeric["cost_stress_loss_pct"] > kills["max_cost_stress_loss_pct"]:
        reasons.append("COST_STRESS_KILL")
    if numeric["walk_forward_score"] < kills["min_walk_forward_score"]:
        reasons.append("WALK_FORWARD_KILL")
    if numeric["oos_score"] < kills["min_oos_score"]:
        reasons.append("OOS_KILL")
    if numeric["max_drawdown_pct"] > kills["max_drawdown_pct"]:
        reasons.append("DRAWDOWN_KILL")
    if numeric["regime_pass_ratio"] < kills["min_regime_pass_ratio"]:
        reasons.append("REGIME_KILL")
    if numeric["failure_mode_severity"] > kills["max_failure_mode_severity"]:
        reasons.append("FAILURE_MODE_KILL")

    path = [
        "Evidence", "Hypothesis", "Preregister", "Robustness", "Cost/Funding/Slippage Stress",
        "Walk-forward", "OOS", "Regime Analysis", "Failure Modes", "Qualification Artifact",
    ]
    status = "killed" if reasons else "paper_candidate"
    if not reasons:
        path.append("Paper Candidate")
    core = {
        "schema_version": QUALIFICATION_SCHEMA,
        "experiment_id": experiment["experiment_id"],
        "dataset_binding_sha256": dataset["binding_sha256"],
        "code_sha": experiment["code_sha"],
        "strategy_version": experiment["strategy_version"],
        "family": experiment["family"],
        "status": status,
        "kill_reasons": reasons,
        "stage_path": path,
        "benchmark_score": numeric["benchmark_score"],
        "uncertainty_width": numeric["uncertainty_width"],
        "paper_only": True,
        "live_execution_allowed": False,
        "deterministic_risk_final_authority": True,
        "evidence_digest": _digest(dict(evidence)),
    }
    return {**core, "qualification_digest": _digest(core)}
