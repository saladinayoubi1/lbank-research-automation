"""Assemble the fixed-SHA NEXUS final Proof Mission from durable evidence.

The assembler is deliberately data-only: it never invents worker execution,
resource availability, scheduler state, synchronized regime output, or Project
Memory freshness. It binds already-produced evidence to one Git SHA and
delegates the final decision to ``nexus_final_proof_mission``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import nexus_final_proof_mission as final_proof
import project_memory_validator as memory_validator

MAX_INPUT_BYTES = 16_000_000


class FinalProofAssemblerError(RuntimeError):
    pass


def _read_json(path: Path, label: str) -> Any:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FinalProofAssemblerError(f"{label} is unavailable") from exc
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise FinalProofAssemblerError(f"{label} size is outside bounds")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FinalProofAssemblerError(f"{label} is not valid JSON") from exc


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FinalProofAssemblerError(f"{label} root must be an object")
    return dict(value)


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise FinalProofAssemblerError("resource utilization root must be an array of objects")
    return [dict(row) for row in value]


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise FinalProofAssemblerError("Project Memory state is unavailable") from exc


def assemble(
    *,
    root: Path,
    source_sha: str,
    supervisor_ledger_path: Path,
    mission_control_path: Path,
    regime_cycle_path: Path,
    scheduler_snapshot_path: Path,
    resource_utilization_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    try:
        memory = memory_validator.validate_repository(
            root, expected_observed_main=source_sha
        )
    except memory_validator.MemoryValidationError as exc:
        raise FinalProofAssemblerError(f"Project Memory rejected: {exc}") from exc

    supervisor = _object(_read_json(supervisor_ledger_path, "Supervisor ledger"), "Supervisor ledger")
    mission_control = _object(
        _read_json(mission_control_path, "Mission Control projection"),
        "Mission Control projection",
    )
    regime_cycle = _object(
        _read_json(regime_cycle_path, "synchronized regime cycle"),
        "synchronized regime cycle",
    )
    scheduler = _object(
        _read_json(scheduler_snapshot_path, "scheduler snapshot"),
        "scheduler snapshot",
    )
    resources = _rows(_read_json(resource_utilization_path, "resource utilization"))

    if supervisor.get("source_sha") != source_sha:
        raise FinalProofAssemblerError("Supervisor ledger is not bound to source SHA")
    if regime_cycle.get("source_sha") != source_sha:
        raise FinalProofAssemblerError("synchronized regime cycle is not bound to source SHA")
    if scheduler.get("source_sha") != source_sha:
        raise FinalProofAssemblerError("scheduler snapshot is not bound to source SHA")
    if any(row.get("source_sha") != source_sha for row in resources):
        raise FinalProofAssemblerError("resource utilization is not bound to source SHA")

    bundle = final_proof.build_unsigned_bundle(
        source_sha=source_sha,
        supervisor_ledger=supervisor,
        mission_control_projection=mission_control,
        regime_cycle_snapshot=regime_cycle,
        scheduler_snapshot=scheduler,
        resource_utilization=resources,
    )
    bundle["project_memory_projection"].update(
        {
            "canonical_state_observed_main_sha": memory["observed_main_sha"],
            "canonical_state_sha256": _sha256(root / "docs/project_memory/STATE.json"),
            "freshness_validation": "exact_or_direct_snapshot_integration",
        }
    )
    # The Project Memory projection is part of the signed bundle. Recompute the
    # producer digest after adding its durable-state provenance.
    unsigned = dict(bundle)
    unsigned.pop("unsigned_bundle_digest", None)
    unsigned.pop("project_memory_projection", None)
    bundle["unsigned_bundle_digest"] = final_proof._digest(unsigned)
    bundle["project_memory_projection"]["proof_bundle_digest"] = bundle[
        "unsigned_bundle_digest"
    ]
    return final_proof.save_verified_bundle(output_path, bundle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--supervisor-ledger", type=Path, required=True)
    parser.add_argument("--mission-control", type=Path, required=True)
    parser.add_argument("--regime-cycle", type=Path, required=True)
    parser.add_argument("--scheduler-snapshot", type=Path, required=True)
    parser.add_argument("--resource-utilization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = assemble(
            root=args.root.resolve(),
            source_sha=args.source_sha,
            supervisor_ledger_path=args.supervisor_ledger,
            mission_control_path=args.mission_control,
            regime_cycle_path=args.regime_cycle,
            scheduler_snapshot_path=args.scheduler_snapshot,
            resource_utilization_path=args.resource_utilization,
            output_path=args.output,
        )
    except (OSError, FinalProofAssemblerError, final_proof.FinalProofMissionError) as exc:
        parser.exit(1, f"NEXUS final Proof Mission assembly failed: {exc}\n")
    print(json.dumps({
        "decision": result["verification"]["decision"],
        "source_sha": result["source_sha"],
        "bundle_digest": result["bundle_digest"],
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
