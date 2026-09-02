"""Bind health-driven Strategy Discovery feedback to an exact verified Paper 4h boundary.

This module is evidence-only. It consumes already-produced Paper, Discovery and
runtime-requalification artifacts, verifies their existing contracts, and emits a
digest-bound lineage record. It never creates Candidate/Paper state, submits
orders, uses private credentials, promotes strategies, or grants Live/L4 authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_multitimeframe_strategy_discovery import APPROVED_SYMBOLS, verify_discovery
from nexus_persistent_paper_trading_loop import verify_loop_snapshot
from nexus_strategy_proposal_runtime_requalification import verify_requalification


CONTEXT_SCHEMA = "nexus.paper-boundary-discovery-context.v1"
FEEDBACK_SCHEMA = "nexus.paper-boundary-discovery-feedback.v2"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class PaperBoundaryDiscoveryFeedbackError(RuntimeError):
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
        raise PaperBoundaryDiscoveryFeedbackError("feedback evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PaperBoundaryDiscoveryFeedbackError("feedback input is unavailable") from exc
    if not isinstance(value, dict):
        raise PaperBoundaryDiscoveryFeedbackError("feedback input is not an object")
    return value


def _atomic_json(path: str | Path, value: Mapping[str, Any]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + f".{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(value), indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PaperBoundaryDiscoveryFeedbackError(f"{label} must be a positive integer")
    return value


def build_boundary_context(
    loop_snapshot: Mapping[str, Any], matrix_state: Mapping[str, Any]
) -> dict[str, Any]:
    """Extract the exact fresh BTC/ETH 4h boundary from one verified Paper cycle."""
    if verify_loop_snapshot(loop_snapshot).get("decision") != "pass":
        raise PaperBoundaryDiscoveryFeedbackError("Paper-loop snapshot failed verification")

    source_sha = str(loop_snapshot.get("source_sha", "")).strip().lower()
    loop_digest = str(loop_snapshot.get("loop_digest", ""))
    run_id = str(loop_snapshot.get("run_id", ""))
    expected_cells = loop_snapshot.get("expected_cell_count")
    fresh_cells = loop_snapshot.get("fresh_cells")
    if (
        not _SHA_RE.fullmatch(source_sha)
        or not _HEX64_RE.fullmatch(loop_digest)
        or not run_id.isdigit()
        or loop_snapshot.get("status") != "PAPER_LOOP_ACTIVE"
        or loop_snapshot.get("regime_status") != "VERIFIED"
        or loop_snapshot.get("strategy_research_required") is not True
        or loop_snapshot.get("strategy_discovery_health_trigger_requested") is not True
        or expected_cells != 6
        or loop_snapshot.get("fresh_cell_count") != expected_cells
        or not isinstance(fresh_cells, list)
        or len(fresh_cells) != expected_cells
        or loop_snapshot.get("paper_only") is not True
        or loop_snapshot.get("live_trading_authority") is not False
        or loop_snapshot.get("private_credentials_used") is not False
        or loop_snapshot.get("automatic_strategy_promotion") is not False
        or loop_snapshot.get("deterministic_risk_final_authority") is not True
    ):
        raise PaperBoundaryDiscoveryFeedbackError(
            "Paper-loop snapshot is not an eligible health-driven fresh boundary"
        )

    cells = matrix_state.get("cells") if isinstance(matrix_state, Mapping) else None
    if not isinstance(cells, Mapping):
        raise PaperBoundaryDiscoveryFeedbackError("matrix state cells are unavailable")

    fresh_set = {str(item) for item in fresh_cells}
    boundary: dict[str, int] = {}
    for symbol in APPROVED_SYMBOLS:
        cell_id = f"{symbol}:hour4"
        row = cells.get(cell_id)
        if cell_id not in fresh_set or not isinstance(row, Mapping):
            raise PaperBoundaryDiscoveryFeedbackError(
                f"fresh hour4 matrix cell is unavailable: {cell_id}"
            )
        if row.get("status") != "VERIFIED" or row.get("source_sha") != source_sha:
            raise PaperBoundaryDiscoveryFeedbackError(
                f"hour4 matrix cell is not verified at the Paper source SHA: {cell_id}"
            )
        boundary[symbol] = _positive_int(
            row.get("last_completed_open_ms"), f"{cell_id}.last_completed_open_ms"
        )

    boundary_digest = _digest(boundary)
    core = {
        "schema_version": CONTEXT_SCHEMA,
        "source_sha": source_sha,
        "paper_run_id": run_id,
        "paper_loop_digest": loop_digest,
        "hour4_boundary_ms": boundary,
        "hour4_boundary_digest": boundary_digest,
        "trigger_reason": "NEW_VERIFIED_4H_BOUNDARY_RESEARCH_REQUIRED",
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "context_digest": _digest(core)}


def verify_boundary_context(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "source": False,
        "boundary": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("context_digest", None)
        boundary = core.get("hour4_boundary_ms")
        checks["schema"] = core.get("schema_version") == CONTEXT_SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["source"] = bool(
            _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and str(core.get("paper_run_id", "")).isdigit()
            and _HEX64_RE.fullmatch(str(core.get("paper_loop_digest", "")))
        )
        checks["boundary"] = bool(
            isinstance(boundary, Mapping)
            and set(boundary) == set(APPROVED_SYMBOLS)
            and all(
                isinstance(boundary[symbol], int)
                and not isinstance(boundary[symbol], bool)
                and boundary[symbol] > 0
                for symbol in APPROVED_SYMBOLS
            )
            and core.get("hour4_boundary_digest") == _digest(dict(boundary))
            and core.get("trigger_reason")
            == "NEW_VERIFIED_4H_BOUNDARY_RESEARCH_REQUIRED"
        )
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
    except (TypeError, ValueError, KeyError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def build_feedback(
    context: Mapping[str, Any],
    discovery: Mapping[str, Any],
    requalification: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove exact-boundary requalification or a verified empty Discovery result."""
    if verify_boundary_context(context).get("decision") != "pass":
        raise PaperBoundaryDiscoveryFeedbackError("Paper boundary context failed verification")
    if verify_discovery(discovery).get("decision") != "pass":
        raise PaperBoundaryDiscoveryFeedbackError("Strategy Discovery evidence failed verification")
    if verify_requalification(requalification).get("decision") != "pass":
        raise PaperBoundaryDiscoveryFeedbackError("runtime requalification evidence failed verification")

    source_sha = context["source_sha"]
    discovery_digest = str(discovery.get("discovery_digest", ""))
    requalification_digest = str(requalification.get("requalification_digest", ""))
    if (
        discovery.get("source_sha") != source_sha
        or requalification.get("source_sha") != source_sha
        or requalification.get("discovery_source_sha") != source_sha
        or requalification.get("source_discovery_digest") != discovery_digest
        or not _HEX64_RE.fullmatch(discovery_digest)
        or not _HEX64_RE.fullmatch(requalification_digest)
    ):
        raise PaperBoundaryDiscoveryFeedbackError(
            "Discovery/requalification lineage is not bound to the Paper source SHA"
        )

    boundary = dict(context["hour4_boundary_ms"])
    rows = requalification.get("proposal_results")
    if not isinstance(rows, list):
        raise PaperBoundaryDiscoveryFeedbackError("runtime requalification results are unavailable")

    covered_evaluations = 0
    required_evaluations = 0
    all_covered = True
    for proposal in rows:
        if not isinstance(proposal, Mapping):
            raise PaperBoundaryDiscoveryFeedbackError("runtime proposal result is invalid")
        evaluations = proposal.get("runtime_evaluations")
        if not isinstance(evaluations, list):
            raise PaperBoundaryDiscoveryFeedbackError("runtime evaluations are unavailable")
        if proposal.get("verdict") != "BLOCKED_RUNTIME_DATA":
            required_evaluations += len(APPROVED_SYMBOLS)
        seen: set[str] = set()
        for evaluation in evaluations:
            if not isinstance(evaluation, Mapping):
                raise PaperBoundaryDiscoveryFeedbackError("runtime evaluation is invalid")
            symbol = str(evaluation.get("symbol", ""))
            if symbol not in boundary or symbol in seen:
                raise PaperBoundaryDiscoveryFeedbackError("runtime evaluation symbol binding is invalid")
            seen.add(symbol)
            last_open = evaluation.get("runtime_last_open_time_ms")
            if (
                isinstance(last_open, bool)
                or not isinstance(last_open, int)
                or last_open < boundary[symbol]
            ):
                all_covered = False
            else:
                covered_evaluations += 1
        if proposal.get("verdict") != "BLOCKED_RUNTIME_DATA" and seen != set(APPROVED_SYMBOLS):
            all_covered = False

    proposal_count = requalification.get("proposal_count")
    blocked_count = requalification.get("blocked_runtime_data_count")
    requalification_status = requalification.get("status")
    discovery_proposal_count = discovery.get("research_proposal_count")
    coverage_verified = bool(
        requalification_status == "EVALUATED"
        and isinstance(proposal_count, int)
        and not isinstance(proposal_count, bool)
        and proposal_count > 0
        and blocked_count == 0
        and required_evaluations == proposal_count * len(APPROVED_SYMBOLS)
        and covered_evaluations == required_evaluations
        and all_covered
    )
    zero_work_verified = bool(
        requalification_status == "NO_WORK"
        and isinstance(proposal_count, int)
        and not isinstance(proposal_count, bool)
        and proposal_count == 0
        and isinstance(discovery_proposal_count, int)
        and not isinstance(discovery_proposal_count, bool)
        and discovery_proposal_count == 0
        and requalification.get("qualified_for_review_count") == 0
        and requalification.get("rejected_count") == 0
        and blocked_count == 0
        and rows == []
        and required_evaluations == 0
        and covered_evaluations == 0
    )
    discovery_feedback_verified = coverage_verified or zero_work_verified
    if coverage_verified:
        status = "VERIFIED_BOUNDARY_FEEDBACK"
    elif zero_work_verified:
        status = "VERIFIED_NO_RESEARCH_PROPOSALS"
    elif proposal_count == 0:
        status = "NO_RESEARCH_PROPOSALS"
    elif blocked_count:
        status = "WAITING_FOR_RUNTIME_DATA"
    else:
        status = "RUNTIME_BOUNDARY_NOT_COVERED"

    core = {
        "schema_version": FEEDBACK_SCHEMA,
        "source_sha": source_sha,
        "paper_run_id": context["paper_run_id"],
        "paper_loop_digest": context["paper_loop_digest"],
        "paper_context_digest": context["context_digest"],
        "hour4_boundary_ms": boundary,
        "hour4_boundary_digest": context["hour4_boundary_digest"],
        "discovery_digest": discovery_digest,
        "requalification_digest": requalification_digest,
        "runtime_requalification_status": requalification_status,
        "proposal_count": proposal_count,
        "qualified_for_review_count": requalification.get("qualified_for_review_count"),
        "rejected_count": requalification.get("rejected_count"),
        "blocked_runtime_data_count": blocked_count,
        "required_runtime_evaluation_count": required_evaluations,
        "boundary_covered_runtime_evaluation_count": covered_evaluations,
        "boundary_coverage_verified": coverage_verified,
        "discovery_feedback_verified": discovery_feedback_verified,
        "status": status,
        "candidate_state_created": False,
        "paper_execution_started": False,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "feedback_digest": _digest(core)}


def verify_feedback(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "lineage": False,
        "counts": False,
        "authority": False,
        "status": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("feedback_digest", None)
        boundary = core.get("hour4_boundary_ms")
        proposal_count = core.get("proposal_count")
        required = core.get("required_runtime_evaluation_count")
        covered = core.get("boundary_covered_runtime_evaluation_count")
        coverage = core.get("boundary_coverage_verified")
        feedback_verified = core.get("discovery_feedback_verified")
        requalification_status = core.get("runtime_requalification_status")
        status = core.get("status")
        checks["schema"] = core.get("schema_version") == FEEDBACK_SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["lineage"] = bool(
            _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and str(core.get("paper_run_id", "")).isdigit()
            and all(
                _HEX64_RE.fullmatch(str(core.get(field, "")))
                for field in (
                    "paper_loop_digest",
                    "paper_context_digest",
                    "hour4_boundary_digest",
                    "discovery_digest",
                    "requalification_digest",
                )
            )
            and isinstance(boundary, Mapping)
            and set(boundary) == set(APPROVED_SYMBOLS)
            and core.get("hour4_boundary_digest") == _digest(dict(boundary))
        )
        checks["counts"] = bool(
            isinstance(proposal_count, int)
            and not isinstance(proposal_count, bool)
            and proposal_count >= 0
            and all(
                isinstance(core.get(field), int)
                and not isinstance(core.get(field), bool)
                and core.get(field) >= 0
                for field in (
                    "qualified_for_review_count",
                    "rejected_count",
                    "blocked_runtime_data_count",
                    "required_runtime_evaluation_count",
                    "boundary_covered_runtime_evaluation_count",
                )
            )
            and core.get("qualified_for_review_count")
            + core.get("rejected_count")
            + core.get("blocked_runtime_data_count")
            == proposal_count
            and covered <= required
        )
        checks["authority"] = bool(
            core.get("candidate_state_created") is False
            and core.get("paper_execution_started") is False
            and core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
        )
        zero_work_verified = bool(
            feedback_verified is True
            and coverage is False
            and proposal_count == 0
            and requalification_status == "NO_WORK"
            and core.get("qualified_for_review_count") == 0
            and core.get("rejected_count") == 0
            and core.get("blocked_runtime_data_count") == 0
            and required == 0
            and covered == 0
        )
        expected_status = (
            "VERIFIED_BOUNDARY_FEEDBACK"
            if feedback_verified is True and coverage is True
            else "VERIFIED_NO_RESEARCH_PROPOSALS"
            if zero_work_verified
            else "NO_RESEARCH_PROPOSALS"
            if proposal_count == 0
            else "WAITING_FOR_RUNTIME_DATA"
            if core.get("blocked_runtime_data_count", 0) > 0
            else "RUNTIME_BOUNDARY_NOT_COVERED"
        )
        checks["status"] = bool(
            isinstance(coverage, bool)
            and isinstance(feedback_verified, bool)
            and status == expected_status
            and (
                (feedback_verified is False and coverage is False)
                or (
                    feedback_verified is True
                    and coverage is True
                    and requalification_status == "EVALUATED"
                    and proposal_count > 0
                    and core.get("blocked_runtime_data_count") == 0
                    and required == proposal_count * len(APPROVED_SYMBOLS)
                    and covered == required
                )
                or zero_work_verified
            )
        )
    except (TypeError, ValueError, KeyError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    context = sub.add_parser("context")
    context.add_argument("--loop-snapshot", type=Path, required=True)
    context.add_argument("--matrix-state", type=Path, required=True)
    context.add_argument("--output", type=Path, required=True)

    feedback = sub.add_parser("feedback")
    feedback.add_argument("--context", type=Path, required=True)
    feedback.add_argument("--discovery", type=Path, required=True)
    feedback.add_argument("--requalification", type=Path, required=True)
    feedback.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "context":
        value = build_boundary_context(
            _read_json(args.loop_snapshot), _read_json(args.matrix_state)
        )
        if verify_boundary_context(value).get("decision") != "pass":
            raise PaperBoundaryDiscoveryFeedbackError("generated boundary context failed verification")
        _atomic_json(args.output, value)
        print(json.dumps(value, sort_keys=True))
        return 0

    value = build_feedback(
        _read_json(args.context),
        _read_json(args.discovery),
        _read_json(args.requalification),
    )
    if verify_feedback(value).get("decision") != "pass":
        raise PaperBoundaryDiscoveryFeedbackError("generated feedback failed verification")
    _atomic_json(args.output, value)
    print(json.dumps(value, sort_keys=True))
    return 0 if value["discovery_feedback_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
