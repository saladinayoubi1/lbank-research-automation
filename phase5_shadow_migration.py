from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

SHADOW_SCHEMA = "nexus.phase5-shadow-migration.v1"
CHAOS_CASES = (
    "restart",
    "stale_lease",
    "duplicate_callback",
    "corrupted_state",
    "provider_outage",
    "github_outage",
    "windows_offline_reconnect",
    "partial_evidence_failure",
)


class ShadowMigrationError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ShadowMigrationError("shadow evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def build_shadow_report(
    legacy_decision: Mapping[str, Any],
    durable_decision: Mapping[str, Any],
    chaos_results: Mapping[str, Any],
    *,
    intentional_differences: list[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(legacy_decision, Mapping) or not isinstance(durable_decision, Mapping):
        raise ShadowMigrationError("shadow decisions must be mappings")
    if not isinstance(chaos_results, Mapping) or set(chaos_results) != set(CHAOS_CASES):
        raise ShadowMigrationError("chaos result schema mismatch")
    if any(not isinstance(chaos_results[name], bool) for name in CHAOS_CASES):
        raise ShadowMigrationError("chaos results must be boolean")
    differences = intentional_differences or []
    if not isinstance(differences, list) or len(differences) > 32 or any(not isinstance(item, str) or not item or len(item) > 240 for item in differences):
        raise ShadowMigrationError("intentional differences must be a bounded string list")

    legacy = dict(legacy_decision)
    durable = dict(durable_decision)
    exact_parity = legacy == durable
    parity_accepted = exact_parity or bool(differences)
    chaos = {name: bool(chaos_results[name]) for name in CHAOS_CASES}
    cutover_ready = parity_accepted and all(chaos.values())
    core = {
        "schema_version": SHADOW_SCHEMA,
        "paper_only": True,
        "legacy_mode": "watchdog_fallback",
        "durable_supervisor_mode": "canonical_phase5",
        "legacy_decision_digest": _digest(legacy),
        "durable_decision_digest": _digest(durable),
        "exact_parity": exact_parity,
        "intentional_differences": list(differences),
        "parity_accepted": parity_accepted,
        "chaos": chaos,
        "cutover_ready": cutover_ready,
        "live_execution_allowed": False,
    }
    return {**core, "report_digest": _digest(core)}


def validate_shadow_report(report: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise ShadowMigrationError("shadow report must be a mapping")
    required = {
        "schema_version", "paper_only", "legacy_mode", "durable_supervisor_mode",
        "legacy_decision_digest", "durable_decision_digest", "exact_parity",
        "intentional_differences", "parity_accepted", "chaos", "cutover_ready",
        "live_execution_allowed", "report_digest",
    }
    if set(report) != required or report.get("schema_version") != SHADOW_SCHEMA:
        raise ShadowMigrationError("shadow report schema mismatch")
    if report.get("paper_only") is not True or report.get("live_execution_allowed") is not False:
        raise ShadowMigrationError("shadow report widened authority")
    if report.get("legacy_mode") != "watchdog_fallback" or report.get("durable_supervisor_mode") != "canonical_phase5":
        raise ShadowMigrationError("cutover roles are invalid")
    chaos = report.get("chaos")
    if not isinstance(chaos, Mapping) or set(chaos) != set(CHAOS_CASES) or any(not isinstance(chaos[name], bool) for name in CHAOS_CASES):
        raise ShadowMigrationError("shadow chaos evidence is malformed")
    expected_ready = bool(report.get("parity_accepted")) and all(chaos.values())
    if report.get("cutover_ready") is not expected_ready:
        raise ShadowMigrationError("cutover readiness does not match parity/chaos evidence")
    core = dict(report)
    claimed = core.pop("report_digest")
    if not isinstance(claimed, str) or len(claimed) != 64 or _digest(core) != claimed:
        raise ShadowMigrationError("shadow report digest mismatch")
    return dict(report)
