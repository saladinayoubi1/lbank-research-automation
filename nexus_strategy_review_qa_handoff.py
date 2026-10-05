"""Build a fail-closed QA-41 handoff from verified modern Strategy Finder review evidence.

This module does not create Candidate/Paper state, qualify a strategy, mutate a
registry, dispatch a worker, or execute Paper. It only converts exact
QUALIFIED_FOR_REVIEW evidence into deterministic independent-QA work intents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_strategy_proposal_runtime_requalification import (
    APPROVED_SYMBOLS,
    VERIFICATION_SCHEMA as REQUALIFICATION_VERIFICATION_SCHEMA,
    verify_requalification,
)

HANDOFF_SCHEMA = "nexus.strategy-review-qa-handoff.v1"
TASK_SCHEMA = "nexus.strategy-review-qa-task.v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class StrategyReviewQaHandoffError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyReviewQaHandoffError("QA handoff evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _load_json(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if target.is_symlink() or not target.is_file() or target.stat().st_size > 4_000_000:
        raise StrategyReviewQaHandoffError("QA handoff input is missing, linked, or oversized")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyReviewQaHandoffError("QA handoff input is unreadable") from exc
    if not isinstance(value, dict):
        raise StrategyReviewQaHandoffError("QA handoff input must be an object")
    return value


def _atomic_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _verify_inputs(
    requalification: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> None:
    computed = verify_requalification(requalification)
    if computed.get("decision") != "pass":
        raise StrategyReviewQaHandoffError("runtime requalification evidence failed verification")
    if (
        not isinstance(verification, Mapping)
        or verification.get("schema_version") != REQUALIFICATION_VERIFICATION_SCHEMA
        or verification != computed
    ):
        raise StrategyReviewQaHandoffError(
            "runtime requalification verification artifact is missing, stale, or mismatched"
        )
    source_sha = str(requalification.get("source_sha", ""))
    if not _HEX40.fullmatch(source_sha):
        raise StrategyReviewQaHandoffError("runtime requalification source SHA is invalid")
    if requalification.get("discovery_source_sha") != source_sha:
        raise StrategyReviewQaHandoffError("runtime requalification is not exact-source bound")
    if (
        requalification.get("paper_only") is not True
        or requalification.get("research_only") is not True
        or requalification.get("candidate_creation_authority") is not False
        or requalification.get("promotion_authority") is not False
        or requalification.get("paper_execution_started") is not False
        or requalification.get("automatic_strategy_promotion") is not False
        or requalification.get("live_trading_authority") is not False
    ):
        raise StrategyReviewQaHandoffError("runtime requalification authority boundary changed")


def _qa_task(
    row: Mapping[str, Any],
    *,
    source_sha: str,
    requalification_digest: str,
    verification_digest: str,
) -> dict[str, Any]:
    if row.get("verdict") != "QUALIFIED_FOR_REVIEW":
        raise StrategyReviewQaHandoffError("only QUALIFIED_FOR_REVIEW may enter QA-41 handoff")
    proposal_digest = str(row.get("proposal_digest", ""))
    result_digest = str(row.get("result_digest", ""))
    if not _HEX64.fullmatch(proposal_digest) or not _HEX64.fullmatch(result_digest):
        raise StrategyReviewQaHandoffError("QA handoff proposal identity is invalid")
    strategy_config = row.get("strategy_config")
    strategy_config_digest = str(row.get("strategy_config_digest", ""))
    if (
        not isinstance(strategy_config, Mapping)
        or not strategy_config
        or not _HEX64.fullmatch(strategy_config_digest)
        or strategy_config_digest != _digest(strategy_config)
    ):
        raise StrategyReviewQaHandoffError("QA handoff strategy config binding is invalid")
    evaluations = row.get("runtime_evaluations")
    if not isinstance(evaluations, list) or not evaluations:
        raise StrategyReviewQaHandoffError("QA handoff has no runtime evaluations")
    evidence: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for item in evaluations:
        if not isinstance(item, Mapping):
            raise StrategyReviewQaHandoffError("QA handoff runtime evaluation is malformed")
        symbol = str(item.get("symbol", ""))
        dataset_digest = str(item.get("runtime_dataset_binding_sha256", ""))
        pipeline_digest = str(item.get("pipeline_digest", ""))
        qualification_digest = str(item.get("qualification_digest", ""))
        last_open_time_ms = item.get("runtime_last_open_time_ms")
        if (
            not symbol
            or symbol in seen_symbols
            or not _HEX64.fullmatch(dataset_digest)
            or not _HEX64.fullmatch(pipeline_digest)
            or not _HEX64.fullmatch(qualification_digest)
            or isinstance(last_open_time_ms, bool)
            or not isinstance(last_open_time_ms, int)
            or last_open_time_ms <= 0
            or item.get("qualification_status") != "paper_candidate"
            or item.get("deterministic_replay_verified") is not True
            or item.get("closed_candle_finality_verified") is not True
            or item.get("paper_only") is not True
            or item.get("live_trading_authority") is not False
            or item.get("paper_execution_started") is not False
            or item.get("automatic_strategy_promotion") is not False
        ):
            raise StrategyReviewQaHandoffError("QA handoff runtime evaluation is not review eligible")
        seen_symbols.add(symbol)
        evidence.append(
            {
                "symbol": symbol,
                "dataset_binding_sha256": dataset_digest,
                "pipeline_digest": pipeline_digest,
                "qualification_digest": qualification_digest,
                "last_open_time_ms": last_open_time_ms,
            }
        )
    evidence.sort(key=lambda item: item["symbol"])
    if seen_symbols != set(APPROVED_SYMBOLS):
        raise StrategyReviewQaHandoffError("QA handoff must bind every approved runtime symbol")
    core = {
        "schema_version": TASK_SCHEMA,
        "id": f"STRATEGY-QA-{proposal_digest}",
        "task_kind": "strategy_review_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "source_sha": source_sha,
        "proposal_digest": proposal_digest,
        "proposal_result_digest": result_digest,
        "requalification_digest": requalification_digest,
        "requalification_verification_digest": verification_digest,
        "family": row.get("family"),
        "timeframe": row.get("timeframe"),
        "variant_id": row.get("variant_id"),
        "strategy_config": dict(strategy_config),
        "strategy_config_digest": strategy_config_digest,
        "runtime_evidence": evidence,
        "producer_role": "strategy-runtime-requalification",
        "required_verifier": "qa-verifier-agent",
        "research_only": True,
        "paper_only": True,
        "candidate_creation_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "task_digest": _digest(core)}


def build_handoff(
    requalification: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_inputs(requalification, verification)
    requalification_digest = str(requalification.get("requalification_digest", ""))
    verification_digest = str(verification.get("verification_digest", ""))
    if not _HEX64.fullmatch(requalification_digest) or not _HEX64.fullmatch(verification_digest):
        raise StrategyReviewQaHandoffError("QA handoff upstream digest is invalid")

    rows = requalification.get("proposal_results")
    if not isinstance(rows, list):
        raise StrategyReviewQaHandoffError("QA handoff proposal results are unavailable")
    tasks = [
        _qa_task(
            row,
            source_sha=str(requalification["source_sha"]),
            requalification_digest=requalification_digest,
            verification_digest=verification_digest,
        )
        for row in rows
        if isinstance(row, Mapping) and row.get("verdict") == "QUALIFIED_FOR_REVIEW"
    ]
    tasks.sort(key=lambda task: task["proposal_digest"])
    if len({task["id"] for task in tasks}) != len(tasks):
        raise StrategyReviewQaHandoffError("QA handoff task identity collision")
    core = {
        "schema_version": HANDOFF_SCHEMA,
        "source_sha": requalification["source_sha"],
        "requalification_digest": requalification_digest,
        "requalification_verification_digest": verification_digest,
        "status": "READY_FOR_QA" if tasks else "NO_WORK",
        "task_count": len(tasks),
        "tasks": tasks,
        "required_verifier": "qa-verifier-agent",
        "research_only": True,
        "paper_only": True,
        "candidate_creation_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "handoff_digest": _digest(core)}


def verify_handoff(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "authority": False,
        "tasks": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("handoff_digest", None)
        tasks = core.get("tasks")
        checks["schema"] = bool(
            core.get("schema_version") == HANDOFF_SCHEMA
            and _HEX40.fullmatch(str(core.get("source_sha", "")))
            and _HEX64.fullmatch(str(core.get("requalification_digest", "")))
            and _HEX64.fullmatch(str(core.get("requalification_verification_digest", "")))
            and core.get("status") == ("READY_FOR_QA" if tasks else "NO_WORK")
            and core.get("task_count") == (len(tasks) if isinstance(tasks, list) else -1)
            and core.get("required_verifier") == "qa-verifier-agent"
        )
        checks["digest"] = claimed == _digest(core)
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("candidate_creation_authority") is False
            and core.get("qualification_authority") is False
            and core.get("promotion_authority") is False
            and core.get("paper_execution_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("live_trading_authority") is False
        )
        valid_tasks = isinstance(tasks, list)
        if valid_tasks:
            ids: set[str] = set()
            for task in tasks:
                if not isinstance(task, Mapping):
                    valid_tasks = False
                    break
                task_core = dict(task)
                task_claim = task_core.pop("task_digest", None)
                task_id = str(task_core.get("id", ""))
                evidence = task_core.get("runtime_evidence")
                valid_tasks = bool(
                    task_claim == _digest(task_core)
                    and task_core.get("schema_version") == TASK_SCHEMA
                    and task_core.get("task_kind") == "strategy_review_independent_qa"
                    and task_core.get("system_map_node") == "QA-41"
                    and task_core.get("status") == "READY_FOR_QA_DISPATCH"
                    and task_core.get("source_sha") == core.get("source_sha")
                    and task_core.get("requalification_digest") == core.get("requalification_digest")
                    and task_core.get("requalification_verification_digest")
                    == core.get("requalification_verification_digest")
                    and task_core.get("required_verifier") == "qa-verifier-agent"
                    and task_core.get("research_only") is True
                    and task_core.get("paper_only") is True
                    and task_core.get("candidate_creation_authority") is False
                    and task_core.get("qualification_authority") is False
                    and task_core.get("promotion_authority") is False
                    and task_core.get("paper_execution_authority") is False
                    and task_core.get("automatic_strategy_promotion") is False
                    and task_core.get("live_trading_authority") is False
                    and _HEX64.fullmatch(str(task_core.get("proposal_digest", "")))
                    and _HEX64.fullmatch(str(task_core.get("proposal_result_digest", "")))
                    and isinstance(task_core.get("strategy_config"), Mapping)
                    and bool(task_core.get("strategy_config"))
                    and _HEX64.fullmatch(str(task_core.get("strategy_config_digest", "")))
                    and task_core.get("strategy_config_digest") == _digest(task_core.get("strategy_config"))
                    and task_id == f"STRATEGY-QA-{task_core.get('proposal_digest')}"
                    and task_id not in ids
                    and isinstance(evidence, list)
                    and bool(evidence)
                    and len({item.get("symbol") for item in evidence if isinstance(item, Mapping)})
                    == len(evidence)
                    and {item.get("symbol") for item in evidence if isinstance(item, Mapping)}
                    == set(APPROVED_SYMBOLS)
                    and all(
                        isinstance(item, Mapping)
                        and isinstance(item.get("symbol"), str)
                        and bool(item.get("symbol"))
                        and _HEX64.fullmatch(str(item.get("dataset_binding_sha256", "")))
                        and _HEX64.fullmatch(str(item.get("pipeline_digest", "")))
                        and _HEX64.fullmatch(str(item.get("qualification_digest", "")))
                        and not isinstance(item.get("last_open_time_ms"), bool)
                        and isinstance(item.get("last_open_time_ms"), int)
                        and item.get("last_open_time_ms") > 0
                        for item in evidence
                    )
                )
                if not valid_tasks:
                    break
                ids.add(task_id)
        checks["tasks"] = bool(valid_tasks)
    except Exception:
        pass
    decision = "pass" if all(checks.values()) else "reject"
    proof_core = {
        "schema_version": "nexus.strategy-review-qa-handoff-verification.v1",
        "decision": decision,
        "checks": checks,
        "handoff_digest": value.get("handoff_digest"),
    }
    return {**proof_core, "verification_digest": _digest(proof_core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requalification", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    handoff = build_handoff(_load_json(args.requalification), _load_json(args.verification))
    proof = verify_handoff(handoff)
    if proof["decision"] != "pass":
        raise SystemExit("strategy review QA handoff verification failed")
    _atomic_json(args.output, handoff)
    _atomic_json(args.output.with_name("qa-handoff-verification.json"), proof)
    print(json.dumps({
        "status": handoff["status"],
        "task_count": handoff["task_count"],
        "handoff_digest": handoff["handoff_digest"],
        "paper_only": True,
        "live_trading_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
