from __future__ import annotations

import pytest

import nexus_multipair_paper_boundary_discovery_feedback as boundary
import nexus_strategy_discovery_health_trigger as health_mod
from scripts.nexus_public_paper_boundary_proof import (
    PublicPaperBoundaryProofError,
    validate_public_evidence,
)


SOURCE_SHA = "a" * 40
RUN_ID = "123456789"
LOOP_DIGEST = "b" * 64


def _health() -> dict:
    core = {
        "schema_version": health_mod.SCHEMA,
        "source_sha": SOURCE_SHA,
        "run_id": RUN_ID,
        "loop_digest": LOOP_DIGEST,
        "should_dispatch": True,
        "reason_code": "NEW_4H_BOUNDARY_RESEARCH_REQUIRED",
        "trigger_scope": "new_verified_4h_boundary_only",
        "daily_rotation_remains_required": True,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "trigger_digest": health_mod._digest(core)}


def _context() -> dict:
    hour4 = {
        "BTCUSDT": 1_000,
        "ETHUSDT": 2_000,
        "SOLUSDT": 3_000,
        "XRPUSDT": 4_000,
    }
    core = {
        "schema_version": boundary.CONTEXT_SCHEMA,
        "source_sha": SOURCE_SHA,
        "paper_run_id": RUN_ID,
        "paper_loop_digest": LOOP_DIGEST,
        "symbols": list(boundary.SYMBOLS),
        "timeframes": list(boundary.TIMEFRAMES),
        "families": list(boundary.FAMILIES),
        "fresh_cell_count": 12,
        "fresh_cell_digest": boundary._digest(boundary._expected_cells()),
        "hour4_boundary_ms": hour4,
        "hour4_boundary_digest": boundary._digest(hour4),
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
    return {**core, "context_digest": boundary._digest(core)}


def test_public_boundary_evidence_is_exact_run_bound_and_authority_closed() -> None:
    validate_public_evidence(
        _health(), _context(), source_sha=SOURCE_SHA, run_id=RUN_ID, require_context=True
    )


def test_public_boundary_evidence_rejects_cross_run_context() -> None:
    context = _context()
    core = dict(context)
    core.pop("context_digest")
    core["paper_run_id"] = "987654321"
    context = {**core, "context_digest": boundary._digest(core)}

    with pytest.raises(PublicPaperBoundaryProofError, match="exact-run binding"):
        validate_public_evidence(
            _health(), context, source_sha=SOURCE_SHA, run_id=RUN_ID, require_context=True
        )


def test_public_evidence_contains_no_runtime_account_surface() -> None:
    keys = set(_health()) | set(_context())
    forbidden = {
        "balance",
        "equity",
        "positions",
        "open_positions",
        "orders",
        "order_history",
        "journal",
        "api_key",
        "api_secret",
        "credential_value",
    }
    assert keys.isdisjoint(forbidden)