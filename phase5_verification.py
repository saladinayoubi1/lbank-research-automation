from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import phase5_attempts as attempts

VERIFICATION_SCHEMA = "nexus.phase5-verification.v1"
MAX_ARTIFACTS = 16
MAX_CHECKS = 32
MAX_MANIFEST_BYTES = 512_000


class VerificationError(RuntimeError):
    pass


class VerificationConflict(VerificationError):
    pass


def _bounded_string(value: Any, field: str, *, limit: int = 160) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise VerificationError(f"{field} must be a non-empty bounded string")
    return value


def _digest(value: Any, *, limit: int = MAX_MANIFEST_BYTES) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerificationError("verification value is not canonical JSON") from exc
    if len(raw) > limit:
        raise VerificationError("verification value exceeds bounded size")
    return hashlib.sha256(raw).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise VerificationError(f"{field} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise VerificationError(f"{field} must be a SHA-256 hex digest") from exc
    return value.lower()


def _workers(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workers = config.get("workers")
    if not isinstance(workers, list):
        raise VerificationError("worker registry must be a list")
    index: dict[str, dict[str, Any]] = {}
    for worker in workers:
        if not isinstance(worker, dict):
            raise VerificationError("worker registry contains a malformed entry")
        worker_id = _bounded_string(worker.get("id"), "worker.id")
        if worker_id in index:
            raise VerificationError("worker registry contains duplicate ids")
        _bounded_string(worker.get("trust_domain"), f"trust_domain for {worker_id}")
        caps = worker.get("capabilities", [])
        if not isinstance(caps, list) or any(not isinstance(cap, str) or not cap for cap in caps):
            raise VerificationError(f"capabilities are malformed for {worker_id}")
        index[worker_id] = worker
    return index


def _verification_policy(task: dict[str, Any]) -> dict[str, Any]:
    policy = task.get("verification")
    if not isinstance(policy, dict) or set(policy) != {"mode", "required_capabilities"}:
        raise VerificationError("task verification policy is missing or malformed")
    mode = policy.get("mode")
    if mode not in {"independent_worker", "independent_trust_domain", "owner_required"}:
        raise VerificationError("task verification mode is unsupported")
    caps = policy.get("required_capabilities")
    if not isinstance(caps, list) or any(not isinstance(cap, str) or not cap for cap in caps):
        raise VerificationError("verification capabilities are malformed")
    return policy


def eligible_verifiers(config: dict[str, Any], task: dict[str, Any], producer_id: str) -> list[str]:
    policy = _verification_policy(task)
    if policy["mode"] == "owner_required":
        return []
    workers = _workers(config)
    producer = workers.get(producer_id)
    if producer is None:
        raise VerificationError("producer is absent from worker registry")
    producer_domain = producer["trust_domain"]
    needed = set(policy["required_capabilities"])
    authority = int(task.get("authority", 0))
    result: list[str] = []
    for worker_id, worker in workers.items():
        if worker_id == producer_id:
            continue
        if not bool(worker.get("enabled", True)) or not bool(worker.get("verifier", False)):
            continue
        worker_authority = worker.get("authority_max", 0)
        if isinstance(worker_authority, bool) or not isinstance(worker_authority, int) or worker_authority < authority:
            continue
        if not needed.issubset(set(worker.get("capabilities", []))):
            continue
        if policy["mode"] == "independent_trust_domain" and worker.get("trust_domain") == producer_domain:
            continue
        result.append(worker_id)
    return sorted(result)


def _current_ingested_attempt(task: dict[str, Any]) -> dict[str, Any]:
    active_id = task.get("active_attempt_id")
    history = task.get("attempt_history")
    if not isinstance(active_id, str) or not isinstance(history, list):
        raise VerificationError("task has no current attempt history")
    matches = [item for item in history if isinstance(item, dict) and item.get("attempt_id") == active_id]
    if len(matches) != 1:
        raise VerificationError("active attempt history is missing or ambiguous")
    current = matches[0]
    if current.get("status") != "INGESTED":
        raise VerificationError("producer result must be ingested before verification")
    return current


def _producer_subject(
    config: dict[str, Any],
    task: dict[str, Any],
    producer_result: dict[str, Any],
    artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    current = _current_ingested_attempt(task)
    workers = _workers(config)
    producer_id = current.get("worker_id")
    producer = workers.get(producer_id)
    if producer is None:
        raise VerificationError("producer is absent from worker registry")

    expected_result_digest = current.get("result_digest")
    actual_result_digest = _digest(producer_result, limit=attempts.MAX_RESULT_BYTES)
    if expected_result_digest != actual_result_digest:
        raise VerificationError("producer result does not match the ingested fenced result")
    if producer_result.get("attempt_id") != current.get("attempt_id"):
        raise VerificationError("producer result attempt identity is stale")
    if producer_result.get("fence_generation") != current.get("fence_generation"):
        raise VerificationError("producer result fence is stale")
    if producer_result.get("source_sha") != current.get("source_sha"):
        raise VerificationError("producer result source SHA is stale")
    if producer_result.get("spec_digest") != task.get("spec_digest"):
        raise VerificationError("producer result spec digest is stale")
    if producer_result.get("evidence") is None or not isinstance(producer_result.get("evidence"), dict):
        raise VerificationError("producer result evidence is malformed")
    evidence_digest = _digest(producer_result["evidence"], limit=attempts.MAX_RESULT_BYTES)
    if evidence_digest != current.get("evidence_digest"):
        raise VerificationError("producer evidence digest does not match ingested result")

    normalized_artifacts = _normalize_artifacts(artifacts)
    return {
        "mission_id": task.get("mission_id"),
        "mission_revision": task.get("mission_revision"),
        "task_id": task.get("id"),
        "spec_digest": _sha256(task.get("spec_digest"), "task spec_digest"),
        "policy_version": _bounded_string(task.get("policy_version"), "policy_version"),
        "attempt_id": current.get("attempt_id"),
        "attempt_number": current.get("attempt_number"),
        "fence_generation": current.get("fence_generation"),
        "source_sha": _sha256(current.get("source_sha"), "source_sha"),
        "producer": {
            "worker_id": producer_id,
            "trust_domain": _bounded_string(producer.get("trust_domain"), "producer trust_domain"),
            "result_digest": _sha256(expected_result_digest, "producer result_digest"),
            "evidence_digest": _sha256(evidence_digest, "producer evidence_digest"),
        },
        "artifacts": normalized_artifacts,
    }


def _normalize_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS:
        raise VerificationError("artifact manifest exceeds bounded count")
    normalized: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"kind", "name", "sha256"}:
            raise VerificationError("artifact manifest entry is malformed")
        kind = _bounded_string(artifact.get("kind"), "artifact kind", limit=64)
        name = _bounded_string(artifact.get("name"), "artifact name", limit=240)
        digest = _sha256(artifact.get("sha256"), "artifact sha256")
        identity = (kind, name)
        if identity in identities:
            raise VerificationError("artifact manifest contains duplicate identity")
        identities.add(identity)
        normalized.append({"kind": kind, "name": name, "sha256": digest})
    return sorted(normalized, key=lambda item: (item["kind"], item["name"], item["sha256"]))


def _normalize_checks(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(checks, list) or not checks or len(checks) > MAX_CHECKS:
        raise VerificationError("verification checks must be a non-empty bounded list")
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {"name", "passed", "evidence_sha256"}:
            raise VerificationError("verification check is malformed")
        name = _bounded_string(check.get("name"), "verification check name", limit=120)
        if name in names:
            raise VerificationError("verification check names must be unique")
        names.add(name)
        passed = check.get("passed")
        if not isinstance(passed, bool):
            raise VerificationError("verification check passed must be boolean")
        normalized.append(
            {"name": name, "passed": passed, "evidence_sha256": _sha256(check.get("evidence_sha256"), "check evidence_sha256")}
        )
    return sorted(normalized, key=lambda item: item["name"])


def build_verification_manifest(
    config: dict[str, Any],
    task: dict[str, Any],
    producer_result: dict[str, Any],
    *,
    verifier_id: str,
    checks: list[dict[str, Any]],
    artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    policy = _verification_policy(task)
    if policy["mode"] == "owner_required" or int(task.get("authority", 0)) >= 4:
        raise VerificationError("owner-required task cannot receive autonomous verification")
    subject = _producer_subject(config, task, producer_result, artifacts or [])
    producer_id = subject["producer"]["worker_id"]
    if verifier_id not in eligible_verifiers(config, task, producer_id):
        raise VerificationError("verifier does not satisfy independent verification policy")
    workers = _workers(config)
    normalized_checks = _normalize_checks(checks)
    subject_digest = _digest(subject)
    checks_digest = _digest(normalized_checks)
    decision = "pass" if all(check["passed"] for check in normalized_checks) else "fail"
    manifest = {
        "schema_version": VERIFICATION_SCHEMA,
        **subject,
        "subject_digest": subject_digest,
        "verification_mode": policy["mode"],
        "verifier": {
            "worker_id": verifier_id,
            "trust_domain": workers[verifier_id]["trust_domain"],
        },
        "checks": normalized_checks,
        "checks_digest": checks_digest,
        "decision": decision,
    }
    _digest(manifest)
    return manifest


def _validate_manifest(
    config: dict[str, Any],
    task: dict[str, Any],
    producer_result: dict[str, Any],
    manifest: dict[str, Any],
) -> str:
    if not isinstance(manifest, dict):
        raise VerificationError("verification manifest root must be an object")
    required = {
        "schema_version", "mission_id", "mission_revision", "task_id", "spec_digest", "policy_version",
        "attempt_id", "attempt_number", "fence_generation", "source_sha", "producer", "artifacts",
        "subject_digest", "verification_mode", "verifier", "checks", "checks_digest", "decision",
    }
    if set(manifest) != required or manifest.get("schema_version") != VERIFICATION_SCHEMA:
        raise VerificationError("verification manifest schema mismatch")
    if manifest.get("decision") not in {"pass", "fail"}:
        raise VerificationError("verification decision is invalid")

    subject = _producer_subject(config, task, producer_result, manifest.get("artifacts"))
    subject_fields = {
        key: manifest.get(key)
        for key in (
            "mission_id", "mission_revision", "task_id", "spec_digest", "policy_version", "attempt_id",
            "attempt_number", "fence_generation", "source_sha", "producer", "artifacts"
        )
    }
    if subject_fields != subject:
        raise VerificationError("verification subject fields do not match current fenced producer result")
    if manifest.get("subject_digest") != _digest(subject):
        raise VerificationError("verification subject digest mismatch")

    policy = _verification_policy(task)
    if manifest.get("verification_mode") != policy["mode"]:
        raise VerificationError("verification mode does not match task policy")
    verifier = manifest.get("verifier")
    if not isinstance(verifier, dict) or set(verifier) != {"worker_id", "trust_domain"}:
        raise VerificationError("verifier identity is malformed")
    producer_id = subject["producer"]["worker_id"]
    verifier_id = verifier.get("worker_id")
    if verifier_id not in eligible_verifiers(config, task, producer_id):
        raise VerificationError("verifier no longer satisfies verification policy")
    workers = _workers(config)
    if verifier.get("trust_domain") != workers[verifier_id]["trust_domain"]:
        raise VerificationError("verifier trust domain does not match registry")

    checks = _normalize_checks(manifest.get("checks"))
    if checks != manifest.get("checks"):
        raise VerificationError("verification checks are not canonical")
    if manifest.get("checks_digest") != _digest(checks):
        raise VerificationError("verification checks digest mismatch")
    expected_decision = "pass" if all(check["passed"] for check in checks) else "fail"
    if manifest.get("decision") != expected_decision:
        raise VerificationError("verification decision does not match check results")
    return _digest(manifest)


def accept_verification(
    config: dict[str, Any],
    task: dict[str, Any],
    producer_result: dict[str, Any],
    manifest: dict[str, Any],
) -> bool:
    manifest_digest = _validate_manifest(config, task, producer_result, manifest)
    prior = task.get("verification_evidence")
    if prior is not None:
        if isinstance(prior, dict) and prior.get("manifest_digest") == manifest_digest:
            return False
        raise VerificationConflict("task already has a different verification decision")

    task["verifier"] = manifest["verifier"]["worker_id"]
    task["verification_evidence"] = {
        "schema_version": VERIFICATION_SCHEMA,
        "manifest_digest": manifest_digest,
        "subject_digest": manifest["subject_digest"],
        "checks_digest": manifest["checks_digest"],
        "attempt_id": manifest["attempt_id"],
        "fence_generation": manifest["fence_generation"],
        "source_sha": manifest["source_sha"],
        "producer": deepcopy(manifest["producer"]),
        "verifier": deepcopy(manifest["verifier"]),
        "verification_mode": manifest["verification_mode"],
        "decision": manifest["decision"],
    }
    if manifest["decision"] == "pass":
        task["status"] = "DONE"
        task.pop("blocked_reason", None)
    else:
        task["status"] = "BLOCKED"
        task["blocked_reason"] = "independent_verification_failed"
    return True
