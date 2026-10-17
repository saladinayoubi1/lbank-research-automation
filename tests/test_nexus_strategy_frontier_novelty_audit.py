"""Adversarial no-replay classification tests using synthetic digest-bound source evidence."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from nexus_strategy_frontier_novelty_audit import NoveltyTriageError, audit


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _inputs():
    catalog = json.loads(
        (ROOT / "research/reviewed_composite_mechanisms_v1.json").read_text("utf-8")
    )
    cert_core = {
        "schema_version": "nexus.multitimeframe-search-exhaustion.v1",
        "source_sha": "a" * 40,
        "dataset_semantic_sha256": "b" * 64,
        "dataset_archive_sha256": "b" * 64,
        "neighborhood_fingerprint": "c" * 64,
        "base_research_proposal_count": 0,
        "refined_research_proposal_count": 0,
        "selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "exhausted": True,
        "reuse_policy": "exact_static_neighborhood_only",
        "research_only": True, "paper_only": True,
        "automatic_strategy_promotion": False, "live_trading_authority": False,
    }
    certificate = {**cert_core, "certificate_digest": _digest(cert_core)}
    run = {
        "id": 1234, "name": "NEXUS multi-timeframe strategy discovery",
        "head_branch": "main", "event": "workflow_dispatch",
        "status": "completed", "conclusion": "success",
        "head_sha": "a" * 40,
        "repository": {"full_name": "saladinayoubi1/lbank-research-automation"},
    }
    ledger_core = {
        "schema": "nexus.automatic-composite-novelty-ledger.v1",
        "archive_sha256": "b" * 64,
        "mechanisms_evaluated": ["cross_pair_relative_reclaim"],
        "config_fingerprints_evaluated": ["e" * 64],
        "frontier_screened_mechanisms": ["trend_vwap_pullback_reclaim"],
        "frontier_screening_version": "nexus.frontier-train-screen.v6",
        "research_only": True,
        "auto_demo_promotion": False, "live_enabled": False,
    }
    ledger = {**ledger_core, "ledger_digest": _digest(ledger_core)}
    return run, certificate, ledger, catalog


def test_retains_difference_between_evaluated_screened_missing_and_unrecorded():
    run, cert, ledger, catalog = _inputs()
    report = audit(run, cert, ledger, catalog)
    lookup = {row["mechanism_id"]: row for row in report["review_queue"]}
    assert lookup["cross_pair_relative_reclaim"]["status"] == "ALREADY_EVALUATED"
    assert lookup["trend_vwap_pullback_reclaim"]["status"] == "TRAINING_SCREENED"
    assert lookup["multi_tf_structural_retest"]["status"] == "IDENTITY_ABSENT_SEMANTIC_REVIEW_REQUIRED"
    assert lookup["liquidity_microstructure_mean_revert"]["status"] == "INPUT_PROOF_REQUIRED"
    assert not any(row["semantic_novelty_proven"] or row["dispatch_allowed"] for row in report["review_queue"])
    assert report["reviewed_design_count"] == len(catalog["mechanisms"])
    assert sum(report["classification_counts"].values()) == report["reviewed_design_count"]
    assert report["historical_ledger_counts"] == {
        "evaluated_mechanisms": 1,
        "training_screened_mechanisms": 1,
        "evaluated_configuration_fingerprints": 1,
    }
    assert report["research_only"] is True
    assert report["live_trading_authority"] is False
    assert report["automatic_strategy_promotion"] is False
    assert report["audit_sha256"] == _digest({k:v for k,v in report.items() if k!="audit_sha256"})


@pytest.mark.parametrize("change", [
    "run_sha", "run_failed", "wrong_repo", "certificate_exhaustion",
    "certificate_digest", "ledger_digest", "dataset_scope",
    "auto_promotion", "duplicate_catalog", "not_real_main",
])
def test_any_modified_or_untrusted_exact_source_fails_closed(change):
    run, cert, ledger, catalog = _inputs()
    if change == "run_sha":
        run["head_sha"] = "f" * 40
    elif change == "run_failed":
        run["conclusion"] = "failure"
    elif change == "wrong_repo":
        run["repository"]["full_name"] = "attacker/fake"
    elif change == "certificate_exhaustion":
        cert["exhausted"] = False
    elif change == "certificate_digest":
        cert["certificate_digest"] = "0" * 64
    elif change == "ledger_digest":
        ledger["ledger_digest"] = "0" * 64
    elif change == "dataset_scope":
        ledger["archive_sha256"] = "0" * 64
    elif change == "auto_promotion":
        ledger["auto_demo_promotion"] = True
    elif change == "duplicate_catalog":
        catalog["mechanisms"].append(dict(catalog["mechanisms"][0]))
    elif change == "not_real_main":
        run["head_branch"] = "feature"
    with pytest.raises(NoveltyTriageError, match="invalid"):
        audit(run, cert, ledger, catalog)


def test_training_screened_is_not_a_new_candidate_even_if_unevaluated():
    run, cert, ledger, catalog = _inputs()
    report = audit(run, cert, ledger, catalog)
    selected = next(row for row in report["review_queue"] if row["mechanism_id"] == "trend_vwap_pullback_reclaim")
    assert selected["registered_in_training_screen"] is True
    assert selected["registered_in_evaluated_ledger"] is False
    assert selected["independently_backtested_as_this_design"] is False
    assert selected["qualification_authority"] is False
    assert "review" in selected["next_gate"] or "inspect" in selected["next_gate"]


def test_disjoint_data_proof_classifications_cannot_claim_profit():
    run, cert, ledger, catalog = _inputs()
    report = audit(run, cert, ledger, catalog)
    for row in report["review_queue"]:
        assert not row["semantic_novelty_proven"]
        assert not row["dispatch_allowed"]
    assert report["new_strategy_proven_profitable"] is False
    assert report["novel_design_verified"] is False
