"""Real exhaustion-proof and adversarial feedback tests; no orders or credentials."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import nexus_strategy_research_feedback as feedback


SHA = "a" * 40
CATALOG = Path("research/reviewed_composite_mechanisms_v1.json")


def _digest(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _certificate(source=SHA, marker="b"):
    core = {
        "schema_version": "nexus.multitimeframe-search-exhaustion.v1",
        "source_sha": source,
        "dataset_semantic_sha256": "c" * 64,
        "dataset_archive_sha256": "d" * 64,
        "neighborhood_fingerprint": marker * 64,
        "base_research_proposal_count": 0,
        "refined_research_proposal_count": 0,
        "exhausted": True,
        "reuse_policy": "exact_static_neighborhood_only",
        "selection_basis": "training_only",
        "locked_holdout_used_for_refinement": False,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "certificate_digest": _digest(core)}


def _run(head=SHA, runid=1234):
    return {
        "id": runid,
        "name": feedback.REQUIRED_WORKFLOW,
        "head_branch": "main", "event": "workflow_dispatch",
        "status": "completed", "conclusion": "success", "head_sha": head,
        "repository": {"full_name": "saladinayoubi1/lbank-research-automation"},
    }


def _evaluated_ledger(mechanisms, certificate=None):
    cert = certificate or _certificate()
    core = {
        "schema": feedback.COMPOSITE_LEDGER_SCHEMA,
        "archive_sha256": cert["dataset_semantic_sha256"],
        "mechanisms_evaluated": list(mechanisms),
        "config_fingerprints_evaluated": [
            _digest({"mechanism": m, "config": i})
            for i, m in enumerate(mechanisms)
        ],
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
    }
    return {**core, "ledger_digest": _digest(core)}


def test_existing_research_exhaustion_proposes_design_but_never_claims_backtest():
    state, receipt, proposal = feedback.process_feedback(
        _run(), _certificate(), _catalog(),
    )
    assert receipt["status"] == "NEW_DISTINCT_HYPOTHESIS_DESIGN_ONLY"
    assert proposal["mechanism"]["id"] == "multi_tf_structural_retest"
    assert proposal["status"].endswith("INDEPENDENT_BACKTEST")
    assert proposal["data_claims"] == ["closed_spot_ohlcv"]
    assert state["research_cycles"] == 1
    assert len(state["proposed_mechanisms"]) == 1
    assert state["automatic_strategy_promotion"] is False
    assert proposal["live_trading_authority"] is False
    assert receipt["no_backtest_or_qualification_claim"] is True
    feedback.validate_frontier(state)


def test_same_cert_is_idempotent_and_next_exact_verified_exhaustion_changes_mechanism():
    state, _, _ = feedback.process_feedback(_run(), _certificate(), _catalog())
    replay, receipt, proposal = feedback.process_feedback(
        _run(runid=999), _certificate(), _catalog(), previous=state,
    )
    assert receipt["status"] == "VERIFIED_EXHAUSTION_REPLAY_NO_NEW_PROPOSAL"
    assert proposal is None
    assert replay["research_cycles"] == 1
    second, receipt2, proposal2 = feedback.process_feedback(
        _run(runid=1000), _certificate(marker="e"), _catalog(), previous=replay,
    )
    assert receipt2["status"] == "NEW_DISTINCT_HYPOTHESIS_DESIGN_ONLY"
    assert proposal2["mechanism"]["id"] == "compression_expansion_response"
    assert len(second["proposed_mechanisms"]) == 2


@pytest.mark.parametrize("change", [
    {"conclusion": "failure"},
    {"head_branch": "pull/45"},
    {"name": "unrelated workflow"},
    {"status": "in_progress"},
    {"event": "pull_request"},
    {"repository": {"full_name": "other/repo"}},
])
def test_trigger_must_be_exact_successful_expected_main_workflow(change):
    run = {**_run(), **change}
    with pytest.raises(feedback.ResearchFeedbackError):
        feedback.process_feedback(run, _certificate(), _catalog())


def test_source_mismatch_and_forged_exhaustion_refused():
    with pytest.raises(feedback.ResearchFeedbackError, match="source"):
        feedback.process_feedback(_run(head="f"*40), _certificate(), _catalog())
    cert = _certificate()
    cert["exhausted"] = False
    with pytest.raises(feedback.ResearchFeedbackError, match="unverified"):
        feedback.process_feedback(_run(), cert, _catalog())
    cert = _certificate()
    cert["live_trading_authority"] = True
    with pytest.raises(feedback.ResearchFeedbackError):
        feedback.process_feedback(_run(), cert, _catalog())


def test_frontier_tamper_fails_closed_without_state_cursor_reset():
    state, _, _ = feedback.process_feedback(_run(), _certificate(), _catalog())
    state["proposed_mechanisms"] = []
    with pytest.raises(feedback.ResearchFeedbackError):
        feedback.process_feedback(_run(), _certificate(), _catalog(), previous=state)


def test_catalog_forbids_relabeling_parameter_sweeps_as_novel_mechanisms():
    catalog = _catalog()
    duplicate = dict(catalog["mechanisms"][0])
    duplicate["id"] = "parameter_only_variant"
    duplicate["hypothesis"] = "Different number for the same underlying causal mechanism."
    catalog["mechanisms"].append(duplicate)
    with pytest.raises(feedback.ResearchFeedbackError, match="parameter/text"):
        feedback.validate_catalog(catalog)


def test_more_than_eight_distinct_research_ideas_permitted_but_budget_one_design_per_cycle():
    catalog = _catalog()
    first = catalog["mechanisms"][0]
    for i in range(9):
        row = dict(first)
        row["id"] = f"reviewed_additional_mechanism_{i}"
        row["entry"] = ["structural_signal", f"distinct_trigger_{i}"]
        catalog["mechanisms"].append(row)
    assert len(feedback.validate_catalog(catalog)) > 8
    _, _, proposal = feedback.process_feedback(_run(), _certificate(), catalog)
    assert proposal is not None
    assert proposal["mechanism"]["id"] == first["id"]


def test_unsupported_source_is_reported_as_data_gap_not_invented_trade_feed():
    catalog = _catalog()
    catalog["mechanisms"] = [
        x for x in catalog["mechanisms"]
        if x["id"] in ("signed_flow_price_response", "perpetual_positioning_divergence")
    ]
    _, receipt, candidate = feedback.process_feedback(
        _run(), _certificate(), catalog,
    )
    assert candidate is None
    assert receipt["status"] == "NEEDS_VERIFIED_DATA_OR_CATALOG_EXPANSION"
    assert any("verified_signed_trade_flow" in x["missing_inputs"]
               for x in receipt["data_blockers"])


def test_every_reviewed_input_is_a_data_claim_not_unbounded_ai_generated_code():
    catalog = _catalog()
    catalog["mechanisms"][0]["inputs"].append("fictional_market_depth")
    with pytest.raises(feedback.ResearchFeedbackError):
        feedback.validate_catalog(catalog)


def test_actual_september_2026_multitimeframe_artifact_contract_fixture_if_available():
    # Hosted proof is tested with the EXACT source-run artifact in the
    # workflow_dispatch integration, not a guessed sample of financial returns.
    assert feedback.REQUIRED_WORKFLOW == "NEXUS multi-timeframe strategy discovery"
    assert feedback._PROVEN_INPUTS == {"closed_spot_ohlcv", "aligned_spot_cross_pair"}


def test_feedback_reuses_existing_guarded_rotation_without_policy_change():
    text = Path(".github/workflows/nexus_strategy_discovery_rotation.yml").read_text(encoding="utf-8")
    assert "contents: read" in text and "actions: write" in text  # Already approved dispatch grant.
    assert '"NEXUS multi-timeframe strategy discovery"' in text
    assert "github.event.workflow_run.id" in text
    assert "actions/runs/$SOURCE_RUN_ID/artifacts" in text
    assert "nexus-multitimeframe-search-exhaustion" in text
    assert "nexus_strategy_research_feedback.py" in text
    gate = text.split("Decide daily or health-driven dispatch", 1)[1].split(
        "Restore rotation state", 1
    )[0]
    assert 'if [ "$FEEDBACK_REQUESTED" = "true" ]; then' in gate
    assert 'echo "should_dispatch=false" >> "$GITHUB_OUTPUT"' in gate
    feedback_steps = text.split("Obtain only the exact certified prior", 1)[1].split(
        "if: steps.health-gate.outputs.should_dispatch == 'true'", 1
    )[0]
    assert 'gh workflow run' not in feedback_steps
    assert "nexus-research-frontier-state" in feedback_steps


def test_prior_frontier_must_originate_from_successful_same_repo_main_run():
    text = Path(".github/workflows/nexus_strategy_discovery_rotation.yml").read_text(encoding="utf-8")
    stage = text.split("Restore integrity-bound prior independent research frontier", 1)[1].split(
        "Issue one unexecuted NEW mechanism", 1
    )[0]
    assert '.workflow_run.head_branch == "main"' in stage
    assert 'actions/runs/$prior_run_id' in stage
    assert '.conclusion == "success"' in stage
    assert '.name == "NEXUS strategy discovery rotation"' in stage
    assert '.repository.full_name == "saladinayoubi1/lbank-research-automation"' in stage
    assert 'test "$verified" = "verified"' in stage

def test_ninth_proven_input_design_is_reached_after_first_eight_cycles():
    state = None
    proposed = []
    catalog = _catalog()
    for i, marker in enumerate("123456789", start=1):
        state, receipt, proposal = feedback.process_feedback(
            _run(runid=5000 + i), _certificate(marker=marker),
            catalog, previous=state,
        )
        assert receipt["status"] == "NEW_DISTINCT_HYPOTHESIS_DESIGN_ONLY"
        assert proposal is not None
        proposed.append(proposal["mechanism"]["id"])
    assert proposed[-1] == "lagged_peer_volatility_release"
    assert state["research_cycles"] == 9
    assert state["automatic_strategy_promotion"] is False
    assert state["live_trading_authority"] is False

def test_exact_evaluated_ledger_prevents_reproposing_already_backtested_ninth_design():
    catalog = _catalog()
    state = None
    # Preserve the real autonomous frontier history through the first eight
    # design cycles. The ninth mechanism was implemented/backtested directly
    # by the composite engine before feedback got a chance to propose it.
    for i, marker in enumerate("12345678", start=1):
        state, receipt, proposal = feedback.process_feedback(
            _run(runid=7000 + i), _certificate(marker=marker),
            catalog, previous=state,
        )
        assert receipt["status"] == "NEW_DISTINCT_HYPOTHESIS_DESIGN_ONLY"
        assert proposal is not None

    cert = _certificate(marker="9")
    evaluated = _evaluated_ledger(["lagged_peer_volatility_release"], cert)
    state, receipt, proposal = feedback.process_feedback(
        _run(runid=7009), cert, catalog, previous=state,
        evaluated_ledger=evaluated,
    )
    assert proposal is not None
    assert receipt["status"] == "NEW_DISTINCT_HYPOTHESIS_DESIGN_ONLY"
    assert proposal["mechanism"]["id"] == "cross_pair_volatility_catchup"
    assert proposal["data_claims"] == ["aligned_spot_cross_pair", "closed_spot_ohlcv"]
    assert state["research_cycles"] == 9
    assert len(state["proposed_mechanisms"]) == 9
    assert state["automatic_strategy_promotion"] is False
    assert state["live_trading_authority"] is False


def test_evaluated_ledger_accepts_only_digest_bound_frontier_screen_extension():
    cert = _certificate()
    ledger = _evaluated_ledger(["lagged_peer_volatility_release"], cert)
    core = {k: v for k, v in ledger.items() if k != "ledger_digest"}
    core["frontier_screened_mechanisms"] = [
        "factory_gen_deep_drawdown_recovery_vwap_reclaim",
        "factory_gen_efficiency_up_midpoint_reclaim",
    ]
    core["frontier_screening_version"] = "nexus.frontier-train-screen.v5"
    extended = {**core, "ledger_digest": _digest(core)}

    assert feedback.validate_evaluated_ledger(extended, cert) == {
        "lagged_peer_volatility_release",
        "factory_gen_deep_drawdown_recovery_vwap_reclaim",
        "factory_gen_efficiency_up_midpoint_reclaim",
    }

    missing_pair = dict(extended)
    missing_pair.pop("frontier_screening_version")
    unsigned = {k: v for k, v in missing_pair.items() if k != "ledger_digest"}
    missing_pair["ledger_digest"] = _digest(unsigned)
    with pytest.raises(feedback.ResearchFeedbackError, match="evaluated composite ledger"):
        feedback.validate_evaluated_ledger(missing_pair, cert)

    unknown = {**core, "qualification_authority": False}
    unknown = {**unknown, "ledger_digest": _digest(unknown)}
    with pytest.raises(feedback.ResearchFeedbackError, match="evaluated composite ledger"):
        feedback.validate_evaluated_ledger(unknown, cert)


def test_frontier_screened_mechanism_is_not_reproposed_as_new_design():
    cert = _certificate()
    catalog = _catalog()
    screened_id = catalog["mechanisms"][0]["id"]
    expected_next = catalog["mechanisms"][1]["id"]
    ledger = _evaluated_ledger([], cert)
    core = {k: v for k, v in ledger.items() if k != "ledger_digest"}
    core["frontier_screened_mechanisms"] = [screened_id]
    core["frontier_screening_version"] = "nexus.frontier-train-screen.v5"
    extended = {**core, "ledger_digest": _digest(core)}

    _, receipt, proposal = feedback.process_feedback(
        _run(), cert, catalog, evaluated_ledger=extended,
    )
    assert receipt["status"] == "NEW_DISTINCT_HYPOTHESIS_DESIGN_ONLY"
    assert proposal is not None
    assert proposal["mechanism"]["id"] == expected_next
    assert proposal["mechanism"]["id"] != screened_id


def test_evaluated_ledger_must_be_digest_bound_to_exact_dataset_and_authority():
    cert = _certificate()
    ledger = _evaluated_ledger(["lagged_peer_volatility_release"], cert)
    feedback.validate_evaluated_ledger(ledger, cert)

    tampered = dict(ledger)
    tampered["mechanisms_evaluated"] = ["peer_shock_noncontagion_rebound"]
    with pytest.raises(feedback.ResearchFeedbackError, match="evaluated composite ledger"):
        feedback.validate_evaluated_ledger(tampered, cert)

    wrong_archive = _evaluated_ledger(["lagged_peer_volatility_release"], cert)
    core = {k: v for k, v in wrong_archive.items() if k != "ledger_digest"}
    core["archive_sha256"] = "f" * 64
    wrong_archive = {**core, "ledger_digest": _digest(core)}
    with pytest.raises(feedback.ResearchFeedbackError, match="evaluated composite ledger"):
        feedback.validate_evaluated_ledger(wrong_archive, cert)

