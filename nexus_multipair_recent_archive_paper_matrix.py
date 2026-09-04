"""Run the four-symbol Demo Paper matrix from one verified recent Bybit archive snapshot.

This adapter exists for physical continuity proof when the runner cannot reach Bybit
public REST from its region. It does not change exchange, market, symbol, timeframe,
strategy, Risk, or Paper authority. The transported snapshot is independently verified
before use, each requested Supervisor dataset is re-bound through the canonical registry,
and the matrix clock is pinned to the snapshot's exact ``data_as_of_ms`` boundary.

No Live/private-credential/order/promotion authority is introduced here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from nexus_demo_strategy_matrix import _atomic_json, run_matrix_cycle
from nexus_multipair_demo_strategy_matrix import (
    MultiPairMatrixError,
    load_manifest,
    load_or_migrate_state,
    verify_v2_snapshot,
)
import nexus_multipair_recent_archive_runtime_snapshot as recent
import nexus_multipair_runtime_requalification_snapshot as runtime_snapshot
from nexus_strategy_paper_supervisor import run_once as run_supervisor_once
from product_research_runtime import TIMEFRAMES


class MultiPairRecentArchivePaperError(RuntimeError):
    pass


def _load_json(path: Path) -> dict[str, Any]:
    target = path.resolve()
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 5_000_000:
        raise MultiPairRecentArchivePaperError("recent archive Paper input is unavailable or unsafe")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairRecentArchivePaperError("recent archive Paper input is unreadable") from exc
    if not isinstance(value, dict):
        raise MultiPairRecentArchivePaperError("recent archive Paper input is not an object")
    return value


def load_verified_snapshot(
    snapshot_root: str | Path,
    *,
    expected_snapshot_digest: str,
    source_sha: str,
    now_ms: int,
) -> dict[str, Any]:
    root = Path(snapshot_root).resolve()
    value = _load_json(root / "snapshot-manifest.json")
    expected = str(expected_snapshot_digest).strip().lower()
    if value.get("snapshot_digest") != expected:
        raise MultiPairRecentArchivePaperError("recent archive snapshot digest mismatch")
    verification = recent.verify_recent_archive_runtime_snapshot(
        root, value, source_sha=source_sha, now_ms=now_ms
    )
    if verification.get("decision") != "pass":
        raise MultiPairRecentArchivePaperError("recent archive snapshot failed independent verification")
    if (
        value.get("history_limit") != recent.HISTORY_LIMIT
        or value.get("cell_count") != 12
        or value.get("runtime_requalification_recency_verified") is not True
        or value.get("live_freshness_claimed") is not False
        or value.get("research_only") is not True
        or value.get("paper_execution_started") is not False
        or value.get("live_trading_authority") is not False
        or value.get("private_credentials_used") is not False
        or value.get("real_exchange_orders") is not False
        or value.get("automatic_strategy_promotion") is not False
        or value.get("issue_984_state_touched") is not False
    ):
        raise MultiPairRecentArchivePaperError("recent archive snapshot authority boundary mismatch")
    return value


def build_snapshot_dataset_fetcher(
    snapshot_root: str | Path,
    snapshot: Mapping[str, Any],
) -> Callable[..., Mapping[str, Any]]:
    root = Path(snapshot_root).resolve()
    interval_to_timeframe = {
        str(spec["interval"]): name
        for name, spec in TIMEFRAMES.items()
        if name in {"minute15", "hour1", "hour4"}
    }

    def fetcher(
        *,
        canonical_symbol: str,
        source_symbol: str,
        interval: str,
        now_ms: int,
        start_time_ms: int,
        end_time_ms: int,
        limit: int,
        **_kwargs: Any,
    ) -> Mapping[str, Any]:
        symbol = str(source_symbol).strip().upper()
        timeframe = interval_to_timeframe.get(str(interval))
        if timeframe is None or symbol not in recent.SYMBOLS:
            raise MultiPairRecentArchivePaperError("recent archive Paper dataset request escaped the trusted surface")
        spec = TIMEFRAMES[timeframe]
        step_ms = int(spec["step_ms"])
        if (
            isinstance(now_ms, bool)
            or not isinstance(now_ms, int)
            or end_time_ms + step_ms > now_ms
            or limit != recent.HISTORY_LIMIT
        ):
            raise MultiPairRecentArchivePaperError("recent archive Paper dataset request is not a closed 240-row window")
        dataset = runtime_snapshot.bind_transported_runtime_dataset(
            root, snapshot, symbol=symbol, timeframe=timeframe
        )
        rows = dataset.get("rows")
        if (
            dataset.get("instrument") != canonical_symbol
            or dataset.get("source") != "Bybit"
            or dataset.get("source_symbol") != symbol
            or str(dataset.get("interval")) != str(interval)
            or dataset.get("paper_only") is not True
            or dataset.get("row_count") != limit
            or not isinstance(rows, list)
            or len(rows) != limit
            or int(rows[0]["open_time_ms"]) != start_time_ms
            or int(rows[-1]["open_time_ms"]) != end_time_ms
        ):
            raise MultiPairRecentArchivePaperError("recent archive Paper dataset window or canonical binding mismatch")
        return dataset

    return fetcher


def run_recent_archive_paper_cycle(
    *,
    manifest_path: str | Path,
    legacy_manifest_path: str | Path,
    state_path: str | Path,
    state_root: str | Path,
    snapshot_root: str | Path,
    expected_snapshot_digest: str,
    source_sha: str,
    run_id: str,
    now_ms: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairRecentArchivePaperError("now_ms must be a positive integer")
    manifest = load_manifest(manifest_path)
    state, migration = load_or_migrate_state(
        state_path, manifest, legacy_manifest_path=legacy_manifest_path
    )
    snapshot = load_verified_snapshot(
        snapshot_root,
        expected_snapshot_digest=expected_snapshot_digest,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    data_as_of_ms = snapshot.get("data_as_of_ms")
    if isinstance(data_as_of_ms, bool) or not isinstance(data_as_of_ms, int) or data_as_of_ms <= 0:
        raise MultiPairRecentArchivePaperError("recent archive data_as_of_ms is invalid")

    dataset_fetcher = build_snapshot_dataset_fetcher(snapshot_root, snapshot)

    def runner(**kwargs: Any) -> Mapping[str, Any]:
        return run_supervisor_once(dataset_fetcher=dataset_fetcher, **kwargs)

    def now_resolver(symbol: str, timeframe: str, previous_open_ms: int, history_limit: int) -> int:
        if symbol not in recent.SYMBOLS or timeframe not in recent.TIMEFRAMES:
            raise MultiPairRecentArchivePaperError("matrix clock request escaped the recent archive surface")
        if history_limit != recent.HISTORY_LIMIT:
            raise MultiPairRecentArchivePaperError("matrix history limit diverged from recent archive snapshot")
        step_ms = int(TIMEFRAMES[timeframe]["step_ms"])
        last_archive_open = data_as_of_ms - step_ms
        if previous_open_ms > last_archive_open:
            raise MultiPairRecentArchivePaperError("durable matrix cursor is ahead of verified archive evidence")
        return data_as_of_ms

    next_state, matrix_snapshot = run_matrix_cycle(
        manifest=manifest,
        state=state,
        state_root=state_root,
        source_sha=source_sha,
        run_id=run_id,
        now_ms=now_ms,
        runner=runner,
        now_resolver=now_resolver,
        data_mode=recent.TRANSPORT_ORIGIN,
        dataset_sha256=str(snapshot["snapshot_digest"]),
    )
    verification = verify_v2_snapshot(matrix_snapshot, manifest=manifest, state=next_state)
    if verification.get("decision") != "pass":
        raise MultiPairRecentArchivePaperError("recent archive Paper matrix failed independent v2 verification")
    if (
        matrix_snapshot.get("data_mode") != recent.TRANSPORT_ORIGIN
        or matrix_snapshot.get("dataset_sha256") != snapshot.get("snapshot_digest")
        or next_state.get("data_mode") != recent.TRANSPORT_ORIGIN
        or next_state.get("dataset_sha256") != snapshot.get("snapshot_digest")
        or matrix_snapshot.get("paper_only") is not True
        or matrix_snapshot.get("live_trading_authority") is not False
        or matrix_snapshot.get("private_credentials_used") is not False
        or matrix_snapshot.get("automatic_strategy_promotion") is not False
        or matrix_snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise MultiPairRecentArchivePaperError("recent archive Paper matrix evidence lost its transport or authority binding")
    return next_state, matrix_snapshot, migration


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("config/nexus-demo-strategy-matrix-v2.json"))
    parser.add_argument("--legacy-manifest", type=Path, default=Path("config/nexus-demo-strategy-matrix-v1.json"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--expected-snapshot-digest", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--now-ms", type=int, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--migration-evidence", type=Path)
    args = parser.parse_args()

    try:
        next_state, matrix_snapshot, migration = run_recent_archive_paper_cycle(
            manifest_path=args.manifest,
            legacy_manifest_path=args.legacy_manifest,
            state_path=args.state,
            state_root=args.state_root,
            snapshot_root=args.snapshot_root,
            expected_snapshot_digest=args.expected_snapshot_digest,
            source_sha=args.source_sha,
            run_id=args.run_id,
            now_ms=args.now_ms,
        )
        _atomic_json(args.state, next_state)
        _atomic_json(args.snapshot, matrix_snapshot)
        if migration is not None and args.migration_evidence is not None:
            _atomic_json(args.migration_evidence, migration)
    except (OSError, MultiPairMatrixError, MultiPairRecentArchivePaperError) as exc:
        parser.exit(1, f"NEXUS recent-archive multi-pair Paper matrix failed closed: {exc}\n")

    print(json.dumps({
        "status": matrix_snapshot["status"],
        "expected_cell_count": matrix_snapshot["expected_cell_count"],
        "expected_lane_count": matrix_snapshot["expected_lane_count"],
        "data_mode": matrix_snapshot["data_mode"],
        "dataset_sha256": matrix_snapshot["dataset_sha256"],
        "migration_performed": migration is not None,
        "paper_only": matrix_snapshot["paper_only"],
        "live_trading_authority": matrix_snapshot["live_trading_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
