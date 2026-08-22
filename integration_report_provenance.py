"""Canonical provenance envelopes for untrusted dashboard integration reports."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import os
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

ENVELOPE_SCHEMA = "nexus.integration-report-envelope.v1"
POLICY_VERSION = "nexus.integration-report-policy.v1"
MAX_REPORT_BYTES = 262_144
MAX_REPORT_AGE = timedelta(hours=24)
MAX_CLOCK_SKEW = timedelta(minutes=5)
TRUSTED_PRODUCERS = {
    "zotero": "nexus.tools.zotero-metadata-audit.v2",
    "research": "nexus.tools.research-evidence-validator.v1",
}
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_RUN = re.compile(r"^(?:local-[0-9a-f]{12}|github-[1-9][0-9]{0,19})$")


class ProvenanceError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProvenanceError("report is not canonical JSON") from exc


def report_digest(report: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(report)).hexdigest()


def build_envelope(*, kind: str, report: Mapping[str, Any], source_commit: str,
                   workflow_run: str, generated_at: str) -> dict[str, Any]:
    if kind not in TRUSTED_PRODUCERS:
        raise ProvenanceError("unsupported report kind")
    return {
        "schema": ENVELOPE_SCHEMA,
        "kind": kind,
        "policy_version": POLICY_VERSION,
        "producer": TRUSTED_PRODUCERS[kind],
        "source_commit": source_commit,
        "workflow_run": workflow_run,
        "generated_at": generated_at,
        "report_sha256": report_digest(report),
        "report": dict(report),
    }


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise ProvenanceError("invalid generated_at")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProvenanceError("invalid generated_at") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProvenanceError("generated_at must be UTC")
    return parsed


def trusted_source_commit(root: str | None = None) -> str:
    configured = os.environ.get("NEXUS_SOURCE_COMMIT")
    if configured:
        if not _SHA1.fullmatch(configured):
            raise ProvenanceError("invalid trusted source commit")
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ProvenanceError("trusted source commit unavailable") from exc
    commit = result.stdout.strip()
    if not _SHA1.fullmatch(commit):
        raise ProvenanceError("invalid trusted source commit")
    return commit


def _bounded_tree(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> None:
    if budget is None:
        budget = [50_000]
    budget[0] -= 1
    if budget[0] < 0 or depth > 12:
        raise ProvenanceError("report structure exceeds bounds")
    if isinstance(value, str):
        if len(value) > 4096:
            raise ProvenanceError("report string exceeds bounds")
    elif isinstance(value, list):
        if len(value) > 10_000:
            raise ProvenanceError("report list exceeds bounds")
        for item in value:
            _bounded_tree(item, depth=depth + 1, budget=budget)
    elif isinstance(value, dict):
        if len(value) > 100:
            raise ProvenanceError("report field count exceeds bounds")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 120:
                raise ProvenanceError("report key exceeds bounds")
            _bounded_tree(item, depth=depth + 1, budget=budget)


def validate_envelope(value: Any, *, kind: str, now: datetime | None = None,
                      expected_source_commit: str | None = None) -> dict[str, Any]:
    keys = {"schema", "kind", "policy_version", "producer", "source_commit", "workflow_run", "generated_at", "report_sha256", "report"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ProvenanceError("provenance envelope schema mismatch")
    if value["schema"] != ENVELOPE_SCHEMA or value["policy_version"] != POLICY_VERSION:
        raise ProvenanceError("unsupported provenance policy")
    if value["kind"] != kind or value["producer"] != TRUSTED_PRODUCERS.get(kind):
        raise ProvenanceError("untrusted report producer")
    if not isinstance(value["source_commit"], str) or not _SHA1.fullmatch(value["source_commit"]):
        raise ProvenanceError("invalid source commit")
    trusted_commit = expected_source_commit or trusted_source_commit()
    if value["source_commit"] != trusted_commit:
        raise ProvenanceError("source commit mismatch")
    if not isinstance(value["workflow_run"], str) or not _RUN.fullmatch(value["workflow_run"]):
        raise ProvenanceError("invalid workflow run")
    if value["workflow_run"].startswith("local-") and value["workflow_run"] != f"local-{trusted_commit[:12]}":
        raise ProvenanceError("local workflow binding mismatch")
    configured_run = os.environ.get("NEXUS_EXPECTED_WORKFLOW_RUN")
    if configured_run and value["workflow_run"] != configured_run:
        raise ProvenanceError("workflow run mismatch")
    generated = _utc(value["generated_at"])
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if generated > current + MAX_CLOCK_SKEW or current - generated > MAX_REPORT_AGE:
        raise ProvenanceError("integration report is stale or future-dated")
    report = value["report"]
    if not isinstance(report, dict) or not isinstance(value["report_sha256"], str):
        raise ProvenanceError("invalid bound report")
    _bounded_tree(report)
    if not hmac.compare_digest(value["report_sha256"], report_digest(report)):
        raise ProvenanceError("report digest mismatch")
    return report
