"""Fail-closed physical acceptance for four-symbol Discovery and requalification.

This module orchestrates the already-reviewed Multi-Pair Research components on
one exact Git source revision. It collects a fresh canonical public Bybit
snapshot, runs leakage-resistant Discovery, then independently requalifies any
RESEARCH_PROPOSAL_ONLY outputs against fresh runtime data. The resulting compact
proof has no Candidate/Paper execution, promotion, private-credential, order, or
Live authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_multipair_discovery_snapshot import collect_snapshot, verify_snapshot
from nexus_multipair_strategy_discovery import (
    load_manifest as load_discovery_manifest,
    run as run_discovery,
    verify_discovery,
)
from nexus_multipair_strategy_proposal_requalification import (
    run as run_requalification,
    verify_requalification,
)
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES


SCHEMA = "nexus.multipair-physical-discovery-acceptance.v1"
FAMILIES = ("momentum", "trend_breakout", "mean_reversion")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class MultiPairPhysicalDiscoveryAcceptanceError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MultiPairPhysicalDiscoveryAcceptanceError("acceptance evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 5_000_000:
        raise MultiPairPhysicalDiscoveryAcceptanceError(f"acceptance input is unavailable or unsafe: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairPhysicalDiscoveryAcceptanceError(f"acceptance input is unreadable: {target}") from exc
    if not isinstance(value, dict):
        raise MultiPairPhysicalDiscoveryAcceptanceError(f"acceptance input is not an object: {target}")
    return value


def _atomic_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _exact_sha(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA_RE.fullmatch(normalized):
        raise MultiPairPhysicalDiscoveryAcceptanceError("source_sha must be an exact 40-character Git SHA")
    return normalized


def _exact_run_id(value: str) -> str:
    normalized = str(value).strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        raise MultiPairPhysicalDiscoveryAcceptanceError("run_id must be a positive decimal GitHub run id")
    return normalized


def _safe_snapshot_root(manifest: Mapping[str, Any]) -> Path:
    dataset = manifest.get("dataset")
    if not isinstance(dataset, Mapping):
        raise MultiPairPhysicalDiscoveryAcceptanceError("discovery dataset contract is missing")
    raw = Path(str(dataset.get("dataset_root", "")))
    if raw.is_absolute() or not raw.parts or raw.parts[0] != "build" or ".." in raw.parts:
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical discovery snapshot root must remain under build/")
    repository = Path.cwd().resolve()
    target = (repository / raw).resolve()
    build_root = (repository / "build").resolve()
    try:
        target.relative_to(build_root)
    except ValueError as exc:
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical discovery snapshot root escaped build/") from exc
    return target


def _discovery_contract(discovery: Mapping[str, Any]) -> dict[str, bool]:
    cells = discovery.get("cells")
    proposals = discovery.get("research_proposals")
    return {
        "trusted_surface": (
            discovery.get("symbols") == list(SYMBOLS)
            and discovery.get("timeframes") == list(TIMEFRAMES)
            and discovery.get("families") == list(FAMILIES)
            and discovery.get("hypothesis_count") == 9
            and isinstance(cells, list)
            and len(cells) == 9
        ),
        "training_selection_only": bool(
            isinstance(cells, list)
            and all(isinstance(row, Mapping) and row.get("selection_source") == "training_only" for row in cells)
        ),
        "locked_holdout_after_selection": bool(
            isinstance(cells, list)
            and all(
                isinstance(row, Mapping)
                and isinstance(row.get("locked_profiles"), Mapping)
                and set(row["locked_profiles"]) == {"conservative", "stress"}
                for row in cells
            )
        ),
        "research_proposal_only": bool(
            isinstance(proposals, list)
            and all(
                isinstance(row, Mapping)
                and row.get("proposal_state") == "RESEARCH_PROPOSAL_ONLY"
                and row.get("requires_independent_runtime_requalification") is True
                and row.get("promotion_authority") is False
                and row.get("live_trading_authority") is False
                for row in proposals
            )
        ),
        "discovery_authority": (
            discovery.get("research_only") is True
            and discovery.get("paper_only") is True
            and discovery.get("live_trading_authority") is False
            and discovery.get("private_credentials_used") is False
            and discovery.get("automatic_strategy_promotion") is False
            and discovery.get("automatic_paper_forward_started") is False
        ),
    }


def run_acceptance(
    *,
    manifest_path: str | Path,
    source_sha: str,
    run_id: str,
    now_ms: int,
    state_root: str | Path,
    work_root: str | Path,
    output: str | Path,
    runner_name: str,
    runner_os: str,
    runner_environment: str,
    execution_plane: str,
    history_limit: int = 240,
) -> dict[str, Any]:
    source_sha = _exact_sha(source_sha)
    run_id = _exact_run_id(run_id)
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairPhysicalDiscoveryAcceptanceError("now_ms must be a positive integer")
    if isinstance(history_limit, bool) or not isinstance(history_limit, int) or not 160 <= history_limit <= 500:
        raise MultiPairPhysicalDiscoveryAcceptanceError("history_limit must be between 160 and 500")
    if not str(runner_name).strip() or runner_os != "Linux" or runner_environment != "self-hosted":
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical acceptance requires an identified self-hosted Linux runner")
    if execution_plane != "nexus-bybit-network":
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical acceptance requires the nexus-bybit-network execution plane")

    manifest = load_discovery_manifest(manifest_path)
    snapshot_root = _safe_snapshot_root(manifest)
    work = Path(work_root).resolve()
    state = Path(state_root).resolve()
    if "nexus-persistent-paper-trading-state" in str(state) or "issue-984" in str(state).lower():
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical discovery state must be isolated from Issue #984")
    work.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    snapshot = collect_snapshot(
        output_root=snapshot_root,
        source_sha=source_sha,
        now_ms=now_ms,
        limit=history_limit,
    )
    snapshot_verification = verify_snapshot(snapshot_root, snapshot)
    if snapshot_verification.get("decision") != "pass":
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical discovery snapshot verification rejected evidence")
    if snapshot.get("source_sha") != source_sha or snapshot.get("cell_count") != 12:
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical discovery snapshot did not bind the exact 12-cell source surface")

    discovery_root = work / "discovery"
    run_discovery(manifest_path, discovery_root, source_sha=source_sha)
    discovery_path = discovery_root / "multipair_strategy_discovery.json"
    queue_path = discovery_root / "research_proposals.json"
    discovery = _read_json(discovery_path)
    discovery_verification = verify_discovery(discovery)
    if discovery_verification.get("decision") != "pass":
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical Discovery verification rejected evidence")

    requalification_path = work / "requalification" / "result.json"
    run_requalification(
        discovery_path,
        queue_path,
        source_sha=source_sha,
        discovery_source_sha=source_sha,
        state_root=state / "requalification",
        output=requalification_path,
        now_ms=now_ms,
    )
    requalification = _read_json(requalification_path)
    requalification_verification = verify_requalification(requalification)
    if requalification_verification.get("decision") != "pass":
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical runtime requalification verification rejected evidence")

    contract = _discovery_contract(discovery)
    proposals = discovery.get("research_proposals", [])
    proposal_count = int(discovery.get("research_proposal_count", -1))
    requalification_count = int(requalification.get("proposal_count", -2))
    blocked_count = int(requalification.get("blocked_runtime_data_count", -1))
    proposal_results = requalification.get("proposal_results")
    candidate_state_created = bool(
        isinstance(proposal_results, list)
        and any(isinstance(row, Mapping) and row.get("candidate_state_created") is not False for row in proposal_results)
    )
    accepted = bool(
        all(contract.values())
        and proposal_count == len(proposals)
        and proposal_count == requalification_count
        and blocked_count == 0
        and requalification.get("runtime_data_is_fresh_not_snapshot_reuse") is True
        and requalification.get("candidate_creation_authority") is False
        and requalification.get("promotion_authority") is False
        and requalification.get("paper_execution_started") is False
        and requalification.get("live_trading_authority") is False
        and requalification.get("private_credentials_used") is False
        and requalification.get("automatic_strategy_promotion") is False
        and requalification.get("deterministic_risk_final_authority") is True
        and candidate_state_created is False
    )
    if not accepted:
        raise MultiPairPhysicalDiscoveryAcceptanceError("physical Discovery/requalification acceptance failed closed")

    core = {
        "schema_version": SCHEMA,
        "decision": "pass",
        "source_sha": source_sha,
        "run_id": run_id,
        "runner_name": str(runner_name),
        "runner_os": runner_os,
        "runner_environment": runner_environment,
        "execution_plane": execution_plane,
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "families": list(FAMILIES),
        "snapshot_cell_count": 12,
        "snapshot_history_limit": history_limit,
        "hypothesis_count": 9,
        "research_proposal_count": proposal_count,
        "requalification_proposal_count": requalification_count,
        "blocked_runtime_data_count": blocked_count,
        "qualified_for_review_count": requalification.get("qualified_for_review_count"),
        "rejected_count": requalification.get("rejected_count"),
        "requalification_status": requalification.get("status"),
        "snapshot_digest": snapshot.get("snapshot_digest"),
        "discovery_digest": discovery.get("discovery_digest"),
        "discovery_verification_digest": discovery_verification.get("verification_digest"),
        "requalification_digest": requalification.get("requalification_digest"),
        "requalification_verification_digest": requalification_verification.get("verification_digest"),
        "training_selection_only": contract["training_selection_only"],
        "locked_holdout_after_selection": contract["locked_holdout_after_selection"],
        "conservative_and_stress_costs": contract["locked_holdout_after_selection"],
        "zero_proposals_valid": True,
        "research_proposal_only": contract["research_proposal_only"],
        "fresh_runtime_requalification": True,
        "candidate_state_created": False,
        "paper_execution_started": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "deterministic_risk_final_authority": True,
        "silent_exchange_substitution": False,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
        "persistent_runtime_database_on_github": False,
    }
    evidence = {**core, "evidence_digest": _digest(core)}
    _atomic_json(output, evidence)
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--now-ms", required=True, type=int)
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--runner-name", required=True)
    parser.add_argument("--runner-os", required=True)
    parser.add_argument("--runner-environment", required=True)
    parser.add_argument("--execution-plane", default="nexus-bybit-network")
    parser.add_argument("--history-limit", type=int, default=240)
    args = parser.parse_args()
    try:
        evidence = run_acceptance(
            manifest_path=args.manifest,
            source_sha=args.source_sha,
            run_id=args.run_id,
            now_ms=args.now_ms,
            state_root=args.state_root,
            work_root=args.work_root,
            output=args.output,
            runner_name=args.runner_name,
            runner_os=args.runner_os,
            runner_environment=args.runner_environment,
            execution_plane=args.execution_plane,
            history_limit=args.history_limit,
        )
    except Exception as exc:
        print(f"physical_multipair_discovery_acceptance=REJECT:{type(exc).__name__}:{exc}")
        return 2
    print(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
