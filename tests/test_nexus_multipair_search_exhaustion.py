from __future__ import annotations

import copy
from pathlib import Path

import pytest

from nexus_multipair_search_exhaustion import (
    IMPLEMENTATION_FILES,
    MultiPairExhaustionError,
    build_certificate,
    build_fresh_no_work,
    build_neighborhood,
    build_reuse_evidence,
    certificate_is_reusable,
    verify_certificate,
    verify_fresh_no_work,
    verify_neighborhood,
    verify_reuse_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multipair_strategy_discovery_v2.json"
SOURCE_SHA = "a" * 40
SNAPSHOT_DIGEST = "b" * 64
RUNTIME_DIGEST = "e" * 64


def _neighborhood(**kwargs):
    return build_neighborhood(
        MANIFEST,
        source_sha=kwargs.get("source_sha", SOURCE_SHA),
        snapshot_digest=kwargs.get("snapshot_digest", SNAPSHOT_DIGEST),
        root=kwargs.get("root", ROOT),
    )


def _proof(neighborhood=None, **overrides):
    neighborhood = neighborhood or _neighborhood()
    value = {
        "schema_version": "nexus.multipair-discovery-v2-physical-proof.v1",
        "source_sha": SOURCE_SHA,
        "run_id": "12345",
        "physical_runner_name": "NEXUS-BYBIT-WSL",
        "physical_runner_os": "Linux",
        "physical_runner_environment": "self-hosted",
        "execution_plane": "nexus-bybit-network",
        "trusted_surface_source": "config/nexus-demo-strategy-matrix-v2.json",
        "snapshot_transport": "digest_pinned_current_run_github_artifact",
        "snapshot_data_origin": "official_public_bybit_spot_trade_archive_aggregated",
        "snapshot_runtime_freshness_claimed": False,
        "snapshot_cell_count": 12,
        "snapshot_history_limit": 500,
        "snapshot_digest": SNAPSHOT_DIGEST,
        "snapshot_as_of_ms": 1_700_000,
        "discovery_digest": "c" * 64,
        "discovery_hypothesis_count": 9,
        "refinement_training_basis_digest": "d" * 64,
        "runtime_snapshot_digest": RUNTIME_DIGEST,
        "requalification_digest": "f" * 64,
        "search_neighborhood_fingerprint": neighborhood["neighborhood_fingerprint"],
        "base_research_proposal_count": 0,
        "refinement_started": True,
        "refinement_selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "refinement_targeted_cells": [{"family": "trend_breakout", "timeframe": "hour1"}],
        "refinement_variant_counts": {"momentum": 2, "trend_breakout": 6, "mean_reversion": 2},
        "effective_research_proposal_count": 0,
        "research_proposal_count": 0,
        "selection_policy": "training_only_rank_then_locked_holdout",
        "multiplicity_policy": "bounded_family_hypotheses",
        "requalification_status": "NO_WORK",
        "qualified_for_review_count": 0,
        "rejected_count": 0,
        "blocked_runtime_data_count": 0,
        "runtime_snapshot_freshness_verified": True,
        "runtime_snapshot_distinct_from_discovery": True,
        "historical_discovery_snapshot_reused": False,
        "runtime_data_is_fresh_not_snapshot_reuse": True,
        "physical_discovery_skipped_exact_exhaustion": False,
        "historical_discovery_result_reused_exact_exhaustion": False,
        "runtime_requalification_skipped_no_proposals": False,
        "research_only": True,
        "paper_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "real_exchange_orders": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "state_isolated_from_issue_984": True,
        "issue_984_state_artifact_touched": False,
        "persistent_runtime_database_on_github": False,
        "legacy_btc_eth_discovery_archive_used": False,
        "zero_proposal_result_is_valid": True,
    }
    value.update(overrides)
    return value


def _runtime_snapshot(**overrides):
    value = {
        "schema_version": "nexus.multipair-discovery-snapshot.v1",
        "source_sha": SOURCE_SHA,
        "snapshot_digest": RUNTIME_DIGEST,
        "as_of_ms": 1_790_000,
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
        "timeframes": ["minute15", "hour1", "hour4"],
        "cell_count": 12,
        "history_limit": 240,
        "data_origin": "canonical_public_bybit_closed_candles",
        "research_only": True,
        "paper_execution_started": False,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "silent_exchange_substitution": False,
    }
    value.update(overrides)
    return value


def test_exact_zero_proposal_physical_proof_certifies_and_reuses() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    verify_neighborhood(neighborhood)
    verify_certificate(certificate)
    assert certificate_is_reusable(neighborhood, certificate) is True
    assert certificate["base_research_proposal_count"] == 0
    assert certificate["refined_research_proposal_count"] == 0
    assert certificate["fresh_runtime_snapshot_required_on_reuse"] is True
    assert certificate["reuse_policy"] == "exact_snapshot_and_implementation_only"


def test_reuse_misses_when_snapshot_or_source_changes() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    assert certificate_is_reusable(_neighborhood(snapshot_digest="1" * 64), certificate) is False
    changed_source = _neighborhood(source_sha="2" * 40)
    assert certificate_is_reusable(changed_source, certificate) is False


def test_implementation_hash_is_part_of_exact_neighborhood(tmp_path: Path) -> None:
    for name in IMPLEMENTATION_FILES:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"placeholder:{name}\n", encoding="utf-8")
    first = build_neighborhood(
        MANIFEST,
        source_sha=SOURCE_SHA,
        snapshot_digest=SNAPSHOT_DIGEST,
        root=tmp_path,
    )
    target = tmp_path / "nexus_multipair_training_refinement.py"
    target.write_text("changed implementation\n", encoding="utf-8")
    second = build_neighborhood(
        MANIFEST,
        source_sha=SOURCE_SHA,
        snapshot_digest=SNAPSHOT_DIGEST,
        root=tmp_path,
    )
    assert first["neighborhood_fingerprint"] != second["neighborhood_fingerprint"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("base_research_proposal_count", 1),
        ("refinement_started", False),
        ("refinement_selection_basis", "locked_holdout"),
        ("locked_holdout_used_for_refinement", True),
        ("effective_research_proposal_count", 1),
        ("research_proposal_count", 1),
        ("requalification_status", "EVALUATED"),
        ("physical_discovery_skipped_exact_exhaustion", True),
        ("historical_discovery_result_reused_exact_exhaustion", True),
        ("runtime_snapshot_freshness_verified", False),
        ("runtime_snapshot_distinct_from_discovery", False),
        ("runtime_data_is_fresh_not_snapshot_reuse", False),
        ("live_trading_authority", True),
        ("private_credentials_used", True),
        ("automatic_strategy_promotion", True),
    ],
)
def test_certificate_fails_closed_for_non_exhausted_or_widened_proof(field: str, value: object) -> None:
    neighborhood = _neighborhood()
    with pytest.raises(MultiPairExhaustionError):
        build_certificate(neighborhood, _proof(neighborhood, **{field: value}))


def test_reuse_evidence_skips_only_historical_discovery() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    evidence = build_reuse_evidence(neighborhood, certificate, run_id="67890")
    assert verify_reuse_evidence(evidence)["decision"] == "pass"
    assert evidence["physical_discovery_skipped_exact_exhaustion"] is True
    assert evidence["historical_discovery_result_reused_exact_exhaustion"] is True
    assert evidence["fresh_runtime_snapshot_required"] is True
    assert evidence["runtime_snapshot_skipped_no_proposals"] is False
    assert evidence["runtime_requalification_skipped_no_proposals"] is True
    assert evidence["live_trading_authority"] is False


def test_reuse_evidence_tampering_is_rejected() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    evidence = build_reuse_evidence(neighborhood, certificate, run_id="67890")
    tampered = copy.deepcopy(evidence)
    tampered["runtime_snapshot_skipped_no_proposals"] = True
    assert verify_reuse_evidence(tampered)["decision"] == "reject"


def test_reuse_evidence_requires_exact_certificate_match() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    with pytest.raises(MultiPairExhaustionError):
        build_reuse_evidence(_neighborhood(snapshot_digest="9" * 64), certificate, run_id="67890")


def test_fresh_runtime_snapshot_is_required_before_reuse_can_emit_no_work() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    reuse = build_reuse_evidence(neighborhood, certificate, run_id="67890")
    bound = build_fresh_no_work(reuse, _runtime_snapshot(), now_ms=1_800_000)
    assert verify_fresh_no_work(bound)["decision"] == "pass"
    assert bound["status"] == "NO_WORK"
    assert bound["runtime_snapshot_digest"] == RUNTIME_DIGEST
    assert bound["runtime_snapshot_digest"] != bound["historical_snapshot_digest"]
    assert bound["runtime_snapshot_freshness_verified"] is True
    assert bound["runtime_requalification_skipped_no_proposals"] is True
    assert bound["candidate_creation_authority"] is False
    assert bound["live_trading_authority"] is False


def test_stale_or_historical_runtime_snapshot_cannot_satisfy_reuse() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    reuse = build_reuse_evidence(neighborhood, certificate, run_id="67890")
    with pytest.raises(MultiPairExhaustionError):
        build_fresh_no_work(reuse, _runtime_snapshot(as_of_ms=1), now_ms=2_000_000)
    with pytest.raises(MultiPairExhaustionError):
        build_fresh_no_work(
            reuse,
            _runtime_snapshot(snapshot_digest=SNAPSHOT_DIGEST),
            now_ms=1_800_000,
        )


def test_runtime_source_or_authority_mismatch_fails_closed() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    reuse = build_reuse_evidence(neighborhood, certificate, run_id="67890")
    with pytest.raises(MultiPairExhaustionError):
        build_fresh_no_work(reuse, _runtime_snapshot(source_sha="2" * 40), now_ms=1_800_000)
    with pytest.raises(MultiPairExhaustionError):
        build_fresh_no_work(reuse, _runtime_snapshot(live_trading_authority=True), now_ms=1_800_000)


def test_fresh_no_work_tampering_is_rejected() -> None:
    neighborhood = _neighborhood()
    certificate = build_certificate(neighborhood, _proof(neighborhood))
    reuse = build_reuse_evidence(neighborhood, certificate, run_id="67890")
    bound = build_fresh_no_work(reuse, _runtime_snapshot(), now_ms=1_800_000)
    tampered = copy.deepcopy(bound)
    tampered["runtime_snapshot_freshness_verified"] = False
    assert verify_fresh_no_work(tampered)["decision"] == "reject"


def test_exact_implementation_surface_includes_exhaustion_and_workflow_contract() -> None:
    assert "nexus_multipair_search_exhaustion.py" in IMPLEMENTATION_FILES
    assert ".github/workflows/nexus_multipair_strategy_discovery_v2.yml" in IMPLEMENTATION_FILES
    assert "config/nexus-demo-strategy-matrix-v2.json" in IMPLEMENTATION_FILES
    assert "requirements.lock" in IMPLEMENTATION_FILES
