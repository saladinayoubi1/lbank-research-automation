"""Early physical receipt for exact-main recent Bybit archive, using stdlib only.

Heavy offline wheelhouse setup must not eat the recent transport deadline.
This receipt proves the ORIGINAL producer artifact reached the authorized
physical job within its 45-minute bound. Numeric and source-recency gates
still run later, against the actual later wall clock, after installation.
Never interpret archive recency as live market freshness or Paper authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from scripts import nexus_snapshot_artifact as snapshot

SCHEMA = "nexus.physical-recent-artifact-arrival.v1"
INNER = "nexus-multipair-runtime-requalification-snapshot.zip"
SIDECAR = "nexus-multipair-recent-runtime-snapshot.sha256"
MAX_ARRIVAL_AGE_MS = 45 * 60 * 1000
MAX_SOURCE_LAG_MS = 36 * 60 * 60 * 1000
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("recent arrival artifact must be an existing regular file")
    return snapshot._sha256_file(path)


def _manifest_from_inner(path: Path) -> dict[str, Any]:
    """Safe bounded extractor refuses malformed paths and oversized members."""
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="nexus-recent-arrival-manifest-") as tmp:
        dest = Path(tmp)
        snapshot._extract_inner(path, dest)
        file = dest / snapshot.MANIFEST_NAME
        if file.is_symlink() or not file.is_file():
            raise RuntimeError("recent arrival manifest is unavailable")
        manifest = json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("recent arrival manifest is invalid")
    return manifest


def _check_identity(
    manifest: dict[str, Any], *,
    source_sha: str, snapshot_digest: str,
    acquired_at_ms: int, data_as_of_ms: int,
) -> None:
    core = dict(manifest)
    signed = core.pop("snapshot_digest", None)
    if (
        not _SHA40.fullmatch(source_sha)
        or not _SHA64.fullmatch(snapshot_digest)
        or signed != snapshot_digest
        or hashlib.sha256(_canonical(core)).hexdigest() != signed
        or manifest.get("schema_version")
            != "nexus.multipair-runtime-requalification-recent-archive-snapshot.v1"
        or manifest.get("source_sha") != source_sha
        or manifest.get("acquired_at_ms") != acquired_at_ms
        or manifest.get("as_of_ms") != acquired_at_ms
        or manifest.get("data_as_of_ms") != data_as_of_ms
        or manifest.get("research_only") is not True
        or manifest.get("live_freshness_claimed") is not False
        or manifest.get("automatic_strategy_promotion") is not False
        or manifest.get("paper_execution_started") is not False
        or manifest.get("live_trading_authority") is not False
    ):
        raise RuntimeError("recent arrival source, signed digest or authority mismatch")


def _check_times(received_at_ms: int, acquired_at_ms: int, data_as_of_ms: int, now_ms: int) -> None:
    if (
        any(type(v) is not int or v <= 0 for v in (
            received_at_ms, acquired_at_ms, data_as_of_ms, now_ms
        ))
        or not 0 <= received_at_ms - acquired_at_ms <= MAX_ARRIVAL_AGE_MS
        or not 0 <= received_at_ms - data_as_of_ms <= MAX_SOURCE_LAG_MS
        or not received_at_ms <= now_ms
        or not 0 <= now_ms - data_as_of_ms <= MAX_SOURCE_LAG_MS
    ):
        raise RuntimeError("recent arrival transport deadline or actual source recency rejected")


def stage(
    *, repository: str, run_id: str, artifact_name: str, source_sha: str,
    expected_sha256: str, expected_snapshot_digest: str,
    expected_acquired_at_ms: int, expected_data_as_of_ms: int,
    destination: Path, token: str,
) -> dict[str, Any]:
    from scripts import nexus_public_current_run_artifact as transport
    dest = destination.resolve()
    if dest.exists():
        raise RuntimeError("physical recent arrival stage must be new and isolated")
    dest.mkdir(parents=True)
    artifact = transport._artifact(repository, run_id, artifact_name, source_sha, token)
    outer = dest / "artifact.zip"
    transport._download_outer(repository, artifact, outer, token)
    files = transport._extract_exact_outer(outer, dest / "outer", {INNER, SIDECAR})
    transport._read_digest(files[SIDECAR], expected_sha256)
    if _hash_file(files[INNER]) != expected_sha256:
        raise RuntimeError("recent physical arrival archive SHA mismatch")
    manifest = _manifest_from_inner(files[INNER])
    _check_identity(
        manifest, source_sha=source_sha, snapshot_digest=expected_snapshot_digest,
        acquired_at_ms=expected_acquired_at_ms, data_as_of_ms=expected_data_as_of_ms,
    )
    received_at_ms = int(time.time() * 1000)
    _check_times(received_at_ms, expected_acquired_at_ms, expected_data_as_of_ms, received_at_ms)
    core = {
        "schema": SCHEMA, "repository": repository, "run_id": str(run_id),
        "artifact_id": int(artifact["id"]), "source_sha": source_sha,
        "archive_sha256": expected_sha256, "snapshot_digest": expected_snapshot_digest,
        "acquired_at_ms": expected_acquired_at_ms,
        "data_as_of_ms": expected_data_as_of_ms,
        "received_at_ms": received_at_ms,
        "research_only": True, "automatic_strategy_promotion": False,
        "live_enabled": False,
    }
    value = {**core, "receipt_digest": hashlib.sha256(_canonical(core)).hexdigest()}
    (dest / "arrival-receipt.json").write_bytes(_canonical(value) + b"\n")
    return value


def verify_stage(
    root: Path, *,
    repository: str, run_id: str, source_sha: str,
    expected_sha256: str, expected_snapshot_digest: str,
    expected_acquired_at_ms: int, expected_data_as_of_ms: int,
    now_ms: int,
) -> tuple[dict[str, Any], Path]:
    base = root.resolve()
    receipt_path = base / "arrival-receipt.json"
    try:
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise RuntimeError("missing regular recent arrival receipt")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        core = dict(receipt)
        claim = core.pop("receipt_digest")
        if (
            receipt.get("schema") != SCHEMA
            or not _SHA64.fullmatch(str(claim))
            or hashlib.sha256(_canonical(core)).hexdigest() != claim
            or receipt.get("repository") != repository
            or receipt.get("run_id") != str(run_id)
            or receipt.get("source_sha") != source_sha
            or receipt.get("archive_sha256") != expected_sha256
            or receipt.get("snapshot_digest") != expected_snapshot_digest
            or receipt.get("acquired_at_ms") != expected_acquired_at_ms
            or receipt.get("data_as_of_ms") != expected_data_as_of_ms
            or type(receipt.get("artifact_id")) is not int
            or receipt["artifact_id"] <= 0
            or receipt.get("research_only") is not True
            or receipt.get("automatic_strategy_promotion") is not False
            or receipt.get("live_enabled") is not False
        ):
            raise RuntimeError("physical arrival receipt source/identity mismatch")
        received = receipt["received_at_ms"]
        _check_times(received, expected_acquired_at_ms, expected_data_as_of_ms, now_ms)
        sidecar = base / "outer" / SIDECAR
        inner = base / "outer" / INNER
        if sidecar.is_symlink() or sidecar.read_text(encoding="ascii").strip() != expected_sha256:
            raise RuntimeError("physical arrival sidecar mismatch")
        if _hash_file(inner) != expected_sha256:
            raise RuntimeError("physical arrival archived bytes changed")
        manifest = _manifest_from_inner(inner)
        _check_identity(
            manifest, source_sha=source_sha, snapshot_digest=expected_snapshot_digest,
            acquired_at_ms=expected_acquired_at_ms, data_as_of_ms=expected_data_as_of_ms,
        )
        return receipt, inner
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("physical recent arrival receipt rejected") from exc
