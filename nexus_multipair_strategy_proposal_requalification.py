"""Independent runtime requalification for four-symbol Discovery v2 proposals.

Every RESEARCH_PROPOSAL_ONLY is re-evaluated on fresh canonical public Bybit
closed candles for BTC/ETH/SOL/XRP. The discovered config is preserved exactly.
This component can qualify a proposal for human/review consideration only; it
cannot create Candidate/Paper state, execute trades, promote strategies, or grant
Live authority.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import nexus_strategy_proposal_runtime_requalification as legacy
from nexus_multipair_discovery_snapshot import SYMBOLS
from nexus_multipair_strategy_discovery import FAMILIES, TIMEFRAME_NAMES, verify_discovery
from product_research_runtime import ProductResearchError


SCHEMA = "nexus.multipair-strategy-proposal-runtime-requalification.v1"
VERIFICATION_SCHEMA = "nexus.multipair-strategy-proposal-runtime-requalification-verification.v1"
QUEUE_SCHEMA = "nexus.multipair-strategy-research-proposal-queue.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class MultiPairProposalRequalificationError(RuntimeError):
    pass


Evaluator = Callable[[Mapping[str, Any], str, str, int, Path], dict[str, Any]]


def _digest(value: Any) -> str:
    return legacy._digest(value)


def _source_sha(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA_RE.fullmatch(normalized):
        raise MultiPairProposalRequalificationError("source_sha must be an exact Git SHA")
    return normalized


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairProposalRequalificationError("requalification input is unavailable") from exc
    if not isinstance(value, dict):
        raise MultiPairProposalRequalificationError("requalification input is not an object")
    return value


def _validate_inputs(discovery: Mapping[str, Any], queue: Mapping[str, Any]) -> list[dict[str, Any]]:
    if verify_discovery(discovery).get("decision") != "pass":
        raise MultiPairProposalRequalificationError("multi-pair discovery evidence failed verification")
    required = {
        "schema_version", "source_discovery_sha", "source_discovery_digest",
        "dataset_snapshot_sha256", "symbols", "proposals", "research_only",
        "paper_only", "automatic_strategy_promotion", "live_trading_authority", "queue_digest",
    }
    if set(queue) != required:
        raise MultiPairProposalRequalificationError("multi-pair proposal queue schema mismatch")
    core = dict(queue)
    claimed = core.pop("queue_digest", None)
    proposals = queue.get("proposals")
    if (
        queue.get("schema_version") != QUEUE_SCHEMA
        or claimed != _digest(core)
        or queue.get("source_discovery_sha") != discovery.get("source_sha")
        or queue.get("source_discovery_digest") != discovery.get("discovery_digest")
        or queue.get("dataset_snapshot_sha256") != discovery.get("dataset_snapshot_sha256")
        or queue.get("symbols") != list(SYMBOLS)
        or queue.get("research_only") is not True
        or queue.get("paper_only") is not True
        or queue.get("automatic_strategy_promotion") is not False
        or queue.get("live_trading_authority") is not False
        or not isinstance(proposals, list)
        or proposals != discovery.get("research_proposals")
    ):
        raise MultiPairProposalRequalificationError("multi-pair proposal queue is not bound to discovery")
    return [dict(row) for row in proposals]


def build_requalification(
    discovery: Mapping[str, Any],
    queue: Mapping[str, Any],
    *,
    source_sha: str,
    discovery_source_sha: str,
    state_root: str | Path,
    now_ms: int,
    evaluator: Evaluator = legacy._default_evaluator,
) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    discovery_source_sha = _source_sha(discovery_source_sha)
    if source_sha != discovery_source_sha or discovery.get("source_sha") != source_sha:
        raise MultiPairProposalRequalificationError("requalification must execute at the exact discovery source SHA")
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise MultiPairProposalRequalificationError("now_ms must be a positive integer")
    proposals = _validate_inputs(discovery, queue)
    snapshot_digest = str(discovery.get("dataset_snapshot_sha256", ""))
    if not _HEX64_RE.fullmatch(snapshot_digest):
        raise MultiPairProposalRequalificationError("source discovery snapshot digest is invalid")

    root = Path(state_root).resolve()
    results: list[dict[str, Any]] = []
    for proposal in proposals:
        if (
            proposal.get("proposal_state") != "RESEARCH_PROPOSAL_ONLY"
            or proposal.get("eligible_symbols") != list(SYMBOLS)
            or proposal.get("family") not in FAMILIES
            or proposal.get("timeframe") not in TIMEFRAME_NAMES
        ):
            raise MultiPairProposalRequalificationError("proposal is outside the four-symbol Research boundary")
        evaluations: list[dict[str, Any]] = []
        blocked: dict[str, Any] | None = None
        for symbol in SYMBOLS:
            try:
                evaluation = evaluator(proposal, symbol, source_sha, now_ms, root)
                evaluations.append(legacy._validate_evaluation(evaluation, proposal, symbol))
            except ProductResearchError as exc:
                blocked = {
                    "symbol": symbol,
                    "error_type": type(exc).__name__,
                    "error_digest": _digest({"type": type(exc).__name__, "message": str(exc)}),
                }
                break
            except Exception as exc:
                raise MultiPairProposalRequalificationError(
                    f"runtime evaluator failed closed for {symbol}: {type(exc).__name__}"
                ) from exc
        if blocked is not None:
            verdict = "BLOCKED_RUNTIME_DATA"
        elif all(row["qualification_status"] == "paper_candidate" for row in evaluations):
            verdict = "QUALIFIED_FOR_REVIEW"
        else:
            verdict = "REJECTED"
        row_core = {
            "proposal_digest": proposal["proposal_digest"],
            "family": proposal["family"],
            "timeframe": proposal["timeframe"],
            "variant_id": proposal["variant_id"],
            "evaluated_symbols": [row["symbol"] for row in evaluations],
            "verdict": verdict,
            "runtime_evaluations": evaluations,
            "blocked": blocked,
            "candidate_state_created": False,
            "paper_execution_started": False,
            "automatic_strategy_promotion": False,
            "promotion_authority": False,
            "live_trading_authority": False,
        }
        results.append({**row_core, "result_digest": _digest(row_core)})

    blocked_count = sum(row["verdict"] == "BLOCKED_RUNTIME_DATA" for row in results)
    qualified_count = sum(row["verdict"] == "QUALIFIED_FOR_REVIEW" for row in results)
    rejected_count = sum(row["verdict"] == "REJECTED" for row in results)
    status = "NO_WORK" if not proposals else "WAITING_FOR_RUNTIME_DATA" if blocked_count else "EVALUATED"
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "discovery_source_sha": discovery_source_sha,
        "source_discovery_digest": discovery["discovery_digest"],
        "source_snapshot_sha256": snapshot_digest,
        "source_proposal_queue_schema": QUEUE_SCHEMA,
        "symbols": list(SYMBOLS),
        "status": status,
        "proposal_count": len(proposals),
        "qualified_for_review_count": qualified_count,
        "rejected_count": rejected_count,
        "blocked_runtime_data_count": blocked_count,
        "proposal_results": results,
        "runtime_data_is_fresh_not_snapshot_reuse": True,
        "requalification_authority": True,
        "candidate_creation_authority": False,
        "promotion_authority": False,
        "research_only": True,
        "paper_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "requalification_digest": _digest(core)}


def verify_requalification(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "source": False, "authority": False, "counts": False, "results": False}
    try:
        core = dict(value)
        claimed = core.pop("requalification_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = claimed == _digest(core)
        checks["source"] = bool(
            _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and core.get("source_sha") == core.get("discovery_source_sha")
            and _HEX64_RE.fullmatch(str(core.get("source_discovery_digest", "")))
            and _HEX64_RE.fullmatch(str(core.get("source_snapshot_sha256", "")))
            and core.get("source_proposal_queue_schema") == QUEUE_SCHEMA
            and core.get("symbols") == list(SYMBOLS)
        )
        checks["authority"] = bool(
            core.get("runtime_data_is_fresh_not_snapshot_reuse") is True
            and core.get("requalification_authority") is True
            and core.get("candidate_creation_authority") is False
            and core.get("promotion_authority") is False
            and core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("paper_execution_started") is False
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
        rows = core.get("proposal_results")
        checks["counts"] = bool(
            isinstance(rows, list)
            and core.get("proposal_count") == len(rows)
            and core.get("qualified_for_review_count") == sum(isinstance(row, Mapping) and row.get("verdict") == "QUALIFIED_FOR_REVIEW" for row in rows)
            and core.get("rejected_count") == sum(isinstance(row, Mapping) and row.get("verdict") == "REJECTED" for row in rows)
            and core.get("blocked_runtime_data_count") == sum(isinstance(row, Mapping) and row.get("verdict") == "BLOCKED_RUNTIME_DATA" for row in rows)
            and core.get("status") == ("NO_WORK" if not rows else "WAITING_FOR_RUNTIME_DATA" if any(isinstance(row, Mapping) and row.get("verdict") == "BLOCKED_RUNTIME_DATA" for row in rows) else "EVALUATED")
        )
        valid = True
        if not isinstance(rows, list):
            valid = False
        else:
            for row in rows:
                if not isinstance(row, Mapping):
                    valid = False
                    break
                unsigned = dict(row)
                result_digest = unsigned.pop("result_digest", None)
                evaluations = row.get("runtime_evaluations")
                verdict = row.get("verdict")
                blocked = row.get("blocked")
                row_valid = bool(
                    result_digest == _digest(unsigned)
                    and _HEX64_RE.fullmatch(str(row.get("proposal_digest", "")))
                    and row.get("family") in FAMILIES
                    and row.get("timeframe") in TIMEFRAME_NAMES
                    and isinstance(row.get("variant_id"), str)
                    and row.get("candidate_state_created") is False
                    and row.get("paper_execution_started") is False
                    and row.get("automatic_strategy_promotion") is False
                    and row.get("promotion_authority") is False
                    and row.get("live_trading_authority") is False
                    and isinstance(evaluations, list)
                    and len(evaluations) <= len(SYMBOLS)
                    and row.get("evaluated_symbols") == [item.get("symbol") for item in evaluations if isinstance(item, Mapping)]
                    and len(set(row.get("evaluated_symbols", []))) == len(evaluations)
                    and all(
                        isinstance(item, Mapping)
                        and item.get("symbol") in SYMBOLS
                        and item.get("family") == row.get("family")
                        and item.get("timeframe") == row.get("timeframe")
                        and item.get("variant_id") == row.get("variant_id")
                        and item.get("qualification_status") in {"paper_candidate", "killed"}
                        and _HEX64_RE.fullmatch(str(item.get("runtime_dataset_binding_sha256", "")))
                        and _HEX64_RE.fullmatch(str(item.get("pipeline_digest", "")))
                        and _HEX64_RE.fullmatch(str(item.get("qualification_digest", "")))
                        and item.get("deterministic_replay_verified") is True
                        and item.get("data_origin") == "canonical_public_bybit_runtime"
                        and item.get("closed_candle_finality_verified") is True
                        and item.get("paper_only") is True
                        and item.get("live_trading_authority") is False
                        and item.get("paper_execution_started") is False
                        and item.get("automatic_strategy_promotion") is False
                        and item.get("deterministic_risk_final_authority") is True
                        for item in evaluations
                    )
                )
                if verdict == "QUALIFIED_FOR_REVIEW":
                    row_valid = bool(row_valid and blocked is None and len(evaluations) == 4 and set(row["evaluated_symbols"]) == set(SYMBOLS) and all(item["qualification_status"] == "paper_candidate" for item in evaluations))
                elif verdict == "REJECTED":
                    row_valid = bool(row_valid and blocked is None and len(evaluations) == 4 and set(row["evaluated_symbols"]) == set(SYMBOLS) and any(item["qualification_status"] == "killed" for item in evaluations))
                elif verdict == "BLOCKED_RUNTIME_DATA":
                    row_valid = bool(row_valid and isinstance(blocked, Mapping) and blocked.get("symbol") in SYMBOLS and isinstance(blocked.get("error_type"), str) and _HEX64_RE.fullmatch(str(blocked.get("error_digest", ""))))
                else:
                    row_valid = False
                valid = valid and row_valid
        checks["results"] = valid
    except Exception:
        pass
    evidence = {
        "schema_version": VERIFICATION_SCHEMA,
        "decision": "pass" if all(checks.values()) else "reject",
        "checks": checks,
        "requalification_digest": value.get("requalification_digest"),
    }
    return {**evidence, "verification_digest": _digest(evidence)}


def run(
    discovery_path: str | Path,
    queue_path: str | Path,
    *,
    source_sha: str,
    discovery_source_sha: str,
    state_root: str | Path,
    output: str | Path,
    now_ms: int | None = None,
) -> dict[str, Any]:
    result = build_requalification(
        _load_json(discovery_path), _load_json(queue_path),
        source_sha=source_sha, discovery_source_sha=discovery_source_sha,
        state_root=state_root, now_ms=int(time.time() * 1000) if now_ms is None else now_ms,
    )
    verification = verify_requalification(result)
    if verification["decision"] != "pass":
        raise MultiPairProposalRequalificationError("multi-pair requalification verifier rejected evidence")
    target = Path(output).resolve()
    legacy._atomic_json(target, result)
    legacy._atomic_json(target.with_name("verification.json"), verification)
    return result
