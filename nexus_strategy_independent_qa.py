"""Independent QA-41 replay for source-bound Strategy Finder review tasks.

This module reuses the existing runtime requalification evaluator.  It never
selects a strategy, qualifies it for Paper, mutates a registry, executes Paper,
or grants Live authority.  A successful receipt means only that the designated
QA verifier independently reproduced the exact source/config/dataset-bound
runtime evidence carried by the QA-41 handoff.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

from nexus_strategy_requalification_contract import (
    APPROVED_FAMILIES,
    APPROVED_SYMBOLS,
    APPROVED_TIMEFRAMES,
    TIMEFRAME_STEP_MS,
)
from nexus_strategy_review_qa_handoff import qa_task_id

TASK_SCHEMA = "nexus.strategy-review-qa-task.v1"
RECEIPT_SCHEMA = "nexus.strategy-independent-qa-receipt.v1"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

TASK_KEYS = {
    "schema_version", "id", "task_kind", "system_map_node", "status",
    "source_sha", "proposal_digest", "proposal_result_digest",
    "requalification_digest", "requalification_verification_digest",
    "family", "timeframe", "variant_id", "strategy_config",
    "strategy_config_digest", "runtime_evidence", "producer_role",
    "required_verifier", "research_only", "paper_only",
    "candidate_creation_authority", "qualification_authority",
    "promotion_authority", "paper_execution_authority",
    "automatic_strategy_promotion", "live_trading_authority", "task_digest",
}
EVIDENCE_KEYS = {
    "symbol", "dataset_binding_sha256", "pipeline_digest",
    "qualification_digest", "last_open_time_ms",
}
RECEIPT_KEYS = {
    "schema_version", "qa_lease_id", "task_digest", "source_sha",
    "proposal_digest", "proposal_result_digest", "requalification_digest",
    "requalification_verification_digest", "strategy_config_digest",
    "runtime_evidence", "independent_qa_complete", "qualification_authority",
    "promotion_authority", "paper_execution_authority",
    "automatic_strategy_promotion", "live_trading_authority",
    "qa_receipt_digest",
}


class StrategyIndependentQaError(RuntimeError):
    pass


Evaluator = Callable[[Mapping[str, Any], str, str, int, Path], Mapping[str, Any]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyIndependentQaError("Strategy QA evidence is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def validate_task(task: Mapping[str, Any], execution_source_sha: str) -> dict[str, Any]:
    row = dict(task)
    if set(row) != TASK_KEYS:
        raise StrategyIndependentQaError("Strategy QA task schema mismatch")
    unsigned = dict(row)
    claimed = unsigned.pop("task_digest", None)
    config = row.get("strategy_config")
    runtime_evidence = row.get("runtime_evidence")
    proposal_digest = str(row.get("proposal_digest", ""))
    source_sha = str(row.get("source_sha", ""))
    if (
        row.get("schema_version") != TASK_SCHEMA
        or row.get("task_kind") != "strategy_review_independent_qa"
        or row.get("system_map_node") != "QA-41"
        or row.get("status") != "READY_FOR_QA_DISPATCH"
        or claimed != digest(unsigned)
        or not HEX40.fullmatch(source_sha)
        or execution_source_sha != source_sha
        or not HEX64.fullmatch(proposal_digest)
        or row.get("id") != qa_task_id(
            proposal_digest,
            source_sha,
            str(row.get("requalification_digest", "")),
        )
        or not HEX64.fullmatch(str(row.get("proposal_result_digest", "")))
        or not HEX64.fullmatch(str(row.get("requalification_digest", "")))
        or not HEX64.fullmatch(str(row.get("requalification_verification_digest", "")))
        or not isinstance(config, Mapping)
        or not config
        or row.get("strategy_config_digest") != digest(config)
        or row.get("required_verifier") != "qa-verifier-agent"
        or row.get("producer_role") != "strategy-runtime-requalification"
        or row.get("research_only") is not True
        or row.get("paper_only") is not True
        or row.get("candidate_creation_authority") is not False
        or row.get("qualification_authority") is not False
        or row.get("promotion_authority") is not False
        or row.get("paper_execution_authority") is not False
        or row.get("automatic_strategy_promotion") is not False
        or row.get("live_trading_authority") is not False
        or row.get("timeframe") not in APPROVED_TIMEFRAMES
        or row.get("family") not in APPROVED_FAMILIES
        or not isinstance(row.get("variant_id"), str)
        or not row.get("variant_id")
        or not isinstance(runtime_evidence, list)
        or not runtime_evidence
    ):
        raise StrategyIndependentQaError("Strategy QA task authority or identity binding failed")

    seen: set[str] = set()
    for evidence in runtime_evidence:
        if not isinstance(evidence, Mapping) or set(evidence) != EVIDENCE_KEYS:
            raise StrategyIndependentQaError("Strategy QA runtime evidence schema mismatch")
        symbol = evidence.get("symbol")
        last_open = evidence.get("last_open_time_ms")
        if (
            not isinstance(symbol, str)
            or not symbol
            or symbol in seen
            or not HEX64.fullmatch(str(evidence.get("dataset_binding_sha256", "")))
            or not HEX64.fullmatch(str(evidence.get("pipeline_digest", "")))
            or not HEX64.fullmatch(str(evidence.get("qualification_digest", "")))
            or isinstance(last_open, bool)
            or not isinstance(last_open, int)
            or last_open <= 0
        ):
            raise StrategyIndependentQaError("Strategy QA runtime evidence binding failed")
        seen.add(symbol)
    if seen != set(APPROVED_SYMBOLS):
        raise StrategyIndependentQaError("Strategy QA task must bind every approved runtime symbol")
    return row


def _expected_receipt_runtime(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "symbol": evidence["symbol"],
            "dataset_binding_sha256": evidence["dataset_binding_sha256"],
            "pipeline_digest": evidence["pipeline_digest"],
            "qualification_digest": evidence["qualification_digest"],
            "last_open_time_ms": evidence["last_open_time_ms"],
            "qualification_status": "paper_candidate",
            "deterministic_replay_verified": True,
        }
        for evidence in sorted(task["runtime_evidence"], key=lambda item: item["symbol"])
    ]


def run_independent_qa(
    task: Mapping[str, Any],
    *,
    lease_id: str,
    execution_source_sha: str,
    state_root: str | Path,
    evaluator: Evaluator | None = None,
) -> dict[str, Any]:
    if not isinstance(lease_id, str) or not lease_id or len(lease_id) > 160:
        raise StrategyIndependentQaError("Strategy QA lease identity is invalid")
    row = validate_task(task, execution_source_sha)
    if evaluator is None:
        # Numerical replay is the only path that needs the heavy research
        # runtime. Receipt/task verification remains control-plane lightweight.
        from nexus_strategy_proposal_runtime_requalification import _default_evaluator
        evaluator = _default_evaluator
    proposal = {
        "proposal_digest": row["proposal_digest"],
        "family": row["family"],
        "timeframe": row["timeframe"],
        "variant_id": row["variant_id"],
        "strategy_config": dict(row["strategy_config"]),
    }
    step_ms = int(TIMEFRAME_STEP_MS[row["timeframe"]])
    replay_rows: list[dict[str, Any]] = []
    for expected in sorted(row["runtime_evidence"], key=lambda item: item["symbol"]):
        now_ms = int(expected["last_open_time_ms"]) + step_ms
        actual = dict(
            evaluator(
                proposal,
                str(expected["symbol"]),
                execution_source_sha,
                now_ms,
                Path(state_root).resolve(),
            )
        )
        if (
            actual.get("symbol") != expected["symbol"]
            or actual.get("family") != row["family"]
            or actual.get("timeframe") != row["timeframe"]
            or actual.get("variant_id") != row["variant_id"]
            or actual.get("runtime_dataset_binding_sha256")
            != expected["dataset_binding_sha256"]
            or actual.get("runtime_last_open_time_ms") != expected["last_open_time_ms"]
            or actual.get("pipeline_digest") != expected["pipeline_digest"]
            or actual.get("qualification_digest") != expected["qualification_digest"]
            or actual.get("qualification_status") != "paper_candidate"
            or actual.get("deterministic_replay_verified") is not True
            or actual.get("data_origin") != "canonical_public_bybit_runtime"
            or actual.get("closed_candle_finality_verified") is not True
            or actual.get("paper_only") is not True
            or actual.get("live_trading_authority") is not False
            or actual.get("paper_execution_started") is not False
            or actual.get("automatic_strategy_promotion") is not False
        ):
            raise StrategyIndependentQaError(
                f"independent Strategy QA replay mismatch for {expected['symbol']}"
            )
        replay_rows.append(
            {
                "symbol": expected["symbol"],
                "dataset_binding_sha256": expected["dataset_binding_sha256"],
                "pipeline_digest": expected["pipeline_digest"],
                "qualification_digest": expected["qualification_digest"],
                "last_open_time_ms": expected["last_open_time_ms"],
                "qualification_status": "paper_candidate",
                "deterministic_replay_verified": True,
            }
        )

    core = {
        "schema_version": RECEIPT_SCHEMA,
        "qa_lease_id": lease_id,
        "task_digest": row["task_digest"],
        "source_sha": row["source_sha"],
        "proposal_digest": row["proposal_digest"],
        "proposal_result_digest": row["proposal_result_digest"],
        "requalification_digest": row["requalification_digest"],
        "requalification_verification_digest": row["requalification_verification_digest"],
        "strategy_config_digest": row["strategy_config_digest"],
        "runtime_evidence": replay_rows,
        "independent_qa_complete": True,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "qa_receipt_digest": digest(core)}


def verify_receipt(
    receipt: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    lease_id: str,
    execution_source_sha: str,
) -> bool:
    try:
        row = validate_task(task, execution_source_sha)
        if set(receipt) != RECEIPT_KEYS:
            return False
        value = dict(receipt)
        claimed = value.pop("qa_receipt_digest", None)
        return bool(
            claimed == digest(value)
            and receipt.get("schema_version") == RECEIPT_SCHEMA
            and receipt.get("qa_lease_id") == lease_id
            and receipt.get("task_digest") == row["task_digest"]
            and receipt.get("source_sha") == row["source_sha"]
            and receipt.get("proposal_digest") == row["proposal_digest"]
            and receipt.get("proposal_result_digest") == row["proposal_result_digest"]
            and receipt.get("requalification_digest") == row["requalification_digest"]
            and receipt.get("requalification_verification_digest")
            == row["requalification_verification_digest"]
            and receipt.get("strategy_config_digest") == row["strategy_config_digest"]
            and receipt.get("runtime_evidence") == _expected_receipt_runtime(row)
            and receipt.get("independent_qa_complete") is True
            and receipt.get("qualification_authority") is False
            and receipt.get("promotion_authority") is False
            and receipt.get("paper_execution_authority") is False
            and receipt.get("automatic_strategy_promotion") is False
            and receipt.get("live_trading_authority") is False
        )
    except Exception:
        return False
