"""Synchronized 15m/1h/4h regime selection over the immutable Demo archive.

The existing 18-lane matrix remains the comparison/performance surface.  This
controller consumes its verified Supervisor/performance evidence, rebuilds a
common point-in-time market context from the same immutable Bybit archive, and
routes only currently eligible proposals through the already-audited regime
selector and Deterministic Risk runtime.

Authority is strictly Research/Backtest/Demo Paper.  This module cannot promote
strategies, use private credentials, route exchange orders, or grant Live/L4
trading authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cross_timeframe_context import build_cross_timeframe_context
from data_intelligence import classify_canonical_regimes
from market_data_source_validator import load_and_validate
from nexus_demo_archive_replay import ARCHIVE_SHA256, build_archive_dataset_fetcher
from nexus_demo_strategy_matrix import load_manifest, load_state
from nexus_isolated_product_runtime import IsolatedProductRuntime, regime_paper_account_id
from nexus_regime_paper_lane import prepare_regime_paper_lane
from nexus_regime_runtime_drift import build_regime_runtime_drift, persist_regime_runtime_drift
from nexus_regime_strategy_runtime import (
    load_runtime_evidence,
    persist_runtime_evidence,
    run_regime_strategy_runtime,
    verify_runtime_evidence,
)
from nexus_regime_strategy_selector import select_strategy_mix, validate_policy
from nexus_strategy_paper_supervisor import verify_ledger
from paper_event_store import replay, validate_event
from phase5_data_binding import validate_canonical_dataset
from product_research_runtime import (
    ProductResearchRuntime,
    TIMEFRAMES,
    _public_mapping,
    _registry_path,
    _utc_ms,
)
from product_runtime import ProductRuntimeError


SCHEMA = "nexus.demo-regime-cycle.v1"
CELL_SCHEMA = "nexus.demo-regime-cell.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HEALTH = {"HEALTHY", "WATCH", "DEGRADED", "QUARANTINED"}
_TIMEFRAME_MANIFEST = {"minute15": "15m", "hour1": "1h", "hour4": "4h"}
_HOUR4_MS = 14_400_000
_MAX_JSON_BYTES = 20_000_000


class DemoRegimeCycleError(RuntimeError):
    pass


ArchiveFetcher = Callable[..., Mapping[str, Any]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DemoRegimeCycleError("regime cycle evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise DemoRegimeCycleError(f"required evidence is unavailable or unsafe: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoRegimeCycleError(f"required evidence is unreadable: {path.name}") from exc
    if not isinstance(value, dict):
        raise DemoRegimeCycleError(f"required evidence is not an object: {path.name}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    payload = json.dumps(
        dict(value), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DemoRegimeCycleError("regime cycle state commit failed") from exc


def _load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = _read_json(path)
        return validate_policy(policy)
    except Exception as exc:
        raise DemoRegimeCycleError(f"selector policy verification failed: {exc}") from exc


def _validate_performance_projection(
    projection: Mapping[str, Any], supervisor_verification_digest: str
) -> dict[str, Any]:
    required = {
        "contract_version", "supervisor_verification_digest", "paper_only",
        "live_trading_authority", "strategy_count", "status_counts", "strategies",
        "projection_digest",
    }
    if not isinstance(projection, Mapping) or set(projection) != required:
        raise DemoRegimeCycleError("Paper performance projection schema mismatch")
    core = dict(projection)
    claimed = core.pop("projection_digest", None)
    strategies = core.get("strategies")
    if (
        core.get("contract_version") != "nexus.mission-control.paper-performance.v1"
        or core.get("supervisor_verification_digest") != supervisor_verification_digest
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or not isinstance(strategies, list)
        or core.get("strategy_count") != len(strategies)
        or len(strategies) > 32
        or claimed != _digest(core)
    ):
        raise DemoRegimeCycleError("Paper performance projection verification failed")
    if any(not isinstance(row, Mapping) for row in strategies):
        raise DemoRegimeCycleError("Paper performance strategy row is invalid")
    return dict(projection)


def _cell_root(state_root: Path, symbol: str, timeframe: str) -> Path:
    return Path(state_root).resolve() / "cells" / symbol.lower() / timeframe


def _load_cell_inputs(
    *, state_root: Path, symbol: str, timeframe: str, source_sha: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = _cell_root(state_root, symbol, timeframe)
    ledger = _read_json(root / "supervisor-ledger.json")
    verification = verify_ledger(ledger)
    if verification.get("decision") != "pass":
        raise DemoRegimeCycleError("Supervisor ledger failed independent verification")
    if (
        ledger.get("source_sha") != source_sha
        or ledger.get("symbol") != symbol
        or ledger.get("timeframe") != timeframe
        or ledger.get("paper_only") is not True
        or ledger.get("live_trading_authority") is not False
    ):
        raise DemoRegimeCycleError("Supervisor ledger does not bind the requested Demo cell")
    performance = _validate_performance_projection(
        _read_json(root / "analysis" / "paper-performance.json"),
        str(verification.get("verification_digest", "")),
    )
    return ledger, performance


def _eligible_health_rows(
    ledger: Mapping[str, Any], performance: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    tasks = ledger.get("tasks")
    strategies = performance.get("strategies")
    if not isinstance(tasks, list) or not isinstance(strategies, list):
        raise DemoRegimeCycleError("cell task/performance rows are invalid")
    task_by_family: dict[str, Mapping[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            raise DemoRegimeCycleError("Supervisor task row is invalid")
        family = task.get("family")
        if not isinstance(family, str) or not family or family in task_by_family:
            raise DemoRegimeCycleError("Supervisor family identity is invalid or duplicated")
        task_by_family[family] = task
    perf_by_family: dict[str, Mapping[str, Any]] = {}
    for row in strategies:
        family = row.get("family")
        if not isinstance(family, str) or not family or family in perf_by_family:
            raise DemoRegimeCycleError("performance family identity is invalid or duplicated")
        perf_by_family[family] = row

    eligible: dict[str, dict[str, Any]] = {}
    for family, row in perf_by_family.items():
        task = task_by_family.get(family)
        if task is None or task.get("status") not in {"paper_executed", "position_exists"}:
            raise DemoRegimeCycleError("performance row lacks active verified Supervisor evidence")
        research = task.get("research_result")
        if not isinstance(research, Mapping):
            raise DemoRegimeCycleError("strategy research evidence is missing")
        record = research.get("strategy_record")
        qualification = research.get("qualification")
        if not isinstance(record, Mapping) or not isinstance(qualification, Mapping):
            raise DemoRegimeCycleError("strategy registry/qualification evidence is missing")
        if (
            row.get("strategy_id") != record.get("strategy_id")
            or record.get("family") != family
            or qualification.get("family") != family
        ):
            raise DemoRegimeCycleError("performance strategy identity substitution detected")
        status = row.get("status")
        lifecycle = row.get("lifecycle_state")
        if status == "INSUFFICIENT_EVIDENCE":
            # Insufficient evidence cannot become a selector health claim.  The
            # policy target remains cash until the monitor has enough evidence.
            continue
        if status not in _HEALTH:
            raise DemoRegimeCycleError("unsupported performance health state")
        if lifecycle != "PAPER":
            continue
        record_digest = record.get("record_digest")
        monitor_digest = row.get("monitor_digest")
        if (
            not isinstance(record_digest, str) or not _SHA256_RE.fullmatch(record_digest)
            or not isinstance(monitor_digest, str) or not _SHA256_RE.fullmatch(monitor_digest)
        ):
            raise DemoRegimeCycleError("strategy health evidence digest is invalid")
        eligible[family] = {
            "family": family,
            "canonical_strategy_id": record["strategy_id"],
            "strategy_version": qualification.get("strategy_version"),
            "record_digest": record_digest,
            "health_state": status,
            "health_digest": monitor_digest,
            "lifecycle_state": lifecycle,
        }
    return eligible


def _common_as_of(matrix_state: Mapping[str, Any], symbol: str) -> int:
    cells = matrix_state.get("cells")
    if not isinstance(cells, Mapping):
        raise DemoRegimeCycleError("matrix state cells are invalid")
    cell = cells.get(f"{symbol}:hour4")
    if not isinstance(cell, Mapping) or cell.get("status") != "VERIFIED":
        raise DemoRegimeCycleError("hour4 matrix cell is not verified for synchronized context")
    open_ms = cell.get("last_completed_open_ms")
    if isinstance(open_ms, bool) or not isinstance(open_ms, int) or open_ms < 0:
        raise DemoRegimeCycleError("hour4 matrix cursor is invalid")
    return open_ms + _HOUR4_MS


def _fetch_synchronized_dataset(
    *, fetcher: ArchiveFetcher, symbol: str, timeframe: str, as_of_ms: int, limit: int
) -> dict[str, Any]:
    spec = TIMEFRAMES[timeframe]
    registry = load_and_validate(_registry_path())
    mapping, source = _public_mapping(registry, symbol, timeframe)
    step_ms = int(spec["step_ms"])
    end_ms = ((as_of_ms - step_ms) // step_ms) * step_ms
    start_ms = end_ms - (limit - 1) * step_ms
    if start_ms < 0:
        raise DemoRegimeCycleError("synchronized archive window is invalid")
    try:
        dataset = fetcher(
            canonical_symbol=mapping["canonical_symbol"],
            source_symbol=source["symbol"],
            interval=spec["interval"],
            now_ms=as_of_ms,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=limit,
        )
        return validate_canonical_dataset(dataset, registry_path=_registry_path())
    except Exception as exc:
        raise DemoRegimeCycleError(
            f"synchronized {symbol}/{timeframe} archive dataset rejected: {exc}"
        ) from exc


def build_synchronized_context(
    *, fetcher: ArchiveFetcher, symbol: str, as_of_ms: int, history_limit: int
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    datasets: dict[str, dict[str, Any]] = {}
    evidences: list[dict[str, Any]] = []
    for timeframe in ("minute15", "hour1", "hour4"):
        dataset = _fetch_synchronized_dataset(
            fetcher=fetcher, symbol=symbol, timeframe=timeframe,
            as_of_ms=as_of_ms, limit=history_limit,
        )
        evidence = classify_canonical_regimes(dataset)
        if evidence.get("timeframe") != _TIMEFRAME_MANIFEST[timeframe]:
            raise DemoRegimeCycleError("regime evidence timeframe binding mismatch")
        datasets[timeframe] = dataset
        evidences.append(evidence)
    try:
        context = build_cross_timeframe_context(evidences, as_of_ms=as_of_ms)
    except Exception as exc:
        raise DemoRegimeCycleError(f"cross-timeframe context failed closed: {exc}") from exc
    return context, datasets


def _append_events_once(runtime: IsolatedProductRuntime, events: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)) or not events:
        raise DemoRegimeCycleError("runtime evidence contains no Paper events")
    validated = [validate_event(dict(event)) for event in events]
    with runtime._lock:
        existing = runtime._ensure_account()
        existing_by_id = {event["event_id"]: (index, event) for index, event in enumerate(existing)}
        matched: list[int] = []
        missing: list[dict[str, Any]] = []
        for event in validated:
            prior = existing_by_id.get(event["event_id"])
            if prior is None:
                missing.append(event)
                continue
            index, stored = prior
            if stored["event_digest"] != event["event_digest"] or stored != event:
                raise DemoRegimeCycleError("Paper event identity collision during restart reconciliation")
            matched.append(index)
        if not missing:
            if matched != list(range(matched[0], matched[0] + len(matched))):
                raise DemoRegimeCycleError("replayed Paper events are not a contiguous journal segment")
            return
        if matched:
            raise DemoRegimeCycleError("partial Paper event persistence requires fail-closed recovery")
        if validated[0]["previous_event_digest"] != existing[-1]["event_digest"]:
            raise DemoRegimeCycleError("Paper runtime head does not match persisted runtime evidence")
        try:
            replay(existing + validated)
            runtime._write_events(existing + validated)
        except Exception as exc:
            raise DemoRegimeCycleError(f"Paper event persistence failed closed: {exc}") from exc


def _runtime_for(
    *, state_root: Path, symbol: str, timeframe: str, family: str, as_of_ms: int
) -> IsolatedProductRuntime:
    return IsolatedProductRuntime(
        Path(state_root).resolve() / "regime_selected" / symbol.lower() / timeframe / family,
        account_id=regime_paper_account_id(
            symbol=symbol, timeframe=timeframe, family=family
        ),
        clock=lambda: _utc_ms(as_of_ms),
    )


def _reconcile_evidence_file(
    *, path: Path, state_root: Path, symbol: str, timeframe: str, as_of_ms: int
) -> None:
    evidence = load_runtime_evidence(path)
    occurred_at = evidence.get("occurred_at")
    if not isinstance(occurred_at, str):
        raise DemoRegimeCycleError("persisted runtime evidence timestamp is invalid")
    for row in evidence.get("lanes", []):
        family = row.get("family")
        if not isinstance(family, str) or not family:
            raise DemoRegimeCycleError("persisted runtime family is invalid")
        runtime = _runtime_for(
            state_root=state_root, symbol=symbol, timeframe=timeframe,
            family=family, as_of_ms=as_of_ms,
        )
        _append_events_once(runtime, row.get("events", []))


def reconcile_persisted_runtime_evidence(
    *, state_root: Path, symbol: str, timeframe: str, as_of_ms: int
) -> None:
    root = Path(state_root).resolve() / "regime_runtime_evidence" / symbol.lower() / timeframe
    if not root.exists():
        return
    if root.is_symlink() or not root.is_dir():
        raise DemoRegimeCycleError("runtime evidence directory is unsafe")
    rows: list[tuple[str, Path]] = []
    for path in root.glob("*.json"):
        evidence = load_runtime_evidence(path)
        occurred_at = evidence.get("occurred_at")
        if not isinstance(occurred_at, str):
            raise DemoRegimeCycleError("persisted runtime evidence timestamp is invalid")
        rows.append((occurred_at, path))
    for _occurred_at, path in sorted(rows, key=lambda item: (item[0], item[1].name)):
        _reconcile_evidence_file(
            path=path, state_root=state_root, symbol=symbol,
            timeframe=timeframe, as_of_ms=as_of_ms,
        )


def _prepare_candidates_and_lanes(
    *,
    state_root: Path,
    source_sha: str,
    symbol: str,
    timeframe: str,
    as_of_ms: int,
    history_limit: int,
    fetcher: ArchiveFetcher,
    health_rows: Mapping[str, Mapping[str, Any]],
    expected_dataset_binding: str,
) -> tuple[list[dict[str, Any]], dict[str, Mapping[str, Any]], list[dict[str, Any]]]:
    if not isinstance(expected_dataset_binding, str) or not _SHA256_RE.fullmatch(expected_dataset_binding):
        raise DemoRegimeCycleError("synchronized context dataset binding is invalid")
    candidates: list[dict[str, Any]] = []
    lanes: dict[str, Mapping[str, Any]] = {}
    preparations: list[dict[str, Any]] = []
    for family in sorted(health_rows):
        health = health_rows[family]
        runtime = _runtime_for(
            state_root=state_root, symbol=symbol, timeframe=timeframe,
            family=family, as_of_ms=as_of_ms,
        )
        research = ProductResearchRuntime(
            runtime,
            source_sha=source_sha,
            dataset_fetcher=fetcher,
            clock_ms=lambda as_of_ms=as_of_ms: as_of_ms,
        )
        research_result = research.run_research(
            symbol=symbol, timeframe=timeframe, family=family, limit=history_limit
        )
        preparation = prepare_regime_paper_lane(research)
        preparations.append({
            "family": family,
            "status": preparation["status"],
            "preparation_digest": preparation["preparation_digest"],
            "account_id": preparation["account_id"],
            "lane_ready": preparation["lane_ready"],
            "execution_performed": preparation["execution_performed"],
            "dataset_binding_sha256": preparation.get("dataset_binding_sha256"),
        })
        if preparation["status"] != "ready":
            continue
        if preparation.get("dataset_binding_sha256") != expected_dataset_binding:
            raise DemoRegimeCycleError(
                "fresh proposal dataset is not bound to synchronized cross-timeframe context"
            )
        if (
            health.get("strategy_version") != preparation.get("strategy_version")
            or research_result.get("qualification", {}).get("strategy_version")
            != preparation.get("strategy_version")
        ):
            raise DemoRegimeCycleError("fresh proposal strategy version contradicts health evidence")
        candidate = {
            "family": family,
            # The current execution contract identifies approved proposals by family;
            # canonical registry identity was independently verified above.
            "strategy_id": family,
            "strategy_version": preparation["strategy_version"],
            "lifecycle_state": "PAPER",
            "health_state": health["health_state"],
            "record_digest": health["record_digest"],
            "health_digest": health["health_digest"],
            "paper_only": True,
            "live_trading_authority": False,
        }
        candidates.append(candidate)
        lanes[family] = preparation["lane"]
    return candidates, lanes, preparations


def run_demo_regime_cycle(
    *,
    manifest: Mapping[str, Any],
    matrix_state: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    archive_fetcher: ArchiveFetcher,
    selector_policy: Mapping[str, Any],
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise DemoRegimeCycleError("source_sha must be an exact Git SHA")
    policy = validate_policy(selector_policy)
    root = Path(state_root).resolve()
    cells: list[dict[str, Any]] = []
    contexts: dict[str, str] = {}

    for symbol in manifest["symbols"]:
        as_of_ms = _common_as_of(matrix_state, symbol)
        context, datasets = build_synchronized_context(
            fetcher=archive_fetcher,
            symbol=symbol,
            as_of_ms=as_of_ms,
            history_limit=manifest["history_limit"],
        )
        contexts[symbol] = context["context_sha256"]
        for timeframe in manifest["timeframes"]:
            matrix_cell = matrix_state.get("cells", {}).get(f"{symbol}:{timeframe}")
            if (
                not isinstance(matrix_cell, Mapping)
                or matrix_cell.get("status") != "VERIFIED"
                or matrix_cell.get("source_sha") != source_sha
            ):
                raise DemoRegimeCycleError("regime cycle requires a freshly verified matrix cell")
            synchronized_dataset = datasets.get(timeframe)
            if not isinstance(synchronized_dataset, Mapping):
                raise DemoRegimeCycleError("synchronized context dataset is missing for matrix timeframe")
            expected_dataset_binding = synchronized_dataset.get("binding_sha256")
            if not isinstance(expected_dataset_binding, str) or not _SHA256_RE.fullmatch(expected_dataset_binding):
                raise DemoRegimeCycleError("synchronized context dataset binding is invalid")
            reconcile_persisted_runtime_evidence(
                state_root=root, symbol=symbol, timeframe=timeframe, as_of_ms=as_of_ms
            )
            ledger, performance = _load_cell_inputs(
                state_root=root, symbol=symbol, timeframe=timeframe, source_sha=source_sha
            )
            health_rows = _eligible_health_rows(ledger, performance)
            candidates, prepared_lanes, preparations = _prepare_candidates_and_lanes(
                state_root=root,
                source_sha=source_sha,
                symbol=symbol,
                timeframe=timeframe,
                as_of_ms=as_of_ms,
                history_limit=manifest["history_limit"],
                fetcher=archive_fetcher,
                health_rows=health_rows,
                expected_dataset_binding=expected_dataset_binding,
            )
            selection = select_strategy_mix(
                context=context,
                candidates=candidates,
                policy=policy,
                source_sha=source_sha,
            )
            selected_families = [row["family"] for row in selection["allocations"]]
            lanes = [prepared_lanes[family] for family in selected_families]
            result = run_regime_strategy_runtime(
                context=context,
                candidates=candidates,
                selector_policy=policy,
                lanes=lanes,
                source_sha=source_sha,
                occurred_at=_utc_ms(as_of_ms),
            )
            verification = verify_runtime_evidence(result.evidence)
            if (
                verification.get("decision") != "pass"
                or result.evidence.get("selection_digest") != selection["selection_digest"]
            ):
                raise DemoRegimeCycleError("regime runtime failed independent replay verification")
            runtime_root = root / "regime_runtime_evidence" / symbol.lower() / timeframe
            runtime_path = persist_runtime_evidence(result.evidence, runtime_root)
            _reconcile_evidence_file(
                path=runtime_path, state_root=root, symbol=symbol,
                timeframe=timeframe, as_of_ms=as_of_ms,
            )
            drift = build_regime_runtime_drift(
                supervisor_ledger=ledger,
                performance_projection=performance,
                runtime_evidence=result.evidence,
            )
            drift_path = persist_regime_runtime_drift(
                drift, root / "regime_runtime_drift" / symbol.lower() / timeframe
            )
            cell_core = {
                "schema_version": CELL_SCHEMA,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_sha": source_sha,
                "as_of_ms": as_of_ms,
                "context_sha256": context["context_sha256"],
                "context_dataset_binding_sha256": expected_dataset_binding,
                "alignment": context["alignment"],
                "performance_projection_digest": performance["projection_digest"],
                "candidate_count": len(candidates),
                "preparations": preparations,
                "selection_digest": selection["selection_digest"],
                "selected_families": selected_families,
                "cash_weight": selection["cash_weight"],
                "runtime_digest": result.evidence["runtime_digest"],
                "runtime_verification_digest": verification["verification_digest"],
                "runtime_evidence_file": runtime_path.name,
                "drift_digest": drift["drift_digest"],
                "drift_state": drift["drift_state"],
                "drift_evidence_file": drift_path.name,
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
            }
            cells.append({**cell_core, "cell_digest": _digest(cell_core)})

    core = {
        "schema_version": SCHEMA,
        "matrix_id": manifest["matrix_id"],
        "source_sha": source_sha,
        "archive_sha256": ARCHIVE_SHA256,
        "context_digests": dict(sorted(contexts.items())),
        "expected_cell_count": len(manifest["symbols"]) * len(manifest["timeframes"]),
        "verified_cell_count": len(cells),
        "cells": sorted(cells, key=lambda row: (row["symbol"], row["timeframe"])),
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "frozen_prospective_hour4_lane_mutated": False,
    }
    snapshot = {**core, "cycle_digest": _digest(core)}
    _atomic_json(root / "demo" / "regime-cycle.json", snapshot)
    return snapshot


def verify_cycle_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "shape": False,
        "authority": False,
        "cells": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("cycle_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        cells = core.get("cells")
        checks["shape"] = bool(
            core.get("expected_cell_count") == 6
            and core.get("verified_cell_count") == 6
            and isinstance(cells, list)
            and len(cells) == 6
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("frozen_prospective_hour4_lane_mutated") is False
        )
        checks["cells"] = bool(
            isinstance(cells, list)
            and all(
                isinstance(row, Mapping)
                and row.get("schema_version") == CELL_SCHEMA
                and row.get("paper_only") is True
                and row.get("live_trading_authority") is False
                and row.get("private_credentials_used") is False
                and row.get("automatic_strategy_promotion") is False
                and row.get("deterministic_risk_final_authority") is True
                and isinstance(row.get("cell_digest"), str)
                and row["cell_digest"] == _digest({
                    key: item for key, item in row.items() if key != "cell_digest"
                })
                for row in cells
            )
        )
    except (TypeError, ValueError, KeyError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--replay-archive-root", type=Path, required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument(
        "--selector-policy", type=Path,
        default=Path("config/nexus-regime-strategy-policy-v1.json"),
    )
    args = parser.parse_args()
    if str(args.archive_sha256).lower() != ARCHIVE_SHA256:
        raise DemoRegimeCycleError("only the approved immutable archive is eligible")
    manifest = load_manifest(args.manifest)
    matrix_state = load_state(args.state_root / "matrix-state.json", manifest)
    fetcher = build_archive_dataset_fetcher(
        args.replay_archive_root, archive_sha256=args.archive_sha256
    )
    snapshot = run_demo_regime_cycle(
        manifest=manifest,
        matrix_state=matrix_state,
        state_root=args.state_root,
        source_sha=args.source_sha,
        archive_fetcher=fetcher,
        selector_policy=_load_policy(args.selector_policy),
    )
    verification = verify_cycle_snapshot(snapshot)
    print(json.dumps({
        "status": verification["decision"],
        "verified_cells": snapshot["verified_cell_count"],
        "expected_cells": snapshot["expected_cell_count"],
        "cycle_digest": snapshot["cycle_digest"],
    }, sort_keys=True))
    return 0 if verification["decision"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
