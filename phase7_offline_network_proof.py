from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "nexus.phase7-offline-network-proof.v1"
OBSERVATION_METHOD = "bounded_tcp_connect_dual_target_v1"
MAX_BYTES = 256_000


class OfflineNetworkProofError(ValueError):
    pass


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise OfflineNetworkProofError("offline network proof is unavailable") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise OfflineNetworkProofError("offline network proof size is outside bounds")
    try:
        # Windows PowerShell 5.1's `Set-Content -Encoding UTF8` writes a UTF-8
        # BOM. Accept that representation without weakening the JSON/schema
        # validation that follows.
        value = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfflineNetworkProofError("offline network proof JSON is invalid") from exc
    if not isinstance(value, dict):
        raise OfflineNetworkProofError("offline network proof root must be an object")
    return value


def _time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise OfflineNetworkProofError(f"{field} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfflineNetworkProofError(f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise OfflineNetworkProofError(f"{field} must be timezone-aware")
    return parsed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_offline_network_proof(
    proof_path: Path,
    returned_result: Path,
    *,
    expected_source_sha: str,
    expected_session_id: str | None = None,
) -> dict[str, Any]:
    proof = _read(Path(proof_path))
    required = {
        "schema_version", "session_id", "source_sha", "prepared_at", "boot_time_utc",
        "reboot_after_prepare", "pre_execution", "execution_started_at", "execution_finished_at",
        "post_execution", "result_sha256", "observation_method",
    }
    if set(proof) != required or proof.get("schema_version") != SCHEMA:
        raise OfflineNetworkProofError("offline network proof schema mismatch")
    if proof.get("source_sha") != expected_source_sha.lower():
        raise OfflineNetworkProofError("offline network proof source SHA mismatch")
    if expected_session_id is not None and proof.get("session_id") != expected_session_id:
        raise OfflineNetworkProofError("offline network proof session mismatch")

    prepared = _time(proof.get("prepared_at"), "prepared_at")
    boot = _time(proof.get("boot_time_utc"), "boot_time_utc")
    started = _time(proof.get("execution_started_at"), "execution_started_at")
    finished = _time(proof.get("execution_finished_at"), "execution_finished_at")
    if proof.get("reboot_after_prepare") is not True or boot <= prepared:
        raise OfflineNetworkProofError("offline execution does not prove a reboot after preparation")
    if not (boot <= started <= finished):
        raise OfflineNetworkProofError("offline execution timestamps are inconsistent")
    if proof.get("observation_method") != OBSERVATION_METHOD:
        raise OfflineNetworkProofError("offline observation method mismatch")

    observations: dict[str, Any] = {}
    for name in ("pre_execution", "post_execution"):
        observation = proof.get(name)
        if not isinstance(observation, Mapping) or observation.get("internet_unavailable") is not True:
            raise OfflineNetworkProofError(f"{name} does not prove unavailable internet")
        checked_at = _time(observation.get("checked_at"), f"{name}.checked_at")
        if name == "pre_execution" and not (boot <= checked_at <= started):
            raise OfflineNetworkProofError("pre-execution network observation is outside the offline execution window")
        if name == "post_execution" and checked_at < finished:
            raise OfflineNetworkProofError("post-execution network observation predates execution completion")
        targets = observation.get("targets")
        if not isinstance(targets, list) or len(targets) != 2:
            raise OfflineNetworkProofError(f"{name} must contain exactly two external target observations")
        seen: set[tuple[str, int]] = set()
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"host", "port", "reachable", "error"}:
                raise OfflineNetworkProofError(f"{name} target schema mismatch")
            host = target.get("host")
            port = target.get("port")
            if not isinstance(host, str) or not host or isinstance(port, bool) or not isinstance(port, int) or port <= 0:
                raise OfflineNetworkProofError(f"{name} target identity is invalid")
            identity = (host, port)
            if identity in seen:
                raise OfflineNetworkProofError(f"{name} target observations must be independent")
            seen.add(identity)
            if target.get("reachable") is not False:
                raise OfflineNetworkProofError(f"{name} observed reachable external network")
            if not isinstance(target.get("error"), str):
                raise OfflineNetworkProofError(f"{name} target error evidence is invalid")
        observations[name] = {"checked_at": observation["checked_at"], "targets": [dict(row) for row in targets]}

    actual_result_sha = sha256_file(Path(returned_result))
    if proof.get("result_sha256") != actual_result_sha:
        raise OfflineNetworkProofError("offline network proof is not bound to returned laptop result")
    return {
        "schema_version": SCHEMA,
        "session_id": proof["session_id"],
        "source_sha": proof["source_sha"],
        "prepared_at": proof["prepared_at"],
        "boot_time_utc": proof["boot_time_utc"],
        "reboot_after_prepare": True,
        "execution_started_at": proof["execution_started_at"],
        "execution_finished_at": proof["execution_finished_at"],
        "observation_method": OBSERVATION_METHOD,
        "internet_unavailable_pre": True,
        "internet_unavailable_post": True,
        "result_sha256": actual_result_sha,
        "proof_sha256": sha256_file(Path(proof_path)),
        "observations": observations,
    }
