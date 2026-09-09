"""Bind four-symbol Paper health feedback to exact Multi-Pair Discovery v2 proof.

Evidence-only. This module links an exact 12-cell Paper boundary to the already
persisted, independently verified Multi-Pair Discovery v2 physical proof at the
same Git SHA. It does not acquire market data, rerun Discovery/requalification,
create Candidate/Paper state, submit orders, promote strategies, or grant Live/L4
authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from nexus_multipair_persistent_paper_trading_loop import verify_loop_snapshot
from nexus_multipair_trusted_surface import FAMILIES, SYMBOLS, TIMEFRAMES


CONTEXT_SCHEMA = "nexus.multipair-paper-boundary-discovery-context.v1"
FEEDBACK_SCHEMA = "nexus.multipair-paper-boundary-discovery-feedback.v1"
PROOF_SCHEMA = "nexus.multipair-discovery-v2-physical-proof.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_HOUR4_MS = 4 * 60 * 60 * 1000


class MultiPairPaperBoundaryFeedbackError(RuntimeError):
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
        raise MultiPairPaperBoundaryFeedbackError("feedback evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MultiPairPaperBoundaryFeedbackError("feedback input is unavailable") from exc
    if not isinstance(value, dict):
        raise MultiPairPaperBoundaryFeedbackError("feedback input is not an object")
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
        raise MultiPairPaperBoundaryFeedbackError(f"{label} must be a positive integer")
    return value


def _expected_cells() -> list[str]:
    return sorted(f"{symbol}:{timeframe}" for symbol in SYMBOLS for timeframe in TIMEFRAMES)


def build_boundary_context(
    loop_snapshot: Mapping[str, Any], matrix_state: Mapping[str, Any]
) -> dict[str, Any]:
    if verify_loop_snapshot(loop_snapshot).get("decision") != "pass":
        raise MultiPairPaperBoundaryFeedbackError("Multi-Pair Paper-loop snapshot failed verification")

    source_sha = str(loop_snapshot.get("source_sha", "")).strip().lower()
    loop_digest = str(loop_snapshot.get("loop_digest", ""))
    run_id = str(loop_snapshot.get("run_id", ""))
    fresh_cells = loop_snapshot.get("fresh_cells")
    expected_cells = _expected_cells()
    if (
        not _SHA_RE.fullmatch(source_sha)
        or not _HEX64_RE.fullmatch(loop_digest)
        or not run_id.isdigit()
        or loop_snapshot.get("status") != "PAPER_LOOP_ACTIVE"
        or loop_snapshot.get("regime_status") != "VERIFIED"
        or loop_snapshot.get("expected_cell_count") != 12
        or loop_snapshot.get("fresh_cell_count") != 12
        or loop_snapshot.get("expected_lane_count") != 36
        or not isinstance(fresh_cells, list)
        or sorted(str(value) for value in fresh_cells) != expected_cells
        or loop_snapshot.get("strategy_research_required") is not True
        or loop_snapshot.get("strategy_discovery_health_trigger_requested") is not True
        or loop_snapshot.get("regime_selected_rebalance_operational") is not True
        or loop_snapshot.get("performance_health_feedback_operational") is not True
        or loop_snapshot.get("paper_only") is not True
        or loop_snapshot.get("live_trading_authority") is not False
        or loop_snapshot.get("private_credentials_used") is not False
        or loop_snapshot.get("real_exchange_orders") is not False
        or loop_snapshot.get("automatic_strategy_promotion") is not False
        or loop_snapshot.get("deterministic_risk_final_authority") is not True
        or loop_snapshot.get("state_isolated_from_issue_984") is not True
        or loop_snapshot.get("issue_984_state_artifact_touched") is not False
    ):
        raise MultiPairPaperBoundaryFeedbackError(
            "Paper snapshot is not an eligible natural 12-cell health boundary"
        )

    cells = matrix_state.get("cells") if isinstance(matrix_state, Mapping) else None
    if not isinstance(cells, Mapping):
        raise MultiPairPaperBoundaryFeedbackError("matrix state cells are unavailable")

    boundary: dict[str, int] = {}
    for cell_id in expected_cells:
        row = cells.get(cell_id)
        if not isinstance(row, Mapping):
            raise MultiPairPaperBoundaryFeedbackError(f"matrix cell is unavailable: {cell_id}")
        if row.get("status") != "VERIFIED" or row.get("source_sha") != source_sha:
            raise MultiPairPaperBoundaryFeedbackError(
                f"matrix cell is not verified at the exact Paper source SHA: {cell_id}"
            )
        if cell_id.endswith(":hour4"):
            symbol = cell_id.split(":", 1)[0]
            boundary[symbol] = _positive_int(
                row.get("last_completed_open_ms"), f"{cell_id}.last_completed_open_ms"
            )

    if set(boundary) != set(SYMBOLS):
        raise MultiPairPaperBoundaryFeedbackError("four-symbol hour4 boundary is incomplete")

    boundary_digest = _digest(boundary)
    fresh_cell_digest = _digest(expected_cells)
    core = {
        "schema_version": CONTEXT_SCHEMA,
        "source_sha": source_sha,
        "paper_run_id": run_id,
        "paper_loop_digest": loop_digest,
        "symbols": list(SYMBOLS),
        "timeframes": list(TIMEFRAMES),
        "families": list(FAMILIES),
        "fresh_cell_count": 12,
        "fresh_cell_digest": fresh_cell_digest,
        "hour4_boundary_ms": boundary,
        "hour4_boundary_digest": boundary_digest,
        "trigger_reason": "NEW_VERIFIED_12_CELL_4H_BOUNDARY_RESEARCH_REQUIRED",
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
    }
    return {**core, "context_digest": _digest(core)}


def verify_boundary_context(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "surface": False, "boundary": False, "authority": False}
    try:
        core = dict(value)
        claimed = core.pop("context_digest", None)
        boundary = core.get("hour4_boundary_ms")
        checks["schema"] = core.get("schema_version") == CONTEXT_SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["surface"] = bool(
            _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and str(core.get("paper_run_id", "")).isdigit()
            and _HEX64_RE.fullmatch(str(core.get("paper_loop_digest", "")))
            and core.get("symbols") == list(SYMBOLS)
            and core.get("timeframes") == list(TIMEFRAMES)
            and core.get("families") == list(FAMILIES)
            and core.get("fresh_cell_count") == 12
            and core.get("fresh_cell_digest") == _digest(_expected_cells())
        )
        checks["boundary"] = bool(
            isinstance(boundary, Mapping)
            and set(boundary) == set(SYMBOLS)
            and all(
                isinstance(boundary[symbol], int)
                and not isinstance(boundary[symbol], bool)
                and boundary[symbol] > 0
                for symbol in SYMBOLS
            )
            and core.get("hour4_boundary_digest") == _digest(dict(boundary))
            and core.get("trigger_reason") == "NEW_VERIFIED_12_CELL_4H_BOUNDARY_RESEARCH_REQUIRED"
        )
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("state_isolated_from_issue_984") is True
            and core.get("issue_984_state_artifact_touched") is False
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def _validate_discovery_proof(proof: Mapping[str, Any], source_sha: str) -> dict[str, int | str]:
    required_hex = ("snapshot_digest", "discovery_digest", "runtime_snapshot_digest", "requalification_digest")
    if (
        proof.get("schema_version") != PROOF_SCHEMA
        or proof.get("source_sha") != source_sha
        or not str(proof.get("run_id", "")).isdigit()
        or proof.get("execution_plane") != "nexus-bybit-network"
        or proof.get("trusted_surface_source") != "config/nexus-demo-strategy-matrix-v2.json"
        or proof.get("symbols") != list(SYMBOLS)
        or proof.get("timeframes") != list(TIMEFRAMES)
        or proof.get("families") != list(FAMILIES)
        or proof.get("snapshot_cell_count") != 12
        or proof.get("discovery_hypothesis_count") != 9
        or proof.get("runtime_snapshot_history_limit") != 240
        or proof.get("runtime_snapshot_data_origin") != "canonical_public_bybit_closed_candles"
        or proof.get("runtime_snapshot_transport") != "digest_pinned_physical_bybit_rest_snapshot"
        or proof.get("runtime_snapshot_distinct_from_discovery") is not True
        or proof.get("historical_discovery_snapshot_reused") is not False
        or proof.get("runtime_snapshot_freshness_verified") is not True
        or proof.get("blocked_runtime_data_count") != 0
        or proof.get("runtime_data_is_fresh_not_snapshot_reuse") is not True
        or proof.get("research_only") is not True
        or proof.get("paper_only") is not True
        or proof.get("paper_execution_started") is not False
        or proof.get("live_trading_authority") is not False
        or proof.get("private_credentials_used") is not False
        or proof.get("real_exchange_orders") is not False
        or proof.get("automatic_strategy_promotion") is not False
        or proof.get("deterministic_risk_final_authority") is not True
        or proof.get("state_isolated_from_issue_984") is not True
        or proof.get("issue_984_state_artifact_touched") is not False
        or any(not _HEX64_RE.fullmatch(str(proof.get(field, ""))) for field in required_hex)
    ):
        raise MultiPairPaperBoundaryFeedbackError("Multi-Pair Discovery v2 proof contract mismatch")

    status = str(proof.get("requalification_status", ""))
    proposal_count = proof.get("research_proposal_count")
    qualified = proof.get("qualified_for_review_count")
    rejected = proof.get("rejected_count")
    as_of_ms = proof.get("runtime_snapshot_as_of_ms")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in (proposal_count, qualified, rejected)):
        raise MultiPairPaperBoundaryFeedbackError("Discovery proof counts are invalid")
    if isinstance(as_of_ms, bool) or not isinstance(as_of_ms, int) or as_of_ms <= 0:
        raise MultiPairPaperBoundaryFeedbackError("runtime snapshot timestamp is invalid")
    if status == "NO_WORK":
        if proposal_count != 0 or qualified != 0 or rejected != 0:
            raise MultiPairPaperBoundaryFeedbackError("NO_WORK proof contains proposal results")
    elif status == "EVALUATED":
        if proposal_count <= 0 or qualified + rejected != proposal_count:
            raise MultiPairPaperBoundaryFeedbackError("EVALUATED proof counts do not reconcile")
    else:
        raise MultiPairPaperBoundaryFeedbackError("Discovery proof requalification status is invalid")
    return {
        "status": status,
        "proposal_count": proposal_count,
        "qualified": qualified,
        "rejected": rejected,
        "as_of_ms": as_of_ms,
    }


def build_feedback(context: Mapping[str, Any], discovery_proof: Mapping[str, Any]) -> dict[str, Any]:
    if verify_boundary_context(context).get("decision") != "pass":
        raise MultiPairPaperBoundaryFeedbackError("Paper boundary context failed verification")
    source_sha = str(context["source_sha"])
    proof_summary = _validate_discovery_proof(discovery_proof, source_sha)
    boundary = dict(context["hour4_boundary_ms"])
    as_of_ms = int(proof_summary["as_of_ms"])
    expected_runtime_hour4_open_ms = ((as_of_ms - _HOUR4_MS) // _HOUR4_MS) * _HOUR4_MS
    boundary_coverage = bool(
        all(expected_runtime_hour4_open_ms >= int(boundary[symbol]) for symbol in SYMBOLS)
    )
    if not boundary_coverage:
        raise MultiPairPaperBoundaryFeedbackError(
            "fresh runtime requalification snapshot does not cover the Paper hour4 boundary"
        )

    status = (
        "VERIFIED_NO_RESEARCH_PROPOSALS"
        if proof_summary["status"] == "NO_WORK"
        else "VERIFIED_RESEARCH_PROPOSALS_EVALUATED"
    )
    proof_digest = _digest(dict(discovery_proof))
    core = {
        "schema_version": FEEDBACK_SCHEMA,
        "source_sha": source_sha,
        "paper_run_id": context["paper_run_id"],
        "discovery_run_id": str(discovery_proof["run_id"]),
        "paper_loop_digest": context["paper_loop_digest"],
        "paper_context_digest": context["context_digest"],
        "hour4_boundary_ms": boundary,
        "hour4_boundary_digest": context["hour4_boundary_digest"],
        "discovery_proof_digest": proof_digest,
        "discovery_digest": discovery_proof["discovery_digest"],
        "historical_snapshot_digest": discovery_proof["snapshot_digest"],
        "runtime_snapshot_digest": discovery_proof["runtime_snapshot_digest"],
        "runtime_snapshot_as_of_ms": as_of_ms,
        "runtime_expected_hour4_open_ms": expected_runtime_hour4_open_ms,
        "requalification_digest": discovery_proof["requalification_digest"],
        "runtime_requalification_status": proof_summary["status"],
        "proposal_count": proof_summary["proposal_count"],
        "qualified_for_review_count": proof_summary["qualified"],
        "rejected_count": proof_summary["rejected"],
        "blocked_runtime_data_count": 0,
        "paper_boundary_coverage_verified": True,
        "discovery_feedback_verified": True,
        "status": status,
        "candidate_state_created": False,
        "paper_execution_started": False,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
    }
    return {**core, "feedback_digest": _digest(core)}


def verify_feedback(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {"schema": False, "digest": False, "lineage": False, "counts": False, "coverage": False, "authority": False, "status": False}
    try:
        core = dict(value)
        claimed = core.pop("feedback_digest", None)
        boundary = core.get("hour4_boundary_ms")
        proposal_count = core.get("proposal_count")
        qualified = core.get("qualified_for_review_count")
        rejected = core.get("rejected_count")
        requal_status = core.get("runtime_requalification_status")
        checks["schema"] = core.get("schema_version") == FEEDBACK_SCHEMA
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        checks["lineage"] = bool(
            _SHA_RE.fullmatch(str(core.get("source_sha", "")))
            and str(core.get("paper_run_id", "")).isdigit()
            and str(core.get("discovery_run_id", "")).isdigit()
            and all(
                _HEX64_RE.fullmatch(str(core.get(field, "")))
                for field in (
                    "paper_loop_digest", "paper_context_digest", "hour4_boundary_digest",
                    "discovery_proof_digest", "discovery_digest", "historical_snapshot_digest",
                    "runtime_snapshot_digest", "requalification_digest",
                )
            )
            and isinstance(boundary, Mapping)
            and set(boundary) == set(SYMBOLS)
            and core.get("hour4_boundary_digest") == _digest(dict(boundary))
        )
        checks["counts"] = bool(
            all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (proposal_count, qualified, rejected))
            and core.get("blocked_runtime_data_count") == 0
            and (
                (requal_status == "NO_WORK" and proposal_count == qualified == rejected == 0)
                or (requal_status == "EVALUATED" and proposal_count > 0 and qualified + rejected == proposal_count)
            )
        )
        as_of_ms = core.get("runtime_snapshot_as_of_ms")
        expected_open = core.get("runtime_expected_hour4_open_ms")
        checks["coverage"] = bool(
            isinstance(as_of_ms, int) and not isinstance(as_of_ms, bool) and as_of_ms > 0
            and isinstance(expected_open, int) and not isinstance(expected_open, bool)
            and expected_open == ((as_of_ms - _HOUR4_MS) // _HOUR4_MS) * _HOUR4_MS
            and all(expected_open >= int(boundary[symbol]) for symbol in SYMBOLS)
            and core.get("paper_boundary_coverage_verified") is True
            and core.get("discovery_feedback_verified") is True
        )
        checks["authority"] = bool(
            core.get("candidate_state_created") is False
            and core.get("paper_execution_started") is False
            and core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("live_trading_authority") is False
            and core.get("private_credentials_used") is False
            and core.get("real_exchange_orders") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("deterministic_risk_final_authority") is True
            and core.get("state_isolated_from_issue_984") is True
            and core.get("issue_984_state_artifact_touched") is False
        )
        checks["status"] = bool(
            (requal_status == "NO_WORK" and core.get("status") == "VERIFIED_NO_RESEARCH_PROPOSALS")
            or (requal_status == "EVALUATED" and core.get("status") == "VERIFIED_RESEARCH_PROPOSALS_EVALUATED")
        )
    except (KeyError, TypeError, ValueError):
        pass
    return {"decision": "pass" if all(checks.values()) else "reject", "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    context = sub.add_parser("context")
    context.add_argument("--loop-snapshot", type=Path, required=True)
    context.add_argument("--matrix-state", type=Path, required=True)
    context.add_argument("--output", type=Path, required=True)
    feedback = sub.add_parser("feedback")
    feedback.add_argument("--context", type=Path, required=True)
    feedback.add_argument("--discovery-proof", type=Path, required=True)
    feedback.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "context":
        result = build_boundary_context(_read_json(args.loop_snapshot), _read_json(args.matrix_state))
        if verify_boundary_context(result).get("decision") != "pass":
            raise MultiPairPaperBoundaryFeedbackError("generated boundary context failed verification")
    else:
        result = build_feedback(_read_json(args.context), _read_json(args.discovery_proof))
        if verify_feedback(result).get("decision") != "pass":
            raise MultiPairPaperBoundaryFeedbackError("generated feedback failed verification")
    _atomic_json(args.output, result)
    print(json.dumps({"decision": "pass", "schema_version": result["schema_version"], "digest": result.get("context_digest") or result.get("feedback_digest")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
