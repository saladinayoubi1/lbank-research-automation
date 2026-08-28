"""Independent runtime requalification for bounded Strategy Discovery proposals.

Discovery may emit RESEARCH_PROPOSAL records, but those records have no Candidate,
Paper, or promotion authority. This module re-runs each proposal against fresh
canonical public Bybit closed-candle data using the existing deterministic Strategy
Factory qualification gates. The strongest outcome is QUALIFIED_FOR_REVIEW.
No Paper action is started here and Live/L4 remains unreachable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from nexus_demo_archive_replay import ARCHIVE_SHA256
from nexus_multitimeframe_strategy_discovery import (
    APPROVED_FAMILIES,
    APPROVED_TIMEFRAMES,
    verify_discovery,
)
from phase6_research_pipeline import run_research_job
from product_research_runtime import (
    COST_MODEL,
    KILL_CRITERIA,
    ProductResearchError,
    ProductResearchRuntime,
)

SCHEMA = "nexus.strategy-proposal-runtime-requalification.v1"
VERIFICATION_SCHEMA = "nexus.strategy-proposal-runtime-requalification-verification.v1"
QUEUE_SCHEMA = "nexus.strategy-research-proposal-queue.v1"
APPROVED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class StrategyProposalRequalificationError(RuntimeError):
    pass


Evaluator = Callable[[Mapping[str, Any], str, str, int, Path], Mapping[str, Any]]


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
        raise StrategyProposalRequalificationError(
            "requalification evidence is not canonical JSON"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyProposalRequalificationError(
            "requalification input is unavailable"
        ) from exc
    if not isinstance(value, dict):
        raise StrategyProposalRequalificationError("requalification input is not an object")
    return value


def _source_sha(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA_RE.fullmatch(normalized):
        raise StrategyProposalRequalificationError("source_sha must be an exact Git SHA")
    return normalized


def _validate_inputs(
    discovery: Mapping[str, Any], proposal_queue: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if verify_discovery(discovery).get("decision") != "pass":
        raise StrategyProposalRequalificationError("discovery evidence failed verification")
    if set(proposal_queue) != {
        "schema_version",
        "source_discovery_digest",
        "proposals",
        "automatic_strategy_promotion",
        "live_trading_authority",
    }:
        raise StrategyProposalRequalificationError("proposal queue schema mismatch")
    proposals = proposal_queue.get("proposals")
    discovery_proposals = discovery.get("research_proposals")
    if (
        proposal_queue.get("schema_version") != QUEUE_SCHEMA
        or proposal_queue.get("source_discovery_digest") != discovery.get("discovery_digest")
        or proposal_queue.get("automatic_strategy_promotion") is not False
        or proposal_queue.get("live_trading_authority") is not False
        or not isinstance(proposals, list)
        or proposals != discovery_proposals
    ):
        raise StrategyProposalRequalificationError("proposal queue is not bound to discovery")
    return [dict(row) for row in proposals]


def _validate_runtime_job(
    job: Mapping[str, Any],
    *,
    dataset_sha: str,
    source_sha: str,
    proposal: Mapping[str, Any],
) -> None:
    core = dict(job)
    claimed = core.pop("pipeline_digest", None)
    experiment = job.get("experiment")
    qualification = job.get("qualification")
    handoff = job.get("paper_candidate_handoff")
    if (
        job.get("schema_version") != "nexus.phase6-research-pipeline.v1"
        or job.get("paper_only") is not True
        or job.get("live_execution_allowed") is not False
        or job.get("dataset_binding_sha256") != dataset_sha
        or claimed != _digest(core)
        or not isinstance(experiment, Mapping)
        or experiment.get("dataset_binding_sha256") != dataset_sha
        or experiment.get("code_sha") != source_sha
        or experiment.get("family") != proposal.get("family")
        or experiment.get("config") != proposal.get("strategy_config")
        or not isinstance(qualification, Mapping)
        or qualification.get("dataset_binding_sha256") != dataset_sha
        or qualification.get("code_sha") != source_sha
        or qualification.get("family") != proposal.get("family")
        or qualification.get("status") not in {"paper_candidate", "killed"}
        or qualification.get("paper_only") is not True
        or qualification.get("live_execution_allowed") is not False
        or qualification.get("deterministic_risk_final_authority") is not True
    ):
        raise StrategyProposalRequalificationError(
            "runtime qualification job failed authority or lineage verification"
        )
    if qualification.get("status") == "paper_candidate":
        if (
            not isinstance(handoff, Mapping)
            or handoff.get("qualification_digest") != qualification.get("qualification_digest")
            or handoff.get("paper_only") is not True
            or handoff.get("live_execution_allowed") is not False
            or handoff.get("production_promotion_allowed") is not False
            or handoff.get("deterministic_risk_final_authority") is not True
        ):
            raise StrategyProposalRequalificationError("runtime Paper review handoff is invalid")
    elif handoff is not None:
        raise StrategyProposalRequalificationError("killed runtime job emitted a Paper handoff")


def _default_evaluator(
    proposal: Mapping[str, Any],
    symbol: str,
    source_sha: str,
    now_ms: int,
    state_root: Path,
) -> dict[str, Any]:
    """Evaluate one proposal/symbol on fresh canonical public runtime data."""
    # fetch_dataset is the existing canonical public-data boundary: unique approved
    # Bybit mapping, closed candles, freshness, schema, and registry validation.
    # No ProductRuntime/Paper method is invoked here.
    research = ProductResearchRuntime(
        None,  # type: ignore[arg-type]
        source_sha=source_sha,
        clock_ms=lambda: now_ms,
    )
    dataset = research.fetch_dataset(
        symbol=symbol,
        timeframe=str(proposal["timeframe"]),
        limit=240,
    )
    family = str(proposal["family"])
    variant_id = str(proposal["variant_id"])
    job_kwargs = {
        "hypothesis": (
            "Independent runtime requalification of a bounded Strategy Discovery "
            f"proposal {proposal['proposal_digest']}; no profitability or promotion claim."
        ),
        "family": family,
        "strategy_version": f"{family}-runtime-requalification-{variant_id}",
        "strategy_config": dict(proposal["strategy_config"]),
        "code_sha": source_sha,
        "cost_model": COST_MODEL,
        "kill_criteria": KILL_CRITERIA,
    }
    job = run_research_job(
        dataset,
        **job_kwargs,
    )
    replay = run_research_job(dataset, **job_kwargs)
    binding = str(dataset.get("binding_sha256", ""))
    _validate_runtime_job(
        job,
        dataset_sha=binding,
        source_sha=source_sha,
        proposal=proposal,
    )
    _validate_runtime_job(
        replay,
        dataset_sha=binding,
        source_sha=source_sha,
        proposal=proposal,
    )
    if _canonical(job) != _canonical(replay):
        raise StrategyProposalRequalificationError(
            "runtime qualification replay is not deterministic"
        )
    qualification = job.get("qualification")
    if not isinstance(qualification, Mapping):
        raise StrategyProposalRequalificationError("runtime qualification is missing")
    status = qualification.get("status")
    if status not in {"paper_candidate", "killed"}:
        raise StrategyProposalRequalificationError("runtime qualification status is invalid")
    if (
        qualification.get("paper_only") is not True
        or qualification.get("live_execution_allowed") is not False
        or qualification.get("deterministic_risk_final_authority") is not True
        or qualification.get("family") != family
        or qualification.get("code_sha") != source_sha
        or qualification.get("dataset_binding_sha256") != dataset.get("binding_sha256")
    ):
        raise StrategyProposalRequalificationError("runtime qualification authority binding failed")
    if not _HEX64_RE.fullmatch(binding):
        raise StrategyProposalRequalificationError("runtime dataset binding is invalid")
    rows = dataset.get("rows")
    if not isinstance(rows, list) or not rows or not isinstance(rows[-1], Mapping):
        raise StrategyProposalRequalificationError("runtime dataset rows are missing")
    return {
        "symbol": symbol,
        "family": family,
        "timeframe": proposal["timeframe"],
        "variant_id": variant_id,
        "runtime_dataset_binding_sha256": binding,
        "runtime_last_open_time_ms": rows[-1].get("open_time_ms"),
        "qualification_status": status,
        "pipeline_digest": job.get("pipeline_digest"),
        "qualification_digest": qualification.get("qualification_digest"),
        "kill_reasons": list(qualification.get("kill_reasons", [])),
        "deterministic_replay_verified": True,
        "data_origin": "canonical_public_bybit_runtime",
        "closed_candle_finality_verified": True,
        "paper_only": True,
        "live_trading_authority": False,
        "paper_execution_started": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }


def _validate_evaluation(
    evaluation: Mapping[str, Any], proposal: Mapping[str, Any], symbol: str
) -> dict[str, Any]:
    row = dict(evaluation)
    if (
        row.get("symbol") != symbol
        or row.get("family") != proposal.get("family")
        or row.get("timeframe") != proposal.get("timeframe")
        or row.get("variant_id") != proposal.get("variant_id")
        or row.get("qualification_status") not in {"paper_candidate", "killed"}
        or not _HEX64_RE.fullmatch(str(row.get("runtime_dataset_binding_sha256", "")))
        or not _HEX64_RE.fullmatch(str(row.get("pipeline_digest", "")))
        or not _HEX64_RE.fullmatch(str(row.get("qualification_digest", "")))
        or row.get("deterministic_replay_verified") is not True
        or row.get("data_origin") != "canonical_public_bybit_runtime"
        or row.get("closed_candle_finality_verified") is not True
        or row.get("paper_only") is not True
        or row.get("live_trading_authority") is not False
        or row.get("paper_execution_started") is not False
        or row.get("automatic_strategy_promotion") is not False
        or row.get("deterministic_risk_final_authority") is not True
    ):
        raise StrategyProposalRequalificationError("runtime evaluation contract mismatch")
    reasons = row.get("kill_reasons")
    if not isinstance(reasons, list) or any(not isinstance(item, str) for item in reasons):
        raise StrategyProposalRequalificationError("runtime kill reasons are invalid")
    if row["qualification_status"] == "paper_candidate" and reasons:
        raise StrategyProposalRequalificationError("paper_candidate cannot contain kill reasons")
    if row["qualification_status"] == "killed" and not reasons:
        raise StrategyProposalRequalificationError("killed qualification requires kill reasons")
    return row


def build_requalification(
    discovery: Mapping[str, Any],
    proposal_queue: Mapping[str, Any],
    *,
    source_sha: str,
    discovery_source_sha: str,
    state_root: str | Path,
    now_ms: int,
    evaluator: Evaluator = _default_evaluator,
) -> dict[str, Any]:
    source_sha = _source_sha(source_sha)
    discovery_source_sha = _source_sha(discovery_source_sha)
    if source_sha != discovery_source_sha:
        raise StrategyProposalRequalificationError(
            "requalification must execute at the exact discovery source SHA"
        )
    if isinstance(now_ms, bool) or not isinstance(now_ms, int) or now_ms <= 0:
        raise StrategyProposalRequalificationError("now_ms must be a positive integer")
    proposals = _validate_inputs(discovery, proposal_queue)
    if discovery.get("dataset_archive_sha256") != ARCHIVE_SHA256:
        raise StrategyProposalRequalificationError(
            "discovery archive identity is not the approved immutable Bybit dataset"
        )
    root = Path(state_root).resolve()
    results: list[dict[str, Any]] = []

    for proposal in proposals:
        evaluations: list[dict[str, Any]] = []
        blocked: dict[str, Any] | None = None
        for symbol in APPROVED_SYMBOLS:
            try:
                evaluation = evaluator(proposal, symbol, source_sha, now_ms, root)
                evaluations.append(_validate_evaluation(evaluation, proposal, symbol))
            except ProductResearchError as exc:
                blocked = {
                    "error_type": type(exc).__name__,
                    "error_digest": _digest({"type": type(exc).__name__, "message": str(exc)}),
                }
                break

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
    if not proposals:
        status = "NO_WORK"
    elif blocked_count:
        status = "WAITING_FOR_RUNTIME_DATA"
    else:
        status = "EVALUATED"
    core = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "discovery_source_sha": discovery_source_sha,
        "source_discovery_digest": discovery["discovery_digest"],
        "source_archive_sha256": discovery["dataset_archive_sha256"],
        "source_proposal_queue_schema": QUEUE_SCHEMA,
        "status": status,
        "proposal_count": len(proposals),
        "qualified_for_review_count": qualified_count,
        "rejected_count": rejected_count,
        "blocked_runtime_data_count": blocked_count,
        "proposal_results": results,
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
    checks = {
        "schema": False,
        "digest": False,
        "source": False,
        "authority": False,
        "counts": False,
        "results": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("requalification_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["source"] = bool(
            _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and core.get("source_sha") == core.get("discovery_source_sha")
            and _HEX64_RE.fullmatch(str(core.get("source_discovery_digest", "")))
            and core.get("source_archive_sha256") == ARCHIVE_SHA256
            and core.get("source_proposal_queue_schema") == QUEUE_SCHEMA
        )
        checks["authority"] = bool(
            core.get("requalification_authority") is True
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
            and core.get("qualified_for_review_count")
            == sum(isinstance(row, Mapping) and row.get("verdict") == "QUALIFIED_FOR_REVIEW" for row in rows)
            and core.get("rejected_count")
            == sum(isinstance(row, Mapping) and row.get("verdict") == "REJECTED" for row in rows)
            and core.get("blocked_runtime_data_count")
            == sum(isinstance(row, Mapping) and row.get("verdict") == "BLOCKED_RUNTIME_DATA" for row in rows)
            and core.get("status")
            == (
                "NO_WORK" if not rows
                else "WAITING_FOR_RUNTIME_DATA"
                if any(isinstance(row, Mapping) and row.get("verdict") == "BLOCKED_RUNTIME_DATA" for row in rows)
                else "EVALUATED"
            )
        )
        valid_rows = True
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    valid_rows = False
                    break
                unsigned = dict(row)
                result_digest = unsigned.pop("result_digest", None)
                evaluations = row.get("runtime_evaluations")
                verdict = row.get("verdict")
                blocked = row.get("blocked")
                row_valid = bool(
                    result_digest == _digest(unsigned)
                    and _HEX64_RE.fullmatch(str(row.get("proposal_digest", "")))
                    and row.get("family") in APPROVED_FAMILIES
                    and row.get("timeframe") in APPROVED_TIMEFRAMES
                    and isinstance(row.get("variant_id"), str)
                    and row.get("candidate_state_created") is False
                    and row.get("paper_execution_started") is False
                    and row.get("automatic_strategy_promotion") is False
                    and row.get("promotion_authority") is False
                    and row.get("live_trading_authority") is False
                    and isinstance(evaluations, list)
                    and len(evaluations) <= len(APPROVED_SYMBOLS)
                    and len({item.get("symbol") for item in evaluations if isinstance(item, Mapping)})
                    == len(evaluations)
                    and all(
                        isinstance(item, Mapping)
                        and item.get("symbol") in APPROVED_SYMBOLS
                        and item.get("family") == row.get("family")
                        and item.get("timeframe") == row.get("timeframe")
                        and item.get("variant_id") == row.get("variant_id")
                        and item.get("qualification_status") in {"paper_candidate", "killed"}
                        and _HEX64_RE.fullmatch(
                            str(item.get("runtime_dataset_binding_sha256", ""))
                        )
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
                    row_valid = bool(
                        row_valid
                        and blocked is None
                        and len(evaluations) == len(APPROVED_SYMBOLS)
                        and {item.get("symbol") for item in evaluations if isinstance(item, Mapping)}
                        == set(APPROVED_SYMBOLS)
                        and all(
                            isinstance(item, Mapping)
                            and item.get("qualification_status") == "paper_candidate"
                            for item in evaluations
                        )
                    )
                elif verdict == "REJECTED":
                    row_valid = bool(
                        row_valid
                        and blocked is None
                        and len(evaluations) == len(APPROVED_SYMBOLS)
                        and any(
                            isinstance(item, Mapping) and item.get("qualification_status") == "killed"
                            for item in evaluations
                        )
                    )
                elif verdict == "BLOCKED_RUNTIME_DATA":
                    row_valid = bool(
                        row_valid
                        and isinstance(blocked, Mapping)
                        and isinstance(blocked.get("error_type"), str)
                        and _HEX64_RE.fullmatch(str(blocked.get("error_digest", "")))
                    )
                else:
                    row_valid = False
                valid_rows = valid_rows and row_valid
        else:
            valid_rows = False
        checks["results"] = valid_rows
    except Exception:
        pass
    decision = "pass" if all(checks.values()) else "reject"
    core = {
        "schema_version": VERIFICATION_SCHEMA,
        "decision": decision,
        "checks": checks,
        "requalification_digest": value.get("requalification_digest"),
    }
    return {**core, "verification_digest": _digest(core)}


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
        _load_json(discovery_path),
        _load_json(queue_path),
        source_sha=source_sha,
        discovery_source_sha=discovery_source_sha,
        state_root=state_root,
        now_ms=int(time.time() * 1000) if now_ms is None else now_ms,
    )
    verification = verify_requalification(result)
    if verification["decision"] != "pass":
        raise StrategyProposalRequalificationError("requalification verifier rejected evidence")
    target = Path(output).resolve()
    _atomic_json(target, result)
    _atomic_json(target.with_name("verification.json"), verification)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--discovery-source-sha", required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--now-ms", type=int)
    args = parser.parse_args()
    result = run(
        args.discovery,
        args.queue,
        source_sha=args.source_sha,
        discovery_source_sha=args.discovery_source_sha,
        state_root=args.state_root,
        output=args.output,
        now_ms=args.now_ms,
    )
    print(json.dumps({
        "status": result["status"],
        "proposal_count": result["proposal_count"],
        "qualified_for_review_count": result["qualified_for_review_count"],
        "requalification_digest": result["requalification_digest"],
        "automatic_strategy_promotion": False,
        "paper_execution_started": False,
        "live_trading_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
