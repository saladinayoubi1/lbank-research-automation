"""Scheduled multi-symbol, multi-timeframe, multi-strategy Demo Paper matrix.

The controller owns orchestration and evidence only. Every cell delegates to the
existing Strategy Paper Supervisor, Deterministic Risk remains final, and no
Live/private-credential authority exists here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCHEMA = "nexus.demo-strategy-matrix.v1"
STATE_SCHEMA = "nexus.demo-strategy-matrix-state.v1"
SNAPSHOT_SCHEMA = "nexus.demo-strategy-matrix-snapshot.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SYMBOLS = {"BTCUSDT", "ETHUSDT"}
_TIMEFRAMES = {
    "minute15": 900_000,
    "hour1": 3_600_000,
    "hour4": 14_400_000,
}
_FAMILIES = {"momentum", "trend_breakout", "mean_reversion"}


class DemoStrategyMatrixError(RuntimeError):
    pass


Runner = Callable[..., Mapping[str, Any]]
Verifier = Callable[[Mapping[str, Any]], Mapping[str, Any]]
Analyzer = Callable[[Path, Mapping[str, Any]], Mapping[str, Any]]
ClockResolver = Callable[[str, str, int, int], int]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DemoStrategyMatrixError("matrix evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoStrategyMatrixError("matrix manifest is unavailable") from exc
    required = {
        "schema_version", "matrix_id", "symbols", "timeframes", "families",
        "history_limit", "authority",
    }
    if not isinstance(raw, dict) or set(raw) != required or raw.get("schema_version") != SCHEMA:
        raise DemoStrategyMatrixError("matrix manifest schema mismatch")
    symbols = raw.get("symbols")
    timeframes = raw.get("timeframes")
    families = raw.get("families")
    authority = raw.get("authority")
    if (
        not isinstance(symbols, list) or set(symbols) != _SYMBOLS or len(symbols) != len(_SYMBOLS)
        or not isinstance(timeframes, list) or set(timeframes) != set(_TIMEFRAMES)
        or len(timeframes) != len(_TIMEFRAMES)
        or not isinstance(families, list) or set(families) != _FAMILIES
        or len(families) != len(_FAMILIES)
    ):
        raise DemoStrategyMatrixError("matrix must contain the approved 2 x 3 x 3 surface")
    if (
        isinstance(raw.get("history_limit"), bool)
        or not isinstance(raw.get("history_limit"), int)
        or not 60 <= raw["history_limit"] <= 500
    ):
        raise DemoStrategyMatrixError("matrix history_limit is outside the bounded range")
    if not isinstance(authority, dict) or authority != {
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_allowed": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }:
        raise DemoStrategyMatrixError("matrix authority boundary mismatch")
    return raw


def _default_runner(**kwargs: Any) -> Mapping[str, Any]:
    from nexus_strategy_paper_supervisor import run_once

    return run_once(**kwargs)


def _default_verifier(ledger: Mapping[str, Any]) -> Mapping[str, Any]:
    from nexus_strategy_paper_supervisor import verify_ledger

    return verify_ledger(ledger)


def _read_journal(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise DemoStrategyMatrixError("Paper journal is unavailable or unsafe")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle, start=1):
            if index > 100_000 or not line.strip():
                raise DemoStrategyMatrixError("Paper journal is invalid or unbounded")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise DemoStrategyMatrixError("Paper journal row is not an object")
            rows.append(value)
    return rows


def _baseline(task: Mapping[str, Any]) -> dict[str, str]:
    fills = task.get("research_result", {}).get("backtest", {}).get("fills", [])
    fees: list[Decimal] = []
    if isinstance(fills, list):
        for row in fills:
            if isinstance(row, Mapping) and not isinstance(row.get("fee"), bool):
                try:
                    fees.append(Decimal(str(row["fee"])))
                except Exception:
                    continue
    fee = sum(fees, Decimal("0")) / Decimal(len(fees)) if fees else Decimal("0")
    return {"expectancy": "0", "fee_per_trade": format(fee, "f")}


def _default_analyzer(cell_root: Path, ledger: Mapping[str, Any]) -> Mapping[str, Any]:
    from nexus_paper_performance_pipeline import (
        build_paper_performance_projection,
        save_paper_performance_projection,
    )

    journals: dict[str, Sequence[Mapping[str, Any]]] = {}
    baselines: dict[str, Mapping[str, Any]] = {}
    for task in ledger.get("tasks", []):
        if task.get("status") not in {"paper_executed", "position_exists"}:
            continue
        family = str(task["family"])
        journals[family] = _read_journal(
            cell_root / "portfolios" / family / "product_runtime" / "paper-events.jsonl"
        )
        baselines[family] = _baseline(task)
    projection = build_paper_performance_projection(
        supervisor_ledger=ledger,
        journals_by_family=journals,
        baselines_by_family=baselines,
    )
    save_paper_performance_projection(cell_root / "analysis" / "paper-performance.json", projection)
    return projection


def _completed_open(now_ms: int, step_ms: int) -> int:
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= step_ms:
        raise DemoStrategyMatrixError("now_ms is invalid")
    return ((now_ms - step_ms) // step_ms) * step_ms


def _empty_state(manifest: Mapping[str, Any]) -> dict[str, Any]:
    core = {
        "schema_version": STATE_SCHEMA,
        "matrix_id": manifest["matrix_id"],
        "manifest_sha256": _digest(manifest),
        "cells": {},
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "state_digest": _digest(core)}


def load_state(path: str | Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return _empty_state(manifest)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoStrategyMatrixError("matrix state is unreadable") from exc
    if not isinstance(raw, dict):
        raise DemoStrategyMatrixError("matrix state is not an object")
    core = dict(raw)
    claimed = core.pop("state_digest", None)
    if (
        core.get("schema_version") != STATE_SCHEMA
        or core.get("matrix_id") != manifest["matrix_id"]
        or core.get("manifest_sha256") != _digest(manifest)
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("private_credentials_used") is not False
        or core.get("automatic_strategy_promotion") is not False
        or not isinstance(core.get("cells"), dict)
        or claimed != _digest(core)
    ):
        raise DemoStrategyMatrixError("matrix state verification failed")
    return raw


def _cell_id(symbol: str, timeframe: str) -> str:
    return f"{symbol}:{timeframe}"


def _error_evidence(exc: Exception) -> tuple[str, str]:
    code = type(exc).__name__
    return code, _digest({"type": code, "message": str(exc)})


def run_matrix_cycle(
    *,
    manifest: Mapping[str, Any],
    state: Mapping[str, Any],
    state_root: str | Path,
    source_sha: str,
    run_id: str,
    now_ms: int,
    runner: Runner = _default_runner,
    verifier: Verifier = _default_verifier,
    analyzer: Analyzer = _default_analyzer,
    now_resolver: ClockResolver | None = None,
    data_mode: str = "public_api",
    dataset_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha):
        raise DemoStrategyMatrixError("source_sha must be an exact Git SHA")
    if not str(run_id).isdigit():
        raise DemoStrategyMatrixError("run_id must be numeric")
    root = Path(state_root).resolve()
    prior_cells = state.get("cells", {})
    cells: dict[str, Any] = dict(prior_cells)
    cycle_rows: list[dict[str, Any]] = []

    for symbol in manifest["symbols"]:
        for timeframe in manifest["timeframes"]:
            cell_id = _cell_id(symbol, timeframe)
            step_ms = _TIMEFRAMES[timeframe]
            previous = prior_cells.get(cell_id, {})
            previous_open = previous.get("last_completed_open_ms", -1)
            if isinstance(previous_open, bool) or not isinstance(previous_open, int):
                raise DemoStrategyMatrixError("matrix cell cursor is invalid")
            effective_now_ms = (
                now_ms if now_resolver is None
                else now_resolver(symbol, timeframe, previous_open, manifest["history_limit"])
            )
            bar_open = _completed_open(effective_now_ms, step_ms)
            if bar_open <= previous_open:
                cycle_rows.append({"cell_id": cell_id, "status": "SKIPPED_NO_NEW_BAR"})
                continue

            cell_root = root / "cells" / symbol.lower() / timeframe
            try:
                ledger = dict(runner(
                    source_sha=source_sha,
                    state_root=cell_root,
                    symbol=symbol,
                    timeframe=timeframe,
                    families=tuple(manifest["families"]),
                    limit=manifest["history_limit"],
                    now_ms=effective_now_ms,
                ))
                verification = dict(verifier(ledger))
                if verification.get("decision") != "pass":
                    raise DemoStrategyMatrixError("independent Supervisor verification rejected the cell")
                tasks = ledger.get("tasks")
                if (
                    not isinstance(tasks, list) or len(tasks) != len(manifest["families"])
                    or {row.get("family") for row in tasks} != set(manifest["families"])
                    or ledger.get("symbol") != symbol or ledger.get("timeframe") != timeframe
                    or ledger.get("paper_only") is not True
                    or ledger.get("live_trading_authority") is not False
                ):
                    raise DemoStrategyMatrixError("Supervisor ledger does not bind the matrix cell")
                analysis = dict(analyzer(cell_root, ledger))
                if (
                    analysis.get("paper_only") is not True
                    or analysis.get("live_trading_authority") is not False
                ):
                    raise DemoStrategyMatrixError("performance analysis exceeded Paper authority")
                lanes = [{
                    "family": row["family"],
                    "task_id": row["task_id"],
                    "status": row["status"],
                    "evidence_digest": row["evidence_digest"],
                } for row in tasks]
                cells[cell_id] = {
                    "cell_id": cell_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "step_ms": step_ms,
                    "last_completed_open_ms": bar_open,
                    "status": "VERIFIED",
                    "source_sha": source_sha,
                    "run_id": str(run_id),
                    "ledger_digest": ledger["ledger_digest"],
                    "verification_digest": verification["verification_digest"],
                    "analysis_digest": analysis["projection_digest"],
                    "analysis_status_counts": analysis.get("status_counts", {}),
                    "lanes": sorted(lanes, key=lambda row: row["family"]),
                }
                cycle_rows.append({"cell_id": cell_id, "status": "VERIFIED"})
            except Exception as exc:
                code, error_digest = _error_evidence(exc)
                blocked = dict(previous) if isinstance(previous, Mapping) else {}
                blocked.update({
                    "cell_id": cell_id,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "step_ms": step_ms,
                    "status": "BLOCKED",
                    "attempted_open_ms": bar_open,
                    "source_sha": source_sha,
                    "run_id": str(run_id),
                    "error_code": code,
                    "error_digest": error_digest,
                })
                blocked.setdefault("last_completed_open_ms", previous_open)
                blocked.setdefault("lanes", [])
                cells[cell_id] = blocked
                cycle_rows.append({"cell_id": cell_id, "status": "BLOCKED", "error_code": code})

    expected_cells = len(manifest["symbols"]) * len(manifest["timeframes"])
    expected_lanes = expected_cells * len(manifest["families"])
    verified_cells = sum(row.get("status") == "VERIFIED" for row in cells.values())
    blocked_cells = sum(row.get("status") == "BLOCKED" for row in cells.values())
    lane_rows: list[dict[str, Any]] = []
    for cell in cells.values():
        for lane in cell.get("lanes", []):
            lane_rows.append({
                "symbol": cell["symbol"], "timeframe": cell["timeframe"], **lane,
            })
    overall = "VERIFIED" if verified_cells == expected_cells and blocked_cells == 0 else "DEGRADED"
    state_core = {
        "schema_version": STATE_SCHEMA,
        "matrix_id": manifest["matrix_id"],
        "manifest_sha256": _digest(manifest),
        "cells": dict(sorted(cells.items())),
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "data_mode": data_mode,
        "dataset_sha256": dataset_sha256,
    }
    next_state = {**state_core, "state_digest": _digest(state_core)}
    snapshot_core = {
        "schema_version": SNAPSHOT_SCHEMA,
        "matrix_id": manifest["matrix_id"],
        "source_sha": source_sha,
        "run_id": str(run_id),
        "status": overall,
        "expected_cell_count": expected_cells,
        "verified_cell_count": verified_cells,
        "blocked_cell_count": blocked_cells,
        "expected_lane_count": expected_lanes,
        "reported_lane_count": len(lane_rows),
        "symbols": list(manifest["symbols"]),
        "timeframes": list(manifest["timeframes"]),
        "families": list(manifest["families"]),
        "cycle": cycle_rows,
        "lanes": sorted(lane_rows, key=lambda row: (row["symbol"], row["timeframe"], row["family"])),
        "state_digest": next_state["state_digest"],
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "data_mode": data_mode,
        "dataset_sha256": dataset_sha256,
    }
    snapshot = {**snapshot_core, "snapshot_digest": _digest(snapshot_core)}
    return next_state, snapshot


def verify_snapshot(value: Mapping[str, Any]) -> dict[str, Any]:
    core = dict(value)
    claimed = core.pop("snapshot_digest", None)
    checks = {
        "schema": core.get("schema_version") == SNAPSHOT_SCHEMA,
        "digest": claimed == _digest(core),
        "paper_only": core.get("paper_only") is True,
        "live_disabled": core.get("live_trading_authority") is False,
        "credentials_disabled": core.get("private_credentials_used") is False,
        "promotion_disabled": core.get("automatic_strategy_promotion") is False,
        "risk_final": core.get("deterministic_risk_final_authority") is True,
        "matrix_shape": core.get("expected_cell_count") == 6 and core.get("expected_lane_count") == 18,
    }
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--now-ms", type=int)
    parser.add_argument("--replay-archive-root", type=Path)
    parser.add_argument("--archive-sha256")
    args = parser.parse_args()
    if args.now_ms is None:
        import time
        args.now_ms = int(time.time() * 1000)
    manifest = load_manifest(args.manifest)
    state_path = args.state_root / "matrix-state.json"
    state = load_state(state_path, manifest)
    runner = _default_runner
    now_resolver = None
    data_mode = "public_api"
    dataset_sha256 = None
    if bool(args.replay_archive_root) != bool(args.archive_sha256):
        raise DemoStrategyMatrixError(
            "replay archive root and archive digest must be supplied together"
        )
    if args.replay_archive_root:
        from nexus_demo_archive_replay import (
            build_archive_dataset_fetcher,
            next_replay_now_ms,
        )
        from nexus_strategy_paper_supervisor import run_once

        archive_fetcher = build_archive_dataset_fetcher(
            args.replay_archive_root, archive_sha256=args.archive_sha256
        )

        def replay_runner(**kwargs: Any) -> Mapping[str, Any]:
            return run_once(dataset_fetcher=archive_fetcher, **kwargs)

        runner = replay_runner
        now_resolver = lambda symbol, timeframe, previous, limit: next_replay_now_ms(
            args.replay_archive_root, symbol, timeframe, previous, limit
        )
        data_mode = "verified_immutable_archive_replay"
        dataset_sha256 = args.archive_sha256
    next_state, snapshot = run_matrix_cycle(
        manifest=manifest, state=state, state_root=args.state_root,
        source_sha=args.source_sha, run_id=args.run_id, now_ms=args.now_ms,
        runner=runner, now_resolver=now_resolver, data_mode=data_mode,
        dataset_sha256=dataset_sha256,
    )
    _atomic_json(state_path, next_state)
    _atomic_json(args.state_root / "demo" / "strategy-matrix.json", snapshot)
    print(json.dumps({
        "status": snapshot["status"],
        "verified_cells": snapshot["verified_cell_count"],
        "expected_cells": snapshot["expected_cell_count"],
        "reported_lanes": snapshot["reported_lane_count"],
        "expected_lanes": snapshot["expected_lane_count"],
        "snapshot_digest": snapshot["snapshot_digest"],
    }, sort_keys=True))
    return 0 if snapshot["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
