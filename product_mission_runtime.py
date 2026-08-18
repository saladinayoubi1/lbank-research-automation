from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from dashboard_integrations import IntegrationUnavailableError, load_research_summary, load_zotero_summary

MISSION_CONTRACT = "nexus.product-mission-control.v1"
SNAPSHOT_CONTRACT = "nexus.agent-manager-snapshot.v1"
STRATEGY_CONTRACT = "nexus.product-strategy-center.v1"
CI_CONTRACT = "nexus.product-ci-health.v1"
MAX_SNAPSHOT_BYTES = 2_000_000
MAX_EVENTS = 200
MAX_STRATEGY_RUNS = 200
MAX_ROUTING_CANDIDATES = 32
MAX_WAIT_ROWS = 32
ACTIVE_STATES = {"LEASED", "RUNNING", "VERIFYING", "TRIAGE"}
KNOWN_STATES = {
    "PENDING", "READY", "LEASED", "RUNNING", "VERIFYING", "DONE", "TRIAGE",
    "BLOCKED", "OWNER_REQUIRED", "QUARANTINED",
}
WAIT_STATES = {"WAITING_EXTERNAL", "COMPLETED"}


class ProductMissionError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ProductMissionError(f"cannot read {path.name}") from exc
    if len(raw) <= 1 or len(raw) > MAX_SNAPSHOT_BYTES:
        raise ProductMissionError(f"unsafe or oversized {path.name}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductMissionError(f"invalid JSON in {path.name}") from exc
    if not isinstance(payload, dict):
        raise ProductMissionError(f"{path.name} root must be an object")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ProductMissionError("mission snapshot exceeds bounded size")
    fd, tmp_name = tempfile.mkstemp(prefix=".nexus-mission-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        Path(tmp_name).replace(path)
    finally:
        try:
            Path(tmp_name).unlink(missing_ok=True)
        except OSError:
            pass


def _bounded_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ProductMissionError("agent event ledger is unsafe")
    events: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    events.append(value)
                    if len(events) > MAX_EVENTS:
                        events.pop(0)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductMissionError("agent event ledger is invalid") from exc
    return events


def _bounded_text(value: Any, *, limit: int = 200) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    return value


def _bounded_text_list(value: Any, *, limit: int = 32, item_limit: int = 160) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value[:limit]:
        text = _bounded_text(item, limit=item_limit)
        if text is not None:
            result.append(text)
    return result


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return value


def _observed_routing_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    if isinstance(value.get("available"), bool):
        result["available"] = value["available"]
    for key in ("health_score", "latency_ms", "failure_rate", "cost_units", "queue_depth", "capacity"):
        number = _finite_number(value.get(key))
        if number is not None:
            result[key] = number
    result["data_locality"] = _bounded_text_list(value.get("data_locality"), limit=16)
    result["trust_domains"] = _bounded_text_list(value.get("trust_domains"), limit=16)
    return result


def _routing_decision_view(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, Any] = {
        "evaluated_at": _bounded_text(value.get("evaluated_at")),
        "selected_worker": _bounded_text(value.get("selected_worker")),
        "reason": _bounded_text(value.get("reason")),
    }
    selected_score = _finite_number(value.get("selected_score"))
    if selected_score is not None:
        result["selected_score"] = selected_score
    candidates: list[dict[str, Any]] = []
    raw_candidates = value.get("candidates")
    if isinstance(raw_candidates, list):
        for raw in raw_candidates[:MAX_ROUTING_CANDIDATES]:
            if not isinstance(raw, Mapping):
                continue
            worker_id = _bounded_text(raw.get("worker_id"))
            if worker_id is None:
                continue
            row: dict[str, Any] = {
                "worker_id": worker_id,
                "eligible": raw.get("eligible") is True,
                "rejection_reasons": _bounded_text_list(raw.get("rejection_reasons"), limit=16),
                "selection_reason": _bounded_text(raw.get("selection_reason")),
                "observed": _observed_routing_view(raw.get("observed")),
            }
            score = _finite_number(raw.get("score"))
            if score is not None:
                row["score"] = score
            components = raw.get("components")
            if isinstance(components, Mapping):
                safe_components: dict[str, Any] = {}
                for key in (
                    "health", "latency", "failure_rate", "cost", "queue_depth",
                    "preferred_resource", "data_locality", "trust_domain", "remaining_capacity",
                ):
                    number = _finite_number(components.get(key))
                    if number is not None:
                        safe_components[key] = number
                row["components"] = safe_components
            candidates.append(row)
    result["candidates"] = candidates
    return result


def _wait_timeline_view(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for raw in value[-MAX_WAIT_ROWS:]:
        if not isinstance(raw, Mapping):
            continue
        row = {
            key: _bounded_text(raw.get(key))
            for key in (
                "started_at", "from_status", "dispatch_id", "worker_id", "transport",
                "completed_at", "outcome",
            )
        }
        result.append({key: item for key, item in row.items() if item is not None})
    return result


def _zero_idle_view(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    overlaps: list[dict[str, Any]] = []
    raw_overlaps = value.get("overlapped_external_waits")
    if isinstance(raw_overlaps, list):
        for raw in raw_overlaps[:MAX_WAIT_ROWS]:
            if not isinstance(raw, Mapping):
                continue
            row = {
                key: _bounded_text(raw.get(key))
                for key in ("task_id", "worker_id", "wait_started_at", "dispatch_id")
            }
            clean = {key: item for key, item in row.items() if item is not None}
            if clean.get("task_id"):
                overlaps.append(clean)
    return {
        "leased_at": _bounded_text(value.get("leased_at")),
        "rule": _bounded_text(value.get("rule")),
        "overlapped_external_waits": overlaps,
    }


def _task_view(task: Mapping[str, Any]) -> dict[str, Any]:
    status = str(task.get("status") or "PENDING").upper()
    if status not in KNOWN_STATES:
        status = "BLOCKED"
    external_wait_state = str(task.get("external_wait_state") or "").upper()
    if external_wait_state not in WAIT_STATES:
        external_wait_state = None
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "phase": task.get("phase"),
        "gate": task.get("gate"),
        "status": status,
        "priority": task.get("priority"),
        "authority": task.get("authority"),
        "dependencies": list(task.get("dependencies") or []),
        "required_capabilities": list(task.get("required_capabilities") or []),
        "preferred_resources": list(task.get("preferred_resources") or []),
        "assigned_worker": task.get("assigned_worker"),
        "producer": task.get("producer"),
        "verifier": task.get("verifier"),
        "attempt": int(task.get("attempt") or 0),
        "transient_retries": int(task.get("transient_retries") or 0),
        "lease_id": _bounded_text(task.get("lease_id")),
        "fence_generation": task.get("fence_generation") if isinstance(task.get("fence_generation"), int) and not isinstance(task.get("fence_generation"), bool) else None,
        "active_attempt_id": _bounded_text(task.get("active_attempt_id")),
        "correlation_id": _bounded_text(task.get("correlation_id")),
        "dispatch_id": _bounded_text(task.get("dispatch_id")),
        "leased_at": task.get("leased_at"),
        "heartbeat_at": task.get("heartbeat_at"),
        "lease_expires_at": task.get("lease_expires_at"),
        "triage_reason": task.get("triage_reason"),
        "triage_mode": task.get("triage_mode"),
        "failure_class": task.get("failure_class"),
        "blocked_reason": task.get("blocked_reason"),
        "dispatch_transport": task.get("dispatch_transport"),
        "dispatched_at": task.get("dispatched_at"),
        "verified_at": task.get("verified_at"),
        "acceptance": list(task.get("acceptance") or []),
        "result_evidence": task.get("result_evidence"),
        "verification_evidence": task.get("verification_evidence"),
        "failure_evidence": task.get("failure_evidence"),
        "routing_decision": _routing_decision_view(task.get("routing_decision")),
        "waiting_from_status": _bounded_text(task.get("waiting_from_status")),
        "external_wait_state": external_wait_state,
        "external_wait_started_at": _bounded_text(task.get("external_wait_started_at")),
        "external_wait_completed_at": _bounded_text(task.get("external_wait_completed_at")),
        "external_wait_timeline": _wait_timeline_view(task.get("external_wait_timeline")),
        "zero_idle_evidence": _zero_idle_view(task.get("zero_idle_evidence")),
    }


def _worker_views(config: Mapping[str, Any], tasks: list[dict[str, Any]], *, runtime_present: bool, runtime: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    runtime_metrics = runtime.get("resource_metrics") if isinstance(runtime, Mapping) and isinstance(runtime.get("resource_metrics"), Mapping) else {}
    for raw in config.get("workers", []):
        if not isinstance(raw, Mapping):
            continue
        worker_id = str(raw.get("id") or "")
        assigned = [task for task in tasks if task.get("assigned_worker") == worker_id]
        active = [task for task in assigned if task["status"] in ACTIVE_STATES]
        if not raw.get("enabled", True):
            state = "DISABLED"
        elif active:
            state = "BUSY"
        elif runtime_present:
            state = "IDLE"
        else:
            state = "UNKNOWN"
        static_routing = raw.get("routing") if isinstance(raw.get("routing"), Mapping) else {}
        observed = runtime_metrics.get(worker_id) if isinstance(runtime_metrics, Mapping) and isinstance(runtime_metrics.get(worker_id), Mapping) else {}
        merged_routing = {**static_routing, **observed}
        result.append({
            "id": worker_id,
            "state": state,
            "enabled": bool(raw.get("enabled", True)),
            "verifier": bool(raw.get("verifier", False)),
            "authority_max": int(raw.get("authority_max") or 0),
            "capabilities": list(raw.get("capabilities") or []),
            "resources": list(raw.get("resources") or []),
            "max_concurrent_tasks": int(raw.get("max_concurrent_tasks") or 1),
            "active_tasks": [task["id"] for task in active],
            "assigned_tasks": [task["id"] for task in assigned],
            "routing_metrics": _observed_routing_view(merged_routing) if runtime_present else {},
        })
    return result


def _resource_views(workers: list[dict[str, Any]], tasks: list[dict[str, Any]], *, snapshot_age_seconds: float | None) -> list[dict[str, Any]]:
    names = sorted({resource for worker in workers for resource in worker["resources"]})
    result: list[dict[str, Any]] = []
    for name in names:
        members = [worker for worker in workers if name in worker["resources"]]
        active = [worker for worker in members if worker["state"] == "BUSY"]
        if active:
            state = "ACTIVE"
        elif snapshot_age_seconds is None:
            state = "UNKNOWN"
        elif snapshot_age_seconds > 900:
            state = "STALE"
        else:
            state = "IDLE_OR_AVAILABLE"
        routed = [task["id"] for task in tasks if name in task["preferred_resources"] and task["status"] in ACTIVE_STATES]
        result.append({
            "id": name,
            "state": state,
            "workers": [worker["id"] for worker in members],
            "active_workers": [worker["id"] for worker in active],
            "routed_tasks": routed,
        })
    return result


def _snapshot_age(generated_at: Any) -> float | None:
    parsed = _parse_time(generated_at)
    if parsed is None:
        return None
    delta = (datetime.now(timezone.utc) - parsed).total_seconds()
    if delta < -300:
        return None
    return max(0.0, delta)


def _latest_ci(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("kind") != "ci_snapshot" or not isinstance(event.get("payload"), Mapping):
            continue
        payload = event["payload"]
        workflows_raw = payload.get("workflows")
        summary_raw = payload.get("summary")
        if not isinstance(workflows_raw, Mapping) or not isinstance(summary_raw, Mapping):
            continue
        workflows: dict[str, Any] = {}
        exact_heads: set[str] = set()
        for name, raw in workflows_raw.items():
            if not isinstance(name, str) or not isinstance(raw, Mapping):
                continue
            head_sha = raw.get("head_sha")
            if isinstance(head_sha, str) and head_sha:
                exact_heads.add(head_sha)
            workflows[name] = {
                key: raw.get(key) for key in (
                    "state", "run_id", "run_attempt", "conclusion", "status",
                    "head_sha", "updated_at", "url", "auto_retry",
                )
            }
        counts = {key: int(summary_raw.get(key) or 0) for key in ("RUNNING", "WAITING", "DONE", "FAILED", "BLOCKED", "UNKNOWN")}
        state = "FAILED" if counts["FAILED"] or counts["BLOCKED"] else ("RUNNING" if counts["RUNNING"] or counts["WAITING"] else "DONE")
        return {
            "contract_version": CI_CONTRACT,
            "status": "available",
            "state": state,
            "generated_at": event.get("at"),
            "summary": counts,
            "workflows": workflows,
            "head_shas": sorted(exact_heads),
            "single_exact_head": len(exact_heads) == 1,
        }
    return {
        "contract_version": CI_CONTRACT,
        "status": "unavailable",
        "state": "UNKNOWN",
        "generated_at": None,
        "summary": {key: 0 for key in ("RUNNING", "WAITING", "DONE", "FAILED", "BLOCKED", "UNKNOWN")},
        "workflows": {},
        "head_shas": [],
        "single_exact_head": False,
    }


def _metric(evidence: Mapping[str, Any], key: str, missing: float) -> float:
    value = evidence.get(key)
    if value is None or isinstance(value, bool):
        return missing
    try:
        number = float(value)
    except (TypeError, ValueError):
        return missing
    return number


class StrategyEvidenceStore:
    def __init__(self, root: Path) -> None:
        self.path = Path(root) / "product_runtime" / "research-history.jsonl"

    def _load_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if not self.path.exists():
            return runs
        if self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > MAX_SNAPSHOT_BYTES * 4:
            raise ProductMissionError("research history is unsafe")
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if isinstance(value, dict):
                        runs.append(value)
                        if len(runs) > MAX_STRATEGY_RUNS:
                            runs.pop(0)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductMissionError("research history is invalid") from exc
        return runs

    def record(self, result: Mapping[str, Any]) -> None:
        public = {key: value for key, value in result.items() if not str(key).startswith("_")}
        record = {"recorded_at": _utc_now(), **public}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = self._load_runs()
        existing.append(record)
        existing = existing[-MAX_STRATEGY_RUNS:]
        temp = self.path.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                for row in existing:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(self.path)
        except OSError as exc:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            raise ProductMissionError("failed to persist research evidence") from exc

    def history(self) -> dict[str, Any]:
        runs = self._load_runs()
        candidates = [
            row for row in runs
            if isinstance(row.get("qualification"), Mapping)
            and row["qualification"].get("status") == "paper_candidate"
        ]

        def score(row: Mapping[str, Any]) -> tuple[float, float, float, float]:
            evidence = row.get("evidence") if isinstance(row.get("evidence"), Mapping) else {}
            return (
                _metric(evidence, "oos_score", -999.0),
                _metric(evidence, "walk_forward_score", -999.0),
                _metric(evidence, "robustness_score", -999.0),
                -_metric(evidence, "max_drawdown_pct", 999.0),
            )

        candidates.sort(key=score, reverse=True)
        leader = candidates[0] if candidates else None
        return {
            "contract_version": STRATEGY_CONTRACT,
            "paper_only": True,
            "profitability_claim": False,
            "ranking_rule": "paper_candidate first; then OOS, walk-forward, robustness, lower drawdown",
            "run_count": len(runs),
            "candidate_count": len(candidates),
            "leading_candidate": leader,
            "runs": runs[-50:],
        }


class ProductMissionRuntime:
    def __init__(self, root: Path, *, config_path: Path | None = None, integration_root: Path | None = None) -> None:
        self.root = Path(root)
        self.agent_root = self.root / "agent_coordination"
        self.runtime_path = self.agent_root / "agent_manager_runtime.json"
        self.summary_path = self.agent_root / "manager_state.json"
        self.event_path = self.agent_root / "manager_events.jsonl"
        self.import_path = self.agent_root / "imported_mission_snapshot.json"
        configured = config_path or Path(os.environ.get("NEXUS_AGENT_MANAGER_CONFIG", "config/nexus-agent-manager.json"))
        self.config_path = Path(configured)
        self.integration_root = Path(integration_root or self.root)
        self.strategy_store = StrategyEvidenceStore(self.root)

    def _config(self) -> dict[str, Any]:
        payload = _read_json(self.config_path)
        if payload is None or payload.get("schema_version") != 1 or not isinstance(payload.get("workers"), list) or not isinstance(payload.get("tasks"), list):
            raise ProductMissionError("agent-manager configuration unavailable or invalid")
        return payload

    def export_snapshot(self) -> dict[str, Any]:
        return {
            "contract_version": SNAPSHOT_CONTRACT,
            "generated_at": _utc_now(),
            "source": "local-agent-manager",
            "config": self._config(),
            "runtime": _read_json(self.runtime_path),
            "summary": _read_json(self.summary_path),
            "events": _bounded_events(self.event_path),
            "paper_only": True,
            "live_trading_authority": False,
        }

    def import_snapshot(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or payload.get("contract_version") != SNAPSHOT_CONTRACT:
            raise ProductMissionError("mission snapshot contract mismatch")
        required = {"contract_version", "generated_at", "source", "config", "runtime", "summary", "events", "paper_only", "live_trading_authority"}
        if set(payload) != required:
            raise ProductMissionError("mission snapshot schema mismatch")
        if payload.get("paper_only") is not True or payload.get("live_trading_authority") is not False:
            raise ProductMissionError("mission snapshot widened authority")
        if _parse_time(payload.get("generated_at")) is None:
            raise ProductMissionError("mission snapshot generated_at invalid")
        source = payload.get("source")
        if not isinstance(source, str) or not 1 <= len(source) <= 120:
            raise ProductMissionError("mission snapshot source invalid")
        config = payload.get("config")
        if not isinstance(config, Mapping) or config.get("schema_version") != 1 or not isinstance(config.get("workers"), list) or not isinstance(config.get("tasks"), list):
            raise ProductMissionError("mission snapshot configuration invalid")
        runtime = payload.get("runtime")
        if runtime is not None and (not isinstance(runtime, Mapping) or runtime.get("schema_version") != 1):
            raise ProductMissionError("mission snapshot runtime invalid")
        summary = payload.get("summary")
        if summary is not None and not isinstance(summary, Mapping):
            raise ProductMissionError("mission snapshot summary invalid")
        events = payload.get("events")
        if not isinstance(events, list) or len(events) > MAX_EVENTS or any(not isinstance(row, Mapping) for row in events):
            raise ProductMissionError("mission snapshot event ledger invalid")
        _atomic_json(self.import_path, dict(payload))
        return {"contract_version": MISSION_CONTRACT, "status": "imported", "generated_at": payload.get("generated_at")}

    def snapshot(self) -> dict[str, Any]:
        local_runtime = _read_json(self.runtime_path)
        local_summary = _read_json(self.summary_path)
        local_events = _bounded_events(self.event_path)
        imported = _read_json(self.import_path)
        source = "definition_only"
        generated_at = None
        config = self._config()
        runtime = local_runtime
        summary = local_summary
        events = local_events
        if runtime is not None:
            source = "local_runtime"
            generated_at = summary.get("generated_at") if isinstance(summary, Mapping) else None
        elif imported is not None and imported.get("contract_version") == SNAPSHOT_CONTRACT:
            source = "imported_snapshot"
            config = dict(imported.get("config") or config)
            runtime = imported.get("runtime") if isinstance(imported.get("runtime"), Mapping) else None
            summary = imported.get("summary") if isinstance(imported.get("summary"), Mapping) else None
            events = [dict(row) for row in imported.get("events", []) if isinstance(row, Mapping)][-MAX_EVENTS:]
            generated_at = imported.get("generated_at")

        tasks_source = runtime.get("tasks") if isinstance(runtime, Mapping) and isinstance(runtime.get("tasks"), list) else config.get("tasks", [])
        tasks = [_task_view(row) for row in tasks_source if isinstance(row, Mapping)]
        runtime_present = runtime is not None
        workers = _worker_views(config, tasks, runtime_present=runtime_present, runtime=runtime if isinstance(runtime, Mapping) else None)
        age = _snapshot_age(generated_at)
        resources = _resource_views(workers, tasks, snapshot_age_seconds=age)
        counts: dict[str, int] = {}
        for task in tasks:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
        owner_actions = [task for task in tasks if task["status"] == "OWNER_REQUIRED" and int(task.get("authority") or 0) >= 4]
        active_tasks = [task for task in tasks if task["status"] in ACTIVE_STATES]
        failed_tasks = [task for task in tasks if task["status"] in {"BLOCKED", "TRIAGE", "QUARANTINED"}]
        external_waiting = [
            {
                "task_id": task.get("id"),
                "worker_id": task.get("assigned_worker"),
                "wait_started_at": task.get("external_wait_started_at"),
                "dispatch_id": task.get("dispatch_id"),
            }
            for task in tasks if task.get("external_wait_state") == "WAITING_EXTERNAL"
        ]
        zero_idle_assignments = [
            {"task_id": task.get("id"), **task["zero_idle_evidence"]}
            for task in tasks if isinstance(task.get("zero_idle_evidence"), Mapping)
        ]
        total_non_owner = sum(1 for task in tasks if int(task.get("authority") or 0) < 4)
        done_non_owner = sum(1 for task in tasks if int(task.get("authority") or 0) < 4 and task["status"] == "DONE")
        try:
            research_summary = load_research_summary(self.integration_root)
        except IntegrationUnavailableError as exc:
            research_summary = {"status": "unavailable", "reason": str(exc)}
        try:
            zotero_summary = load_zotero_summary(self.integration_root)
        except IntegrationUnavailableError as exc:
            zotero_summary = {"status": "unavailable", "reason": str(exc)}
        return {
            "contract_version": MISSION_CONTRACT,
            "paper_only": True,
            "live_trading_authority": False,
            "source": source,
            "generated_at": generated_at,
            "snapshot_age_seconds": age,
            "stale": bool(age is not None and age > 900),
            "control_plane": {
                "runtime_present": runtime_present,
                "summary": summary,
                "policy": config.get("policy"),
                "task_counts": counts,
                "verified_progress_percent": round((done_non_owner / total_non_owner * 100.0) if total_non_owner else 0.0, 2),
                "active_tasks": active_tasks,
                "blocked_or_triage": failed_tasks,
                "external_waiting": external_waiting,
                "zero_idle_assignments": zero_idle_assignments,
            },
            "workers": workers,
            "resources": resources,
            "tasks": tasks,
            "events": events,
            "ci_health": _latest_ci(events),
            "owner_actions": owner_actions,
            "owner_action_required": bool(owner_actions),
            "strategy_center": self.strategy_store.history(),
            "research_integration": research_summary,
            "zotero_integration": zotero_summary,
        }