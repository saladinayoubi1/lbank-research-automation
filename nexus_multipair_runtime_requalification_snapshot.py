"""Fresh canonical Bybit snapshot transport for Multi-Pair runtime requalification.

The physical Bybit runner may be unable to reach Bybit public REST endpoints from its
network region. This module keeps data semantics unchanged: a GitHub-hosted job acquires
fresh canonical public Bybit REST closed candles, packages the verified 12-cell snapshot,
and a physical job re-binds those exact transported candles to the canonical registry
before independently re-running Strategy Factory qualification.

The transported snapshot is distinct from the immutable historical Discovery archive.
It is Research/Paper scoped only and grants no Candidate, promotion, order, or Live
authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

import nexus_multipair_discovery_snapshot as rest_snapshot
import nexus_multipair_strategy_proposal_requalification as multipair_requal
import nexus_strategy_proposal_runtime_requalification as legacy_requal
from market_data_source_validator import load_and_validate
from phase5_data_binding import validate_canonical_dataset
from phase6_research_pipeline import bind_bybit_closed_dataset, run_research_job
from product_research_runtime import (
    COST_MODEL,
    KILL_CRITERIA,
    TIMEFRAMES,
    _public_mapping,
    _registry_path,
)


HISTORY_LIMIT = 240
MAX_SNAPSHOT_TRANSPORT_AGE_MS = 20 * 60 * 1000
TRANSPORT_ORIGIN = "digest_pinned_hosted_bybit_rest_snapshot"
INNER_ARCHIVE_NAME = "nexus-multipair-runtime-requalification-snapshot.zip"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]


class MultiPairRuntimeSnapshotError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairRuntimeSnapshotError("runtime snapshot input is unavailable") from exc
    if not isinstance(value, dict):
        raise MultiPairRuntimeSnapshotError("runtime snapshot input must be an object")
    return value


def verify_fresh_runtime_snapshot(
    root: str | Path,
    value: Mapping[str, Any],
    *,
    source_sha: str,
    now_ms: int,
    max_transport_age_ms: int = MAX_SNAPSHOT_TRANSPORT_AGE_MS,
) -> dict[str, Any]:
    checks = {
        "snapshot": False,
        "source": False,
        "role": False,
        "transport_age": False,
        "closed_candle_freshness": False,
    }
    try:
        source_sha = str(source_sha).strip().lower()
        if not _HEX40.fullmatch(source_sha):
            raise MultiPairRuntimeSnapshotError("source_sha must be an exact Git SHA")
        if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
            raise MultiPairRuntimeSnapshotError("now_ms must be a positive integer")
        if isinstance(max_transport_age_ms, bool) or not isinstance(max_transport_age_ms, int) or max_transport_age_ms <= 0:
            raise MultiPairRuntimeSnapshotError("max_transport_age_ms must be positive")

        verification = rest_snapshot.verify_snapshot(root, value)
        checks["snapshot"] = verification.get("decision") == "pass"
        checks["source"] = bool(value.get("source_sha") == source_sha)
        checks["role"] = bool(
            value.get("schema_version") == rest_snapshot.SCHEMA
            and value.get("history_limit") == HISTORY_LIMIT
            and value.get("cell_count") == 12
            and value.get("symbols") == list(rest_snapshot.SYMBOLS)
            and value.get("timeframes") == list(rest_snapshot.TIMEFRAME_NAMES)
            and value.get("data_origin") == "canonical_public_bybit_closed_candles"
            and value.get("research_only") is True
            and value.get("paper_execution_started") is False
            and value.get("live_trading_authority") is False
            and value.get("private_credentials_used") is False
            and value.get("automatic_strategy_promotion") is False
            and value.get("silent_exchange_substitution") is False
        )
        as_of_ms = value.get("as_of_ms")
        checks["transport_age"] = bool(
            isinstance(as_of_ms, int)
            and not isinstance(as_of_ms, bool)
            and 0 <= now_ms - as_of_ms <= max_transport_age_ms
        )
        cells = value.get("cells")
        fresh = isinstance(cells, list) and len(cells) == 12
        if fresh:
            for cell in cells:
                if not isinstance(cell, Mapping):
                    fresh = False
                    break
                timeframe = str(cell.get("timeframe", ""))
                spec = TIMEFRAMES.get(timeframe)
                if spec is None:
                    fresh = False
                    break
                step_ms = int(spec["step_ms"])
                last_open_ms = cell.get("last_open_time_ms")
                if not isinstance(last_open_ms, int) or isinstance(last_open_ms, bool):
                    fresh = False
                    break
                expected_at_acquisition = ((int(as_of_ms) - step_ms) // step_ms) * step_ms
                closed_age_ms = now_ms - (last_open_ms + step_ms)
                if last_open_ms != expected_at_acquisition or not 0 <= closed_age_ms <= 2 * step_ms:
                    fresh = False
                    break
        checks["closed_candle_freshness"] = bool(fresh)
    except Exception:
        pass
    evidence = {
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
        "snapshot_digest": value.get("snapshot_digest"),
    }
    return evidence


def collect_fresh_runtime_snapshot(
    *,
    output_root: str | Path,
    source_sha: str,
    now_ms: int,
    fetcher=rest_snapshot.fetch_bind_bybit_dataset,
) -> dict[str, Any]:
    result = rest_snapshot.collect_snapshot(
        output_root=output_root,
        source_sha=source_sha,
        now_ms=now_ms,
        limit=HISTORY_LIMIT,
        fetcher=fetcher,
    )
    verification = verify_fresh_runtime_snapshot(
        output_root,
        result,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    if verification["decision"] != "pass":
        raise MultiPairRuntimeSnapshotError("fresh runtime snapshot verification failed after acquisition")
    return result


def deterministic_pack(root: str | Path, output: str | Path) -> str:
    source = Path(root).resolve()
    manifest_path = source / "snapshot-manifest.json"
    manifest = _load_json(manifest_path)
    if rest_snapshot.verify_snapshot(source, manifest).get("decision") != "pass":
        raise MultiPairRuntimeSnapshotError("runtime snapshot verifier rejected before pack")
    if manifest.get("history_limit") != HISTORY_LIMIT:
        raise MultiPairRuntimeSnapshotError("runtime snapshot pack requires exactly 240 rows per cell")
    files = [manifest_path] + [
        source / "bybit_market" / symbol / f"{timeframe}.parquet"
        for symbol in rest_snapshot.SYMBOLS
        for timeframe in rest_snapshot.TIMEFRAME_NAMES
    ]
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise MultiPairRuntimeSnapshotError("runtime snapshot pack surface is incomplete")
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(files, key=lambda item: item.relative_to(source).as_posix()):
            name = path.relative_to(source).as_posix()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return _sha256_file(target)


def _cell(value: Mapping[str, Any], symbol: str, timeframe: str) -> Mapping[str, Any]:
    rows = [
        row for row in value.get("cells", [])
        if isinstance(row, Mapping) and row.get("symbol") == symbol and row.get("timeframe") == timeframe
    ]
    if len(rows) != 1:
        raise MultiPairRuntimeSnapshotError(f"runtime snapshot cell is not unique: {symbol}/{timeframe}")
    return rows[0]


def bind_transported_runtime_dataset(
    root: str | Path,
    snapshot: Mapping[str, Any],
    *,
    symbol: str,
    timeframe: str,
) -> dict[str, Any]:
    if symbol not in rest_snapshot.SYMBOLS or timeframe not in rest_snapshot.TIMEFRAME_NAMES:
        raise MultiPairRuntimeSnapshotError("runtime snapshot request is outside the trusted surface")
    cell = _cell(snapshot, symbol, timeframe)
    path = Path(root).resolve() / "bybit_market" / symbol / f"{timeframe}.parquet"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 20_000_000:
        raise MultiPairRuntimeSnapshotError("transported runtime frame is missing or unsafe")
    frame = pd.read_parquet(path)
    if frame.columns.tolist() != _REQUIRED_COLUMNS or len(frame) != HISTORY_LIMIT:
        raise MultiPairRuntimeSnapshotError("transported runtime frame shape mismatch")
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")

    registry = load_and_validate(_registry_path())
    mapping, source = _public_mapping(registry, symbol, timeframe)
    spec = TIMEFRAMES[timeframe]
    candles = []
    for row in frame.itertuples(index=False):
        candles.append({
            "source": "Bybit",
            "market_type": "spot",
            "symbol": source["symbol"],
            "interval": spec["interval"],
            "open_time_ms": int(pd.Timestamp(row.timestamp).value // 1_000_000),
            "open": str(row.open),
            "high": str(row.high),
            "low": str(row.low),
            "close": str(row.close),
            "volume": str(row.volume),
            "closed": True,
        })
    dataset = bind_bybit_closed_dataset(
        candles,
        canonical_symbol=mapping["canonical_symbol"],
        source_symbol=source["symbol"],
        interval=spec["interval"],
        mapping_policy_version=mapping["mapping_policy_version"],
    )
    artifact = validate_canonical_dataset(dataset, registry_path=_registry_path())
    if (
        artifact.get("row_count") != HISTORY_LIMIT
        or int(artifact["rows"][0]["open_time_ms"]) != cell.get("first_open_time_ms")
        or int(artifact["rows"][-1]["open_time_ms"]) != cell.get("last_open_time_ms")
    ):
        raise MultiPairRuntimeSnapshotError("re-bound runtime dataset window mismatch")
    return artifact


class RuntimeSnapshotEvaluator:
    def __init__(self, root: str | Path, snapshot: Mapping[str, Any], *, source_sha: str, now_ms: int) -> None:
        self.root = Path(root).resolve()
        self.snapshot = dict(snapshot)
        self.source_sha = str(source_sha).strip().lower()
        self.now_ms = int(now_ms)
        verification = verify_fresh_runtime_snapshot(
            self.root,
            self.snapshot,
            source_sha=self.source_sha,
            now_ms=self.now_ms,
        )
        if verification["decision"] != "pass":
            raise MultiPairRuntimeSnapshotError("transported runtime snapshot is not fresh and verified")

    def __call__(
        self,
        proposal: Mapping[str, Any],
        symbol: str,
        source_sha: str,
        now_ms: int,
        state_root: Path,
    ) -> dict[str, Any]:
        del state_root
        if str(source_sha).strip().lower() != self.source_sha or int(now_ms) != self.now_ms:
            raise MultiPairRuntimeSnapshotError("runtime evaluator identity does not match verified snapshot consumption")
        timeframe = str(proposal.get("timeframe", ""))
        dataset = bind_transported_runtime_dataset(
            self.root,
            self.snapshot,
            symbol=symbol,
            timeframe=timeframe,
        )
        family = str(proposal["family"])
        variant_id = str(proposal["variant_id"])
        job_kwargs = {
            "hypothesis": (
                "Independent runtime requalification from a fresh digest-pinned canonical Bybit "
                f"snapshot for proposal {proposal['proposal_digest']}; no profitability or promotion claim."
            ),
            "family": family,
            "strategy_version": f"{family}-runtime-requalification-{variant_id}",
            "strategy_config": dict(proposal["strategy_config"]),
            "code_sha": self.source_sha,
            "cost_model": COST_MODEL,
            "kill_criteria": KILL_CRITERIA,
        }
        job = run_research_job(dataset, **job_kwargs)
        replay = run_research_job(dataset, **job_kwargs)
        binding = str(dataset.get("binding_sha256", ""))
        legacy_requal._validate_runtime_job(
            job, dataset_sha=binding, source_sha=self.source_sha, proposal=proposal
        )
        legacy_requal._validate_runtime_job(
            replay, dataset_sha=binding, source_sha=self.source_sha, proposal=proposal
        )
        if legacy_requal._canonical(job) != legacy_requal._canonical(replay):
            raise MultiPairRuntimeSnapshotError("transported runtime qualification replay is not deterministic")
        qualification = job.get("qualification")
        if not isinstance(qualification, Mapping):
            raise MultiPairRuntimeSnapshotError("transported runtime qualification is missing")
        status = qualification.get("status")
        if status not in {"paper_candidate", "killed"}:
            raise MultiPairRuntimeSnapshotError("transported runtime qualification status is invalid")
        reasons = list(qualification.get("kill_reasons", []))
        return {
            "symbol": symbol,
            "family": family,
            "timeframe": timeframe,
            "variant_id": variant_id,
            "runtime_dataset_binding_sha256": binding,
            "runtime_last_open_time_ms": dataset["rows"][-1]["open_time_ms"],
            "qualification_status": status,
            "pipeline_digest": job.get("pipeline_digest"),
            "qualification_digest": qualification.get("qualification_digest"),
            "kill_reasons": reasons,
            "deterministic_replay_verified": True,
            "data_origin": "canonical_public_bybit_runtime",
            "runtime_data_transport": TRANSPORT_ORIGIN,
            "runtime_snapshot_digest": self.snapshot["snapshot_digest"],
            "runtime_snapshot_as_of_ms": self.snapshot["as_of_ms"],
            "closed_candle_finality_verified": True,
            "paper_only": True,
            "live_trading_authority": False,
            "paper_execution_started": False,
            "automatic_strategy_promotion": False,
            "deterministic_risk_final_authority": True,
        }


def run_requalification_from_snapshot(
    discovery_path: str | Path,
    queue_path: str | Path,
    *,
    snapshot_root: str | Path,
    source_sha: str,
    state_root: str | Path,
    output: str | Path,
    now_ms: int,
) -> dict[str, Any]:
    discovery = _load_json(discovery_path)
    queue = _load_json(queue_path)
    snapshot = _load_json(Path(snapshot_root) / "snapshot-manifest.json")
    evaluator = RuntimeSnapshotEvaluator(
        snapshot_root,
        snapshot,
        source_sha=source_sha,
        now_ms=now_ms,
    )
    result = multipair_requal.build_requalification(
        discovery,
        queue,
        source_sha=source_sha,
        discovery_source_sha=source_sha,
        state_root=state_root,
        now_ms=now_ms,
        evaluator=evaluator,
    )
    core = dict(result)
    core.pop("requalification_digest", None)
    historical_digest = str(discovery.get("dataset_snapshot_sha256", ""))
    runtime_digest = str(snapshot.get("snapshot_digest", ""))
    core.update({
        "runtime_data_transport": TRANSPORT_ORIGIN,
        "runtime_snapshot_digest": runtime_digest,
        "runtime_snapshot_as_of_ms": snapshot["as_of_ms"],
        "runtime_snapshot_history_limit": snapshot["history_limit"],
        "runtime_snapshot_distinct_from_discovery": bool(
            _HEX64.fullmatch(runtime_digest)
            and _HEX64.fullmatch(historical_digest)
            and runtime_digest != historical_digest
        ),
        "historical_discovery_snapshot_reused": False,
    })
    result = {**core, "requalification_digest": multipair_requal._digest(core)}
    verification = multipair_requal.verify_requalification(result)
    if verification["decision"] != "pass":
        raise MultiPairRuntimeSnapshotError("snapshot-backed Multi-Pair requalification verifier rejected evidence")
    if core["runtime_snapshot_distinct_from_discovery"] is not True:
        raise MultiPairRuntimeSnapshotError("fresh runtime snapshot must be distinct from historical Discovery evidence")
    for row in result.get("proposal_results", []):
        for evaluation in row.get("runtime_evaluations", []):
            if (
                evaluation.get("runtime_data_transport") != TRANSPORT_ORIGIN
                or evaluation.get("runtime_snapshot_digest") != runtime_digest
                or evaluation.get("runtime_snapshot_as_of_ms") != snapshot["as_of_ms"]
            ):
                raise MultiPairRuntimeSnapshotError("runtime evaluation is not bound to the transported fresh snapshot")
    target = Path(output).resolve()
    _atomic_json(target, result)
    _atomic_json(target.with_name("verification.json"), verification)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire = subparsers.add_parser("acquire")
    acquire.add_argument("--output-root", type=Path, required=True)
    acquire.add_argument("--archive-output", type=Path, required=True)
    acquire.add_argument("--digest-output", type=Path, required=True)
    acquire.add_argument("--source-sha", required=True)
    acquire.add_argument("--now-ms", type=int, required=True)

    requalify = subparsers.add_parser("requalify")
    requalify.add_argument("--snapshot-root", type=Path, required=True)
    requalify.add_argument("--discovery", type=Path, required=True)
    requalify.add_argument("--queue", type=Path, required=True)
    requalify.add_argument("--source-sha", required=True)
    requalify.add_argument("--state-root", type=Path, required=True)
    requalify.add_argument("--output", type=Path, required=True)
    requalify.add_argument("--now-ms", type=int, required=True)

    args = parser.parse_args()
    if args.command == "acquire":
        snapshot = collect_fresh_runtime_snapshot(
            output_root=args.output_root,
            source_sha=args.source_sha,
            now_ms=args.now_ms,
        )
        archive_sha = deterministic_pack(args.output_root, args.archive_output)
        args.digest_output.parent.mkdir(parents=True, exist_ok=True)
        args.digest_output.write_text(archive_sha + "\n", encoding="ascii")
        print(json.dumps({
            "decision": "pass",
            "snapshot_digest": snapshot["snapshot_digest"],
            "snapshot_as_of_ms": snapshot["as_of_ms"],
            "archive_sha256": archive_sha,
            "cells": snapshot["cell_count"],
            "history_limit": snapshot["history_limit"],
        }, sort_keys=True))
        return 0

    result = run_requalification_from_snapshot(
        args.discovery,
        args.queue,
        snapshot_root=args.snapshot_root,
        source_sha=args.source_sha,
        state_root=args.state_root,
        output=args.output,
        now_ms=args.now_ms,
    )
    print(json.dumps({
        "decision": "pass",
        "status": result["status"],
        "proposal_count": result["proposal_count"],
        "qualified": result["qualified_for_review_count"],
        "rejected": result["rejected_count"],
        "runtime_snapshot_digest": result["runtime_snapshot_digest"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
