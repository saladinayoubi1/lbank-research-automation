"""Persistent Supervisor cycle for canonical Strategy research and isolated Paper.

The runtime is intentionally bounded to public Bybit data and Paper-only state.
Each strategy family receives its own fenced task and isolated Paper portfolio.
No result is complete until the independent ledger verifier accepts it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import phase5_attempts as attempts
from phase6_research_pipeline import fetch_bind_bybit_dataset
from product_research_runtime import ProductResearchRuntime, STRATEGY_PRESETS, TIMEFRAMES
from product_runtime import ProductRuntime

SCHEMA = "nexus.strategy-paper-supervisor.v1"
VERIFICATION_SCHEMA = "nexus.strategy-paper-supervisor-verification.v1"
DEFAULT_STATE_ROOT = Path(os.environ.get("NEXUS_STATE_DIR", ".nexus-runtime")) / "strategy-paper"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CANONICAL_SYMBOLS = {"BTCUSDT": "BTC/USDT", "ETHUSDT": "ETH/USDT"}
DatasetFetcher = Callable[..., Mapping[str, Any]]
ResearchFactory = Callable[[ProductRuntime, str, Mapping[str, Any], int], ProductResearchRuntime]


class StrategyPaperSupervisorError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyPaperSupervisorError("supervisor evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False
    ).encode("utf-8") + b"\n")
    os.replace(temporary, path)


def _source_sha(value: str) -> str:
    value = str(value).strip().lower()
    if not _SHA_RE.fullmatch(value):
        raise StrategyPaperSupervisorError("source_sha must be a 40-character Git SHA")
    return value


def _families(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(dict.fromkeys(str(value).strip() for value in values))
    if not result or any(value not in STRATEGY_PRESETS for value in result):
        raise StrategyPaperSupervisorError("strategy families must be unique approved families")
    return result


def _task(family: str, source_sha: str, dataset_sha: str) -> dict[str, Any]:
    task_id = f"STRATEGY-PAPER-{family.upper().replace('_', '-')}"
    core = {
        "mission_id": "nexus-strategy-paper-supervisor",
        "mission_revision": 1,
        "policy_version": "nexus-paper-only-v1",
        "id": task_id,
        "authority": 2,
        "family": family,
        "source_sha": source_sha,
        "dataset_sha": dataset_sha,
    }
    return {**core, "spec_digest": _digest(core), "status": "QUEUED"}


def _default_research_factory(
    runtime: ProductRuntime, source_sha: str, dataset: Mapping[str, Any], now_ms: int
) -> ProductResearchRuntime:
    return ProductResearchRuntime(
        runtime,
        source_sha=source_sha,
        dataset_fetcher=lambda **_: deepcopy(dict(dataset)),
        clock_ms=lambda: now_ms,
    )


def verify_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    """Independently validate the durable producer ledger and authority boundary."""
    checks: dict[str, bool] = {
        "schema": ledger.get("schema_version") == SCHEMA,
        "paper_only": ledger.get("paper_only") is True,
        "live_disabled": ledger.get("live_trading_authority") is False,
        "source_bound": bool(_SHA_RE.fullmatch(str(ledger.get("source_sha", "")))),
    }
    rows = ledger.get("tasks")
    checks["tasks_present"] = isinstance(rows, list) and bool(rows)
    seen: set[str] = set()
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            valid = isinstance(row, Mapping)
            task_id = row.get("task_id") if valid else None
            valid = bool(valid and isinstance(task_id, str) and task_id not in seen)
            if isinstance(task_id, str):
                seen.add(task_id)
            producer = row.get("producer_result", {}) if valid else {}
            evidence = producer.get("evidence", {}) if isinstance(producer, Mapping) else {}
            unsigned_row = dict(row) if valid else {}
            recorded_digest = unsigned_row.pop("evidence_digest", None)
            valid = bool(
                valid
                and recorded_digest == _digest(unsigned_row)
                and producer.get("outcome") == "success"
                and row.get("attempt_id") == producer.get("attempt_id")
                and row.get("lease_id") == producer.get("lease_id")
                and row.get("worker_id") == producer.get("worker_id")
                and row.get("status") == evidence.get("status")
                and evidence.get("source_sha") == ledger.get("source_sha")
                and evidence.get("dataset_binding_sha256")
                    == ledger.get("dataset_binding_sha256")
                and row.get("paper_only") is True
                and row.get("live_trading_authority") is False
                and row.get("status") in {
                    "paper_executed", "qualification_killed", "no_open_signal",
                    "position_exists", "risk_rejected",
                }
            )
            if row.get("status") == "paper_executed":
                paper = row.get("paper_result", {})
                valid = bool(
                    valid and paper.get("accepted") is True
                    and paper.get("risk", {}).get("allowed") is True
                    and isinstance(paper.get("execution"), Mapping)
                )
            checks[f"task_{index}"] = valid
    passed = all(checks.values())
    core = {
        "schema_version": VERIFICATION_SCHEMA,
        "decision": "pass" if passed else "reject",
        "verifier": "strategy-paper-independent-verifier",
        "trust_domain": "independent-contract-verifier",
        "checks": checks,
        "ledger_digest": _digest(dict(ledger)),
    }
    return {**core, "verification_digest": _digest(core)}


def run_once(
    *,
    source_sha: str,
    state_root: Path = DEFAULT_STATE_ROOT,
    symbol: str = "BTCUSDT",
    timeframe: str = "minute15",
    families: Sequence[str] = ("momentum", "trend_breakout", "mean_reversion"),
    limit: int = 240,
    now_ms: int | None = None,
    dataset_fetcher: DatasetFetcher = fetch_bind_bybit_dataset,
    research_factory: ResearchFactory = _default_research_factory,
) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    families = _families(families)
    symbol = str(symbol).strip().upper()
    canonical_symbol = _CANONICAL_SYMBOLS.get(symbol)
    if canonical_symbol is None:
        raise StrategyPaperSupervisorError("unsupported matrix symbol")
    if timeframe not in TIMEFRAMES:
        raise StrategyPaperSupervisorError("unsupported timeframe")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 30 <= limit <= 1000:
        raise StrategyPaperSupervisorError("limit must be between 30 and 1000")
    if now_ms is None:
        import time
        now_ms = int(time.time() * 1000)
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise StrategyPaperSupervisorError("now_ms must be a positive integer")

    spec = TIMEFRAMES[timeframe]
    try:
        dataset = dict(dataset_fetcher(
            canonical_symbol=canonical_symbol,
            source_symbol=symbol,
            interval=spec["interval"],
            now_ms=now_ms,
            start_time_ms=now_ms - limit * int(spec["step_ms"]),
            end_time_ms=now_ms,
            limit=limit,
        ))
        dataset_sha = str(dataset["binding_sha256"])
    except Exception as exc:
        raise StrategyPaperSupervisorError(f"canonical Bybit dataset unavailable: {exc}") from exc

    state_root = state_root.resolve()
    rows: list[dict[str, Any]] = []
    for family in families:
        task = _task(family, source_sha, dataset_sha)
        worker_id = f"strategy-worker-{family}"
        lease_id = "lease-" + _digest({"task": task["id"], "dataset": dataset_sha})[:32]
        task.update({"status": "LEASED", "assigned_worker": worker_id, "lease_id": lease_id})
        attempt = attempts.begin_attempt(
            task, worker_id=worker_id, lease_id=lease_id,
            source_sha=hashlib.sha256(("git-object:" + source_sha).encode("ascii")).hexdigest(),
            state_generation=1,
        )
        runtime = ProductRuntime(state_root / "portfolios" / family)
        research = research_factory(runtime, source_sha, dataset, now_ms)
        try:
            research_result = research.run_research(
                symbol=symbol, timeframe=timeframe, family=family, limit=limit
            )
            if research_result.get("qualification", {}).get("status") == "paper_candidate":
                paper_result = research.auto_paper()
                status = str(paper_result.get("status"))
            else:
                paper_result = {
                    "paper_only": True, "live_trading_authority": False,
                    "accepted": False, "status": "qualification_killed",
                    "kill_reasons": research_result.get("qualification", {}).get("kill_reasons", []),
                }
                status = "qualification_killed"
            evidence = {
                "family": family,
                "source_sha": source_sha,
                "dataset_binding_sha256": dataset_sha,
                "qualification_digest": research_result.get("qualification", {}).get("qualification_digest"),
                "status": status,
                "paper_only": True,
                "live_trading_authority": False,
            }
            producer_result = attempts.build_result(attempt, outcome="success", evidence=evidence)
            attempts.accept_result(task, producer_result)
        except Exception as exc:
            raise StrategyPaperSupervisorError(f"{family} task failed closed: {exc}") from exc
        row = {
            "task_id": task["id"], "family": family, "lease_id": lease_id,
            "attempt_id": attempt["attempt_id"], "worker_id": worker_id,
            "producer_trust_domain": "strategy-research-runtime",
            "status": status, "paper_only": True, "live_trading_authority": False,
            "producer_result": producer_result,
            "research_result": research_result,
            "paper_result": paper_result,
            "portfolio_snapshot": runtime.paper_snapshot(),
        }
        row["evidence_digest"] = _digest(row)
        rows.append(row)
        _atomic_json(state_root / "evidence" / f"{family}.json", row)

    ledger_core = {
        "schema_version": SCHEMA, "source_sha": source_sha,
        "dataset_binding_sha256": dataset_sha, "symbol": symbol,
        "timeframe": timeframe, "paper_only": True,
        "live_trading_authority": False, "tasks": rows,
        "resource_utilization": [
            {"resource": row["worker_id"], "task_id": row["task_id"], "classification": "EXECUTED"}
            for row in rows
        ],
    }
    verification = verify_ledger(ledger_core)
    if verification["decision"] != "pass":
        raise StrategyPaperSupervisorError("independent verifier rejected supervisor ledger")
    ledger = {**ledger_core, "verification": verification, "final_status": "VERIFIED"}
    ledger["ledger_digest"] = _digest(ledger)
    _atomic_json(state_root / "supervisor-ledger.json", ledger)
    return ledger


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", choices=sorted(TIMEFRAMES), default="minute15")
    parser.add_argument("--family", action="append", dest="families")
    parser.add_argument("--limit", type=int, default=240)
    args = parser.parse_args()
    ledger = run_once(
        source_sha=args.source_sha, state_root=args.state_root, symbol=args.symbol,
        timeframe=args.timeframe, families=args.families or tuple(STRATEGY_PRESETS), limit=args.limit,
    )
    print(json.dumps({
        "final_status": ledger["final_status"], "ledger_digest": ledger["ledger_digest"],
        "dataset_binding_sha256": ledger["dataset_binding_sha256"],
        "tasks": [{"task_id": row["task_id"], "status": row["status"]} for row in ledger["tasks"]],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
