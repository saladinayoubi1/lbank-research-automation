"""Select existing exact-source Discovery evidence without executing research."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any


WORKFLOW_NAME = "NEXUS Multi-Pair Discovery v2 physical proof"
WORKFLOW_PATH = ".github/workflows/nexus_multipair_strategy_discovery_v2.yml"
PROOF_PREFIX = "nexus-multipair-discovery-v2-proof-"
PHYSICAL_JOBS = (
    "runtime-wheelhouse",
    "discover-physical",
    "runtime-snapshot",
    "persist-runtime-snapshot",
    "requalify-physical",
    "persist-proof",
)
MetadataReader = Callable[[int], Mapping[str, Any]]


@dataclass(frozen=True)
class DiscoverySelection:
    run_id: int
    reason: str
    skipped_run_ids: tuple[int, ...] = ()


def _complete_page(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    rows = payload.get(key)
    total = payload.get("total_count")
    if (
        not isinstance(rows, list)
        or type(total) is not int
        or not 0 <= total <= 100
        or total != len(rows)
        or any(not isinstance(row, Mapping) for row in rows)
    ):
        raise ValueError(f"incomplete or malformed {key} metadata")
    return rows


def select_discovery_proof_run(
    runs: Sequence[Mapping[str, Any]],
    source_sha: str,
    read_jobs: MetadataReader,
    read_artifacts: MetadataReader,
) -> DiscoverySelection:
    """Use API order; skip legitimate no-proof runs, reject invalid evidence.

    Readers must return complete pages for one run, with jobs from its latest
    attempt. An upload job reported successful without its exact proof remains
    an error. A skipped upload never creates evidence or production authority.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("invalid exact source SHA")
    skipped: list[int] = []
    reasons: list[str] = []
    for run in runs:
        run_id = run.get("id")
        if (
            type(run_id) is not int
            or run_id <= 0
            or run.get("name") != WORKFLOW_NAME
            or run.get("path") != WORKFLOW_PATH
            or run.get("head_branch") != "main"
            or run.get("head_sha") != source_sha
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("event") not in {"push", "workflow_dispatch"}
        ):
            raise ValueError("Discovery run identity mismatch")
        jobs = _complete_page(read_jobs(run_id), "jobs")
        names = [job.get("name") for job in jobs]
        required = {"contract-test", *PHYSICAL_JOBS}
        if any(not isinstance(name, str) for name in names) or set(names) != required or len(names) != len(required):
            raise ValueError("missing, duplicate or unexpected Discovery jobs")
        states = {job["name"]: job.get("conclusion") for job in jobs}
        if any(job.get("status") != "completed" for job in jobs) or states["contract-test"] != "success":
            raise ValueError("Discovery jobs are not a completed successful contract")
        if any(states[name] not in {"success", "skipped"} for name in PHYSICAL_JOBS):
            raise ValueError("Discovery physical job metadata contradicts successful run")
        artifacts = _complete_page(read_artifacts(run_id), "artifacts")
        proof_name = PROOF_PREFIX + source_sha
        proofs = [row for row in artifacts if str(row.get("name", "")).startswith(PROOF_PREFIX)]
        if any(row.get("name") != proof_name for row in proofs):
            raise ValueError("Discovery proof artifact source name mismatch")
        if states["persist-proof"] == "skipped":
            if proofs:
                raise ValueError("Discovery proof exists without a successful publisher")
            skipped.append(run_id)
            reasons.append(
                "CONTRACT_ONLY_NO_PHYSICAL_PROOF"
                if all(states[name] == "skipped" for name in PHYSICAL_JOBS)
                else "WAITING_FOR_PHYSICAL_PROOF"
            )
            continue
        if any(states[name] != "success" for name in PHYSICAL_JOBS):
            raise ValueError("Discovery publisher success without complete physical path")
        rows = [row for row in proofs if row.get("expired") is False]
        if len(rows) != 1:
            raise ValueError(f"expected one exact artifact {proof_name}, got {len(rows)}")
        artifact = rows[0]
        binding = artifact.get("workflow_run")
        if not isinstance(binding, Mapping) or (
            str(binding.get("id")) != str(run_id)
            or binding.get("head_sha") != source_sha
            or binding.get("head_branch") != "main"
        ):
            raise ValueError("Discovery proof artifact run binding mismatch")
        if type(artifact.get("id")) is not int or artifact["id"] <= 0:
            raise ValueError("invalid Discovery proof artifact ID")
        size = artifact.get("size_in_bytes")
        if type(size) is not int or not 0 < size <= 250 * 1024 * 1024:
            raise ValueError("Discovery proof artifact size is outside bounds")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(artifact.get("digest", ""))):
            raise ValueError("Discovery proof artifact has invalid GitHub digest")
        return DiscoverySelection(run_id, "ELIGIBLE_PHYSICAL_PROOF", tuple(skipped))
    reason = (
        "CONTRACT_ONLY_NO_PHYSICAL_PROOF"
        if reasons and all(value == "CONTRACT_ONLY_NO_PHYSICAL_PROOF" for value in reasons)
        else "WAITING_FOR_PHYSICAL_PROOF" if reasons
        else "NO_EXACT_SUCCESSFUL_DISCOVERY_RUN"
    )
    return DiscoverySelection(0, reason, tuple(skipped))
