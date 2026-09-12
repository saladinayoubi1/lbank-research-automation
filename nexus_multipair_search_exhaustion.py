"""Fail-closed exact-exhaustion reuse for Multi-Pair historical Discovery.

Only the immutable historical Discovery computation may be skipped. Every reuse still
requires a new fresh canonical Bybit runtime snapshot before a current-run NO_WORK
proof can be emitted. Certificates are exact-SHA, exact-snapshot, exact-manifest and
exact-implementation bindings and never grant Candidate, Paper execution, or Live authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

NEIGHBORHOOD_SCHEMA = "nexus.multipair-search-neighborhood.v1"
CERTIFICATE_SCHEMA = "nexus.multipair-search-exhaustion.v1"
REUSE_SCHEMA = "nexus.multipair-discovery-v2-exhaustion-reuse.v1"
FRESH_NO_WORK_SCHEMA = "nexus.multipair-exhaustion-fresh-no-work.v1"
PHYSICAL_PROOF_SCHEMA = "nexus.multipair-discovery-v2-physical-proof.v1"
RUNTIME_SNAPSHOT_SCHEMA = "nexus.multipair-discovery-snapshot.v1"
MANIFEST_SCHEMA = "nexus.multipair-strategy-discovery-manifest.v1"
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA64_RE = re.compile(r"^[0-9a-f]{64}$")
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
TIMEFRAMES = ("minute15", "hour1", "hour4")
FAMILIES = ("momentum", "trend_breakout", "mean_reversion")
MAX_RUNTIME_AGE_MS = 20 * 60 * 1000
EXPECTED_AUTHORITY = {
    "research_only": True,
    "paper_only": True,
    "live_trading_authority": False,
    "private_credentials_allowed": False,
    "automatic_strategy_promotion": False,
}
IMPLEMENTATION_FILES: tuple[str, ...] = (
    ".github/workflows/nexus_multipair_strategy_discovery_v2.yml",
    "bybit_spot_archive_audit.py",
    "bybit_spot_archive_collector.py",
    "bybit_spot_backfill.py",
    "config/nexus-demo-strategy-matrix-v2.json",
    "nexus_multipair_archive_snapshot.py",
    "nexus_multipair_discovery_snapshot.py",
    "nexus_multipair_search_exhaustion.py",
    "nexus_multipair_strategy_discovery.py",
    "nexus_multipair_training_refinement.py",
    "nexus_multipair_trusted_surface.py",
    "nexus_multitimeframe_strategy_discovery.py",
    "phase5_data_binding.py",
    "phase6_research_pipeline.py",
    "product_research_runtime.py",
    "requirements.lock",
)


class MultiPairExhaustionError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairExhaustionError("exhaustion evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise MultiPairExhaustionError(f"implementation file unavailable: {path.as_posix()}") from exc
    return digest.hexdigest()


def _load(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairExhaustionError("exhaustion input is unavailable") from exc
    if not isinstance(value, dict):
        raise MultiPairExhaustionError("exhaustion input is not an object")
    return value


def _atomic(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _load_manifest(path: str | Path) -> dict[str, Any]:
    value = _load(path)
    required = {
        "schema_version", "experiment_id", "dataset", "symbols", "timeframes", "families",
        "train_fraction", "execution", "gates", "variants", "authority",
    }
    if set(value) != required or value.get("schema_version") != MANIFEST_SCHEMA:
        raise MultiPairExhaustionError("multi-pair discovery manifest schema mismatch")
    if tuple(value.get("symbols", ())) != SYMBOLS:
        raise MultiPairExhaustionError("manifest symbol surface mismatch")
    if tuple(value.get("timeframes", ())) != TIMEFRAMES:
        raise MultiPairExhaustionError("manifest timeframe surface mismatch")
    if tuple(value.get("families", ())) != FAMILIES:
        raise MultiPairExhaustionError("manifest family surface mismatch")
    if value.get("authority") != EXPECTED_AUTHORITY:
        raise MultiPairExhaustionError("manifest authority boundary mismatch")
    dataset = value.get("dataset")
    if not isinstance(dataset, dict) or set(dataset) != {"dataset_root", "snapshot_manifest"}:
        raise MultiPairExhaustionError("manifest dataset contract mismatch")
    if not isinstance(value.get("execution"), dict) or set(value["execution"]) != {"conservative", "stress"}:
        raise MultiPairExhaustionError("manifest execution contract mismatch")
    if not isinstance(value.get("gates"), dict) or set(value["gates"]) != {"training", "locked"}:
        raise MultiPairExhaustionError("manifest gate contract mismatch")
    variants = value.get("variants")
    if not isinstance(variants, dict) or set(variants) != set(FAMILIES):
        raise MultiPairExhaustionError("manifest variant contract mismatch")
    for family in FAMILIES:
        rows = variants.get(family)
        if not isinstance(rows, list) or not 2 <= len(rows) <= 24 or any(not isinstance(row, dict) for row in rows):
            raise MultiPairExhaustionError("manifest variant grid is missing or unbounded")
        if len({_digest(row) for row in rows}) != len(rows):
            raise MultiPairExhaustionError("manifest variant grid contains duplicates")
    return value


def build_neighborhood(
    manifest_path: str | Path,
    *,
    source_sha: str,
    snapshot_digest: str,
    root: str | Path = ".",
    implementation_files: Sequence[str] = IMPLEMENTATION_FILES,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    snapshot_digest = str(snapshot_digest).strip().lower()
    if not _SHA40_RE.fullmatch(source_sha):
        raise MultiPairExhaustionError("source SHA is invalid")
    if not _SHA64_RE.fullmatch(snapshot_digest):
        raise MultiPairExhaustionError("snapshot digest is invalid")
    manifest = _load_manifest(manifest_path)
    repo_root = Path(root).resolve()
    implementation_sha256 = {
        name: _file_sha256(repo_root / name) for name in sorted(set(implementation_files))
    }
    core = {
        "schema_version": NEIGHBORHOOD_SCHEMA,
        "source_sha": source_sha,
        "snapshot_digest": snapshot_digest,
        "experiment_id": manifest["experiment_id"],
        "manifest_sha256": _digest(manifest),
        "gates_sha256": _digest(manifest["gates"]),
        "execution_sha256": _digest(manifest["execution"]),
        "authority_sha256": _digest(manifest["authority"]),
        "variants_sha256": _digest(manifest["variants"]),
        "implementation_sha256": implementation_sha256,
        "symbols": list(manifest["symbols"]),
        "timeframes": list(manifest["timeframes"]),
        "families": list(manifest["families"]),
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_allowed": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "neighborhood_fingerprint": _digest(core)}


def verify_neighborhood(value: Mapping[str, Any]) -> None:
    core = dict(value)
    claimed = core.pop("neighborhood_fingerprint", None)
    implementation = core.get("implementation_sha256")
    if (
        core.get("schema_version") != NEIGHBORHOOD_SCHEMA
        or claimed != _digest(core)
        or not _SHA40_RE.fullmatch(str(core.get("source_sha", "")))
        or not _SHA64_RE.fullmatch(str(core.get("snapshot_digest", "")))
        or core.get("symbols") != list(SYMBOLS)
        or core.get("timeframes") != list(TIMEFRAMES)
        or core.get("families") != list(FAMILIES)
        or not isinstance(implementation, dict)
        or set(implementation) != set(IMPLEMENTATION_FILES)
        or any(not _SHA64_RE.fullmatch(str(item)) for item in implementation.values())
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("private_credentials_allowed") is not False
        or core.get("automatic_strategy_promotion") is not False
    ):
        raise MultiPairExhaustionError("search neighborhood verification failed")


def _verify_physical_zero_proof(proof: Mapping[str, Any], neighborhood: Mapping[str, Any]) -> None:
    required_hex = (
        "snapshot_digest", "discovery_digest", "refinement_training_basis_digest",
        "runtime_snapshot_digest", "requalification_digest", "search_neighborhood_fingerprint",
    )
    targeted = proof.get("refinement_targeted_cells")
    variant_counts = proof.get("refinement_variant_counts")
    if (
        proof.get("schema_version") != PHYSICAL_PROOF_SCHEMA
        or proof.get("source_sha") != neighborhood.get("source_sha")
        or proof.get("physical_runner_environment") != "self-hosted"
        or proof.get("physical_runner_os") != "Linux"
        or proof.get("execution_plane") != "nexus-bybit-network"
        or proof.get("trusted_surface_source") != "config/nexus-demo-strategy-matrix-v2.json"
        or proof.get("snapshot_digest") != neighborhood.get("snapshot_digest")
        or proof.get("snapshot_transport") != "digest_pinned_current_run_github_artifact"
        or proof.get("snapshot_data_origin") != "official_public_bybit_spot_trade_archive_aggregated"
        or proof.get("snapshot_runtime_freshness_claimed") is not False
        or proof.get("snapshot_cell_count") != 12
        or proof.get("snapshot_history_limit") != 500
        or proof.get("discovery_hypothesis_count") != 9
        or proof.get("search_neighborhood_fingerprint") != neighborhood.get("neighborhood_fingerprint")
        or any(not _SHA64_RE.fullmatch(str(proof.get(field, ""))) for field in required_hex)
        or proof.get("physical_discovery_skipped_exact_exhaustion") is not False
        or proof.get("historical_discovery_result_reused_exact_exhaustion") is not False
        or proof.get("runtime_requalification_skipped_no_proposals") is not False
        or proof.get("base_research_proposal_count") != 0
        or proof.get("refinement_started") is not True
        or proof.get("refinement_selection_basis") != "training_only"
        or proof.get("locked_holdout_used_for_refinement") is not False
        or proof.get("effective_research_proposal_count") != 0
        or proof.get("research_proposal_count") != 0
        or proof.get("requalification_status") != "NO_WORK"
        or proof.get("qualified_for_review_count") != 0
        or proof.get("rejected_count") != 0
        or proof.get("blocked_runtime_data_count") != 0
        or proof.get("runtime_snapshot_freshness_verified") is not True
        or proof.get("runtime_snapshot_distinct_from_discovery") is not True
        or proof.get("historical_discovery_snapshot_reused") is not False
        or proof.get("runtime_data_is_fresh_not_snapshot_reuse") is not True
        or not isinstance(targeted, list)
        or len(targeted) > 9
        or not isinstance(variant_counts, dict)
        or set(variant_counts) != set(FAMILIES)
        or proof.get("research_only") is not True
        or proof.get("paper_only") is not True
        or proof.get("paper_execution_started") is not False
        or proof.get("live_trading_authority") is not False
        or proof.get("private_credentials_used") is not False
        or proof.get("real_exchange_orders") is not False
        or proof.get("automatic_strategy_promotion") is not False
        or proof.get("deterministic_risk_final_authority") is not True
        or proof.get("state_isolated_from_issue_984") is not True
        or proof.get("issue_984_state_artifact_touched") is not False
        or proof.get("persistent_runtime_database_on_github") is not False
        or proof.get("legacy_btc_eth_discovery_archive_used") is not False
        or proof.get("zero_proposal_result_is_valid") is not True
    ):
        raise MultiPairExhaustionError("physical zero-proposal proof is not eligible for exhaustion certification")
    if not isinstance(proof.get("snapshot_as_of_ms"), int) or proof["snapshot_as_of_ms"] <= 0:
        raise MultiPairExhaustionError("historical snapshot timestamp is invalid")
    if not isinstance(proof.get("selection_policy"), str) or not proof["selection_policy"]:
        raise MultiPairExhaustionError("selection policy is missing")
    if not isinstance(proof.get("multiplicity_policy"), str) or not proof["multiplicity_policy"]:
        raise MultiPairExhaustionError("multiplicity policy is missing")


def build_certificate(neighborhood: Mapping[str, Any], proof: Mapping[str, Any]) -> dict[str, Any]:
    verify_neighborhood(neighborhood)
    _verify_physical_zero_proof(proof, neighborhood)
    core = {
        "schema_version": CERTIFICATE_SCHEMA,
        "neighborhood_fingerprint": neighborhood["neighborhood_fingerprint"],
        "source_sha": neighborhood["source_sha"],
        "trusted_surface_source": "config/nexus-demo-strategy-matrix-v2.json",
        "snapshot_digest": neighborhood["snapshot_digest"],
        "snapshot_transport": proof["snapshot_transport"],
        "snapshot_data_origin": proof["snapshot_data_origin"],
        "snapshot_runtime_freshness_claimed": proof["snapshot_runtime_freshness_claimed"],
        "snapshot_cell_count": proof["snapshot_cell_count"],
        "snapshot_history_limit": proof["snapshot_history_limit"],
        "discovery_hypothesis_count": proof["discovery_hypothesis_count"],
        "manifest_sha256": neighborhood["manifest_sha256"],
        "gates_sha256": neighborhood["gates_sha256"],
        "execution_sha256": neighborhood["execution_sha256"],
        "authority_sha256": neighborhood["authority_sha256"],
        "variants_sha256": neighborhood["variants_sha256"],
        "implementation_sha256": neighborhood["implementation_sha256"],
        "physical_proof_digest": _digest(dict(proof)),
        "physical_proof_run_id": str(proof["run_id"]),
        "snapshot_as_of_ms": proof["snapshot_as_of_ms"],
        "discovery_digest": proof["discovery_digest"],
        "refinement_training_basis_digest": proof["refinement_training_basis_digest"],
        "refinement_targeted_cells": proof["refinement_targeted_cells"],
        "refinement_variant_counts": proof["refinement_variant_counts"],
        "selection_policy": proof["selection_policy"],
        "multiplicity_policy": proof["multiplicity_policy"],
        "base_research_proposal_count": 0,
        "refined_research_proposal_count": 0,
        "selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "exhausted": True,
        "reuse_policy": "exact_snapshot_and_implementation_only",
        "fresh_runtime_snapshot_required_on_reuse": True,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
        "persistent_runtime_database_on_github": False,
        "legacy_btc_eth_discovery_archive_used": False,
    }
    return {**core, "certificate_digest": _digest(core)}


def verify_certificate(value: Mapping[str, Any]) -> None:
    core = dict(value)
    claimed = core.pop("certificate_digest", None)
    implementation = core.get("implementation_sha256")
    targeted = core.get("refinement_targeted_cells")
    variant_counts = core.get("refinement_variant_counts")
    if (
        core.get("schema_version") != CERTIFICATE_SCHEMA
        or claimed != _digest(core)
        or core.get("exhausted") is not True
        or core.get("reuse_policy") != "exact_snapshot_and_implementation_only"
        or core.get("fresh_runtime_snapshot_required_on_reuse") is not True
        or core.get("base_research_proposal_count") != 0
        or core.get("refined_research_proposal_count") != 0
        or core.get("selection_basis") != "training_only"
        or core.get("locked_holdout_used_for_refinement") is not False
        or not _SHA40_RE.fullmatch(str(core.get("source_sha", "")))
        or core.get("trusted_surface_source") != "config/nexus-demo-strategy-matrix-v2.json"
        or not _SHA64_RE.fullmatch(str(core.get("snapshot_digest", "")))
        or core.get("snapshot_transport") != "digest_pinned_current_run_github_artifact"
        or core.get("snapshot_data_origin") != "official_public_bybit_spot_trade_archive_aggregated"
        or core.get("snapshot_runtime_freshness_claimed") is not False
        or core.get("snapshot_cell_count") != 12
        or core.get("snapshot_history_limit") != 500
        or core.get("discovery_hypothesis_count") != 9
        or not _SHA64_RE.fullmatch(str(core.get("physical_proof_digest", "")))
        or not _SHA64_RE.fullmatch(str(core.get("discovery_digest", "")))
        or not _SHA64_RE.fullmatch(str(core.get("refinement_training_basis_digest", "")))
        or not isinstance(implementation, dict)
        or set(implementation) != set(IMPLEMENTATION_FILES)
        or any(not _SHA64_RE.fullmatch(str(item)) for item in implementation.values())
        or not isinstance(targeted, list)
        or len(targeted) > 9
        or not isinstance(variant_counts, dict)
        or set(variant_counts) != set(FAMILIES)
        or not isinstance(core.get("snapshot_as_of_ms"), int)
        or core.get("snapshot_as_of_ms", 0) <= 0
        or not isinstance(core.get("selection_policy"), str)
        or not core.get("selection_policy")
        or not isinstance(core.get("multiplicity_policy"), str)
        or not core.get("multiplicity_policy")
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("private_credentials_used") is not False
        or core.get("automatic_strategy_promotion") is not False
        or core.get("state_isolated_from_issue_984") is not True
        or core.get("issue_984_state_artifact_touched") is not False
        or core.get("persistent_runtime_database_on_github") is not False
        or core.get("legacy_btc_eth_discovery_archive_used") is not False
    ):
        raise MultiPairExhaustionError("search exhaustion certificate verification failed")


def certificate_is_reusable(neighborhood: Mapping[str, Any], certificate: Mapping[str, Any]) -> bool:
    try:
        verify_neighborhood(neighborhood)
        verify_certificate(certificate)
    except MultiPairExhaustionError:
        return False
    return (
        certificate.get("neighborhood_fingerprint") == neighborhood.get("neighborhood_fingerprint")
        and certificate.get("source_sha") == neighborhood.get("source_sha")
        and certificate.get("snapshot_digest") == neighborhood.get("snapshot_digest")
        and certificate.get("manifest_sha256") == neighborhood.get("manifest_sha256")
        and certificate.get("gates_sha256") == neighborhood.get("gates_sha256")
        and certificate.get("execution_sha256") == neighborhood.get("execution_sha256")
        and certificate.get("authority_sha256") == neighborhood.get("authority_sha256")
        and certificate.get("variants_sha256") == neighborhood.get("variants_sha256")
        and certificate.get("implementation_sha256") == neighborhood.get("implementation_sha256")
    )


def build_reuse_evidence(
    neighborhood: Mapping[str, Any], certificate: Mapping[str, Any], *, run_id: str
) -> dict[str, Any]:
    if not str(run_id).isdigit():
        raise MultiPairExhaustionError("run_id must be numeric")
    if not certificate_is_reusable(neighborhood, certificate):
        raise MultiPairExhaustionError("certificate does not match the exact current neighborhood")
    core = {
        "schema_version": REUSE_SCHEMA,
        "source_sha": neighborhood["source_sha"],
        "run_id": str(run_id),
        "trusted_surface_source": certificate["trusted_surface_source"],
        "snapshot_digest": neighborhood["snapshot_digest"],
        "snapshot_transport": certificate["snapshot_transport"],
        "snapshot_data_origin": certificate["snapshot_data_origin"],
        "snapshot_runtime_freshness_claimed": certificate["snapshot_runtime_freshness_claimed"],
        "snapshot_cell_count": certificate["snapshot_cell_count"],
        "snapshot_history_limit": certificate["snapshot_history_limit"],
        "discovery_hypothesis_count": certificate["discovery_hypothesis_count"],
        "snapshot_as_of_ms": certificate["snapshot_as_of_ms"],
        "neighborhood_fingerprint": neighborhood["neighborhood_fingerprint"],
        "certificate_digest": certificate["certificate_digest"],
        "physical_proof_digest": certificate["physical_proof_digest"],
        "physical_proof_run_id": certificate["physical_proof_run_id"],
        "discovery_digest": certificate["discovery_digest"],
        "refinement_training_basis_digest": certificate["refinement_training_basis_digest"],
        "refinement_targeted_cells": certificate["refinement_targeted_cells"],
        "refinement_variant_counts": certificate["refinement_variant_counts"],
        "selection_policy": certificate["selection_policy"],
        "multiplicity_policy": certificate["multiplicity_policy"],
        "base_research_proposal_count": 0,
        "refined_research_proposal_count": 0,
        "effective_research_proposal_count": 0,
        "research_proposal_count": 0,
        "refinement_started": True,
        "refinement_selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "physical_discovery_skipped_exact_exhaustion": True,
        "historical_discovery_result_reused_exact_exhaustion": True,
        "fresh_runtime_snapshot_required": True,
        "runtime_snapshot_skipped_no_proposals": False,
        "runtime_requalification_skipped_no_proposals": True,
        "reuse_policy": "exact_snapshot_and_implementation_only",
        "research_only": True,
        "paper_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "state_isolated_from_issue_984": certificate["state_isolated_from_issue_984"],
        "issue_984_state_artifact_touched": certificate["issue_984_state_artifact_touched"],
        "persistent_runtime_database_on_github": certificate["persistent_runtime_database_on_github"],
        "legacy_btc_eth_discovery_archive_used": certificate["legacy_btc_eth_discovery_archive_used"],
    }
    return {**core, "reuse_evidence_digest": _digest(core)}


def verify_reuse_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "binding": False, "exhaustion": False, "authority": False}
    try:
        core = dict(value)
        claimed = core.pop("reuse_evidence_digest", None)
        variant_counts = core.get("refinement_variant_counts")
        checks["schema"] = core.get("schema_version") == REUSE_SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["binding"] = bool(
            _SHA40_RE.fullmatch(str(core.get("source_sha", "")))
            and str(core.get("run_id", "")).isdigit()
            and core.get("trusted_surface_source") == "config/nexus-demo-strategy-matrix-v2.json"
            and _SHA64_RE.fullmatch(str(core.get("snapshot_digest", "")))
            and core.get("snapshot_transport") == "digest_pinned_current_run_github_artifact"
            and core.get("snapshot_data_origin") == "official_public_bybit_spot_trade_archive_aggregated"
            and core.get("snapshot_runtime_freshness_claimed") is False
            and core.get("snapshot_cell_count") == 12
            and core.get("snapshot_history_limit") == 500
            and core.get("discovery_hypothesis_count") == 9
            and _SHA64_RE.fullmatch(str(core.get("neighborhood_fingerprint", "")))
            and _SHA64_RE.fullmatch(str(core.get("certificate_digest", "")))
            and _SHA64_RE.fullmatch(str(core.get("physical_proof_digest", "")))
            and _SHA64_RE.fullmatch(str(core.get("discovery_digest", "")))
            and _SHA64_RE.fullmatch(str(core.get("refinement_training_basis_digest", "")))
            and isinstance(core.get("snapshot_as_of_ms"), int)
            and core.get("snapshot_as_of_ms", 0) > 0
        )
        checks["exhaustion"] = bool(
            core.get("base_research_proposal_count") == 0
            and core.get("refined_research_proposal_count") == 0
            and core.get("effective_research_proposal_count") == 0
            and core.get("research_proposal_count") == 0
            and core.get("refinement_started") is True
            and core.get("refinement_selection_basis") == "training_only"
            and core.get("locked_holdout_used_for_refinement") is False
            and core.get("physical_discovery_skipped_exact_exhaustion") is True
            and core.get("historical_discovery_result_reused_exact_exhaustion") is True
            and core.get("fresh_runtime_snapshot_required") is True
            and core.get("runtime_snapshot_skipped_no_proposals") is False
            and core.get("runtime_requalification_skipped_no_proposals") is True
            and core.get("reuse_policy") == "exact_snapshot_and_implementation_only"
            and isinstance(core.get("refinement_targeted_cells"), list)
            and len(core["refinement_targeted_cells"]) <= 9
            and isinstance(variant_counts, dict)
            and set(variant_counts) == set(FAMILIES)
            and isinstance(core.get("selection_policy"), str)
            and bool(core.get("selection_policy"))
            and isinstance(core.get("multiplicity_policy"), str)
            and bool(core.get("multiplicity_policy"))
        )
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("paper_execution_started") is False
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("state_isolated_from_issue_984") is True
            and core.get("issue_984_state_artifact_touched") is False
            and core.get("persistent_runtime_database_on_github") is False
            and core.get("legacy_btc_eth_discovery_archive_used") is False
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def build_fresh_no_work(
    reuse: Mapping[str, Any], runtime_snapshot: Mapping[str, Any], *, now_ms: int
) -> dict[str, Any]:
    if verify_reuse_evidence(reuse).get("decision") != "pass":
        raise MultiPairExhaustionError("reuse evidence failed verification")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairExhaustionError("now_ms must be a positive integer")
    runtime_digest = str(runtime_snapshot.get("snapshot_digest", ""))
    as_of_ms = runtime_snapshot.get("as_of_ms")
    if (
        runtime_snapshot.get("schema_version") != RUNTIME_SNAPSHOT_SCHEMA
        or runtime_snapshot.get("source_sha") != reuse.get("source_sha")
        or not _SHA64_RE.fullmatch(runtime_digest)
        or runtime_digest == reuse.get("snapshot_digest")
        or runtime_snapshot.get("symbols") != list(SYMBOLS)
        or runtime_snapshot.get("timeframes") != list(TIMEFRAMES)
        or runtime_snapshot.get("cell_count") != 12
        or runtime_snapshot.get("history_limit") != 240
        or runtime_snapshot.get("data_origin") != "canonical_public_bybit_closed_candles"
        or isinstance(as_of_ms, bool)
        or not isinstance(as_of_ms, int)
        or not 0 <= now_ms - as_of_ms <= MAX_RUNTIME_AGE_MS
        or runtime_snapshot.get("research_only") is not True
        or runtime_snapshot.get("paper_execution_started") is not False
        or runtime_snapshot.get("live_trading_authority") is not False
        or runtime_snapshot.get("private_credentials_used") is not False
        or runtime_snapshot.get("automatic_strategy_promotion") is not False
        or runtime_snapshot.get("silent_exchange_substitution") is not False
    ):
        raise MultiPairExhaustionError("fresh runtime snapshot is not eligible for exhaustion NO_WORK binding")
    core = {
        "schema_version": FRESH_NO_WORK_SCHEMA,
        "source_sha": reuse["source_sha"],
        "run_id": reuse["run_id"],
        "historical_snapshot_digest": reuse["snapshot_digest"],
        "discovery_digest": reuse["discovery_digest"],
        "reuse_evidence_digest": reuse["reuse_evidence_digest"],
        "certificate_digest": reuse["certificate_digest"],
        "runtime_snapshot_digest": runtime_digest,
        "runtime_snapshot_as_of_ms": as_of_ms,
        "runtime_snapshot_history_limit": 240,
        "runtime_snapshot_data_origin": "canonical_public_bybit_closed_candles",
        "runtime_data_transport": "digest_pinned_physical_bybit_rest_snapshot",
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "runtime_snapshot_distinct_from_discovery": True,
        "historical_discovery_snapshot_reused": False,
        "runtime_data_is_fresh_not_snapshot_reuse": True,
        "runtime_snapshot_freshness_verified": True,
        "status": "NO_WORK",
        "proposal_count": 0,
        "qualified_for_review_count": 0,
        "rejected_count": 0,
        "blocked_runtime_data_count": 0,
        "physical_discovery_skipped_exact_exhaustion": True,
        "historical_discovery_result_reused_exact_exhaustion": True,
        "runtime_requalification_skipped_no_proposals": True,
        "candidate_creation_authority": False,
        "promotion_authority": False,
        "research_only": True,
        "paper_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "requalification_digest": _digest(core)}


def verify_fresh_no_work(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "binding": False, "freshness": False, "counts": False, "authority": False}
    try:
        core = dict(value)
        claimed = core.pop("requalification_digest", None)
        checks["schema"] = core.get("schema_version") == FRESH_NO_WORK_SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["binding"] = bool(
            _SHA40_RE.fullmatch(str(core.get("source_sha", "")))
            and str(core.get("run_id", "")).isdigit()
            and all(
                _SHA64_RE.fullmatch(str(core.get(field, "")))
                for field in (
                    "historical_snapshot_digest", "discovery_digest", "reuse_evidence_digest",
                    "certificate_digest", "runtime_snapshot_digest",
                )
            )
            and core.get("runtime_snapshot_digest") != core.get("historical_snapshot_digest")
        )
        checks["freshness"] = bool(
            isinstance(core.get("runtime_snapshot_as_of_ms"), int)
            and not isinstance(core.get("runtime_snapshot_as_of_ms"), bool)
            and core.get("runtime_snapshot_as_of_ms", 0) > 0
            and core.get("runtime_snapshot_history_limit") == 240
            and core.get("runtime_snapshot_data_origin") == "canonical_public_bybit_closed_candles"
            and core.get("runtime_data_transport") == "digest_pinned_physical_bybit_rest_snapshot"
            and core.get("symbols") == list(SYMBOLS)
            and core.get("timeframes") == list(TIMEFRAMES)
            and core.get("runtime_snapshot_distinct_from_discovery") is True
            and core.get("historical_discovery_snapshot_reused") is False
            and core.get("runtime_data_is_fresh_not_snapshot_reuse") is True
            and core.get("runtime_snapshot_freshness_verified") is True
        )
        checks["counts"] = bool(
            core.get("status") == "NO_WORK"
            and core.get("proposal_count") == 0
            and core.get("qualified_for_review_count") == 0
            and core.get("rejected_count") == 0
            and core.get("blocked_runtime_data_count") == 0
            and core.get("physical_discovery_skipped_exact_exhaustion") is True
            and core.get("historical_discovery_result_reused_exact_exhaustion") is True
            and core.get("runtime_requalification_skipped_no_proposals") is True
        )
        checks["authority"] = bool(
            core.get("candidate_creation_authority") is False
            and core.get("promotion_authority") is False
            and core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("paper_execution_started") is False
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    fingerprint = sub.add_parser("fingerprint")
    fingerprint.add_argument("--manifest", type=Path, required=True)
    fingerprint.add_argument("--source-sha", required=True)
    fingerprint.add_argument("--snapshot-digest", required=True)
    fingerprint.add_argument("--root", type=Path, default=Path("."))
    fingerprint.add_argument("--output", type=Path, required=True)

    certify = sub.add_parser("certify")
    certify.add_argument("--neighborhood", type=Path, required=True)
    certify.add_argument("--proof", type=Path, required=True)
    certify.add_argument("--output", type=Path, required=True)

    check = sub.add_parser("check")
    check.add_argument("--neighborhood", type=Path, required=True)
    check.add_argument("--certificate", type=Path, required=True)

    reuse = sub.add_parser("reuse")
    reuse.add_argument("--neighborhood", type=Path, required=True)
    reuse.add_argument("--certificate", type=Path, required=True)
    reuse.add_argument("--run-id", required=True)
    reuse.add_argument("--output", type=Path, required=True)

    verify_reuse = sub.add_parser("verify-reuse")
    verify_reuse.add_argument("--evidence", type=Path, required=True)

    bind_runtime = sub.add_parser("bind-runtime")
    bind_runtime.add_argument("--reuse", type=Path, required=True)
    bind_runtime.add_argument("--runtime-snapshot", type=Path, required=True)
    bind_runtime.add_argument("--now-ms", type=int, required=True)
    bind_runtime.add_argument("--output", type=Path, required=True)

    verify_runtime = sub.add_parser("verify-runtime")
    verify_runtime.add_argument("--evidence", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "fingerprint":
        value = build_neighborhood(
            args.manifest, source_sha=args.source_sha, snapshot_digest=args.snapshot_digest, root=args.root
        )
        _atomic(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0
    if args.command == "certify":
        value = build_certificate(_load(args.neighborhood), _load(args.proof))
        _atomic(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0
    if args.command == "check":
        reusable = certificate_is_reusable(_load(args.neighborhood), _load(args.certificate))
        print(json.dumps({"reusable": reusable}, sort_keys=True))
        return 0
    if args.command == "reuse":
        value = build_reuse_evidence(_load(args.neighborhood), _load(args.certificate), run_id=args.run_id)
        _atomic(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0
    if args.command == "verify-reuse":
        verification = verify_reuse_evidence(_load(args.evidence))
        print(json.dumps(verification, sort_keys=True))
        return 0 if verification["decision"] == "pass" else 1
    if args.command == "bind-runtime":
        value = build_fresh_no_work(_load(args.reuse), _load(args.runtime_snapshot), now_ms=args.now_ms)
        _atomic(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0
    verification = verify_fresh_no_work(_load(args.evidence))
    print(json.dumps(verification, sort_keys=True))
    return 0 if verification["decision"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
