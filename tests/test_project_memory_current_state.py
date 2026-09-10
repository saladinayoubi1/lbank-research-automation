import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs/project_memory/STATE.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def test_project_memory_preserves_paper_only_authority() -> None:
    state = _state()
    authority = state["authority"]
    policy = state["data_policy"]

    assert authority["research"] is True
    assert authority["backtest"] is True
    assert authority["paper"] is True
    assert authority["live"] is False
    assert authority["l4"] is False
    assert authority["real_exchange_orders"] is False
    assert authority["private_exchange_credentials"] is False
    assert authority["automatic_strategy_promotion"] is False
    assert authority["production_signing"] is False
    assert authority["production_deployment"] is False
    assert authority["deterministic_risk_final_authority"] is True
    assert policy["real_trading"] is False
    assert policy["fabricated_market_data"] is False
    assert policy["approved_public_bybit_mainnet_hosts"] == ["api.bybit.com", "api.bytick.com"]
    assert policy["proxy_vpn_geographic_circumvention_allowed"] is False
    assert policy["testnet_substitution_allowed"] is False
    assert policy["synthetic_market_data_substitution_allowed"] is False
    assert policy["cross_exchange_substitution_for_acceptance_allowed"] is False


def test_project_memory_current_paper_acceptance_is_closed_and_provenance_bound() -> None:
    state = _state()
    evidence = state["current_evidence"]
    paper = evidence["paper_runtime_acceptance"]

    assert SHA_RE.fullmatch(evidence["observed_main_sha"])
    assert paper["issue"] == 1041
    assert paper["issue_state"] == "closed"
    assert paper["status"] == "ACCEPTED_6_OF_6_ENVIRONMENT_FAITHFUL"
    assert paper["accepted_cell_count"] == paper["expected_cell_count"] == 6
    assert paper["expected_lane_count"] == 18
    assert paper["restart_replay_proven"] is True
    assert paper["paper_runtime_acceptance_complete"] is True
    assert paper["trading_engine_complete_for_bounded_acceptance_scope"] is True
    assert SHA_RE.fullmatch(paper["acceptance_source_sha"])
    assert isinstance(paper["acceptance_workflow_run"], int) and paper["acceptance_workflow_run"] > 0
    assert paper["paper_only"] is True
    assert paper["live_trading_authority"] is False
    assert paper["private_credentials_used"] is False
    assert paper["automatic_strategy_promotion"] is False
    assert paper["deterministic_risk_final_authority"] is True


def test_project_memory_windows_persistence_is_current_and_probe_remains_bounded() -> None:
    state = _state()
    evidence = state["current_evidence"]
    probe = evidence["windows_recovery_probe"]
    persistence = evidence["windows_dr_persistence"]
    local = evidence["windows_local_autonomy"]
    gate = state["open_gates"]["windows_runner_routing_and_update"]

    assert probe["status"] == "CONTEXT_LIMITED_SECURITY_BOUNDARY_CONFIRMED_NOT_BLOCKING_CURRENT_WINDOWS_DR_PERSISTENCE"
    assert SHA_RE.fullmatch(probe["source_sha"])
    assert probe["runner_identity_class"] == "NETWORK_SERVICE"
    assert probe["interactive_console_session_present"] is True
    assert probe["wts_user_token_available"] is False
    assert probe["wts_user_token_error"] == 1314
    assert probe["scheduled_recovery_task_visible"] is False
    assert probe["scheduled_recovery_task_query_access_denied"] is True
    assert probe["bybit_watchdog_path_exists"] is True
    assert probe["privilege_acl_service_account_change_authorized"] is False
    assert probe["runner_reregistration_authorized"] is False

    assert persistence["status"] == "SUCCESS_EXACT_MAIN_PHYSICAL_CURRENT"
    assert persistence["evidence_scope"] == "exact_checkpoint_main"
    assert persistence["source_sha"] == evidence["observed_main_sha"]
    assert persistence["runner"] == "NEXUS-WINDOWS-DR"
    assert persistence["runner_version"] == "2.337.0"
    assert persistence["routing_label"] == "nexus-remote-rescue"
    assert persistence["run_id"] == 34482923984
    assert persistence["artifact_id"] == 10156147936
    assert persistence["persistence_install_decision"] == "SUCCESS"
    assert persistence["exact_source_fetch_verified"] is True
    assert persistence["runner_registration_modified"] is False
    assert persistence["runner_credentials_modified"] is False
    assert persistence["other_runner_paths_modified"] is False
    assert persistence["live_trading_authority"] is False

    assert local["status"] == "SUCCESS_EXACT_MAIN_PHYSICAL_CURRENT"
    assert local["evidence_scope"] == "exact_checkpoint_main"
    assert local["source_sha"] == evidence["observed_main_sha"]
    assert local["runner"] == "NEXUS-LOCAL-RUNNER"
    assert local["runner_version"] == "2.337.0"
    assert local["routing_label"] == "nexus-local"
    assert local["run_id"] == 34482924040
    assert local["artifact_id"] == 10157084959
    assert local["workflow_conclusion"] == "success"
    assert local["bounded_autonomous_queue_completed"] is True
    assert local["runner_registration_modified"] is False
    assert local["runner_credentials_modified"] is False
    assert local["live_trading_authority"] is False

    assert gate["state"] == "closed_exact_main_verified"
    assert gate["source_sha"] == evidence["observed_main_sha"]
    assert gate["dr_run"] == persistence["run_id"]
    assert gate["local_run"] == local["run_id"]


def test_project_memory_records_verified_boundary_discovery_without_promotion_authority() -> None:
    state = _state()
    discovery = state["current_evidence"]["strategy_discovery"]

    assert discovery["status"] == "EXACT_MAIN_PHYSICAL_MULTIPAIR_DISCOVERY_RUNTIME_REQUALIFICATION_AND_PROOF_VERIFIED"
    assert discovery["evidence_scope"] == "historical_exact_main_at_run"
    assert SHA_RE.fullmatch(discovery["source_sha"])
    assert discovery["source_sha"] != state["current_evidence"]["observed_main_sha"]
    assert discovery["workflow_run"] == 34392341610
    assert discovery["workflow_conclusion"] == "success"
    assert discovery["exact_source_restore_verified"] is True
    assert discovery["exact_source_reused_without_physical_git_fetch"] is True
    assert discovery["node_actions_executed_on_physical_runner"] is False
    assert discovery["research_proposal_count"] == 0
    assert discovery["issue_984_state_touched"] is False
    assert discovery["discovery_feedback_verified"] is True
    assert discovery["leakage_resistant_discovery_cells_executed"] == 9
    assert discovery["runtime_requalification_result"] == "NO_WORK"
    assert discovery["verified_feedback"] == "VERIFIED_NO_RESEARCH_PROPOSALS"
    assert discovery["output_authority"] == "RESEARCH_PROPOSAL_ONLY"
    assert discovery["automatic_candidate_or_paper_promotion"] is False
    assert discovery["live_trading_authority"] is False


def test_project_memory_keeps_real_time_and_production_gates_fail_closed() -> None:
    state = _state()
    prospective = state["current_evidence"]["prospective_paper_gate"]
    gates = state["open_gates"]

    assert gates["paper_runtime_acceptance"]["issue"] == 1041
    assert gates["paper_runtime_acceptance"]["state"] == "closed"
    assert prospective["issue"] == 984
    assert prospective["status"] == "COLLECTING"
    assert prospective["verified_completed_hour4_bars"] < prospective["required_completed_hour4_bars"]
    assert prospective["may_be_accelerated_or_fabricated"] is False
    assert gates["prospective_paper"]["state"] == "open"
    assert gates["production_release"]["issue"] == 43
    assert gates["production_release"]["state"] == "open"
    assert gates["production_release"]["deny_by_default"] is True
    assert gates["strategy_discovery_runtime_snapshot"]["state"] == "closed_completed"
    assert gates["persistent_paper_freshness"]["state"] == "closed_contract_reconciled"
    latest_paper = state["current_evidence"]["persistent_paper_runtime_latest"]
    assert latest_paper["status"] == "VERIFIED_WAITING_FOR_FRESH_CELLS_PERSISTED"
    assert SHA_RE.fullmatch(latest_paper["source_sha"])
    assert latest_paper["source_sha"] == gates["persistent_paper_freshness"]["source_sha"]
    assert latest_paper["source_sha"] != state["current_evidence"]["observed_main_sha"]
    assert latest_paper["workflow_run"] == 34413401197
    assert latest_paper["workflow_conclusion"] == "success"
    assert latest_paper["persisted_state_artifact_id"] == 10128322177
    assert latest_paper["fresh_cell_count"] == 4
    assert latest_paper["expected_cell_count"] == 12
    assert latest_paper["engine_verification_decision"] == "pass"
    assert latest_paper["independent_workflow_verification_decision"] == "pass"
    assert latest_paper["verification_valid_waiting_state_persisted"] is True
    assert latest_paper["unverified_partial_state_persisted"] is False
    assert latest_paper["endpoint_http403_root_cause_of_eight_of_twelve"] is False
    assert latest_paper["endpoint_http403_root_cause_of_latest_freshness_shortfall"] is False
    assert latest_paper["regime_selected_rebalance_operational"] is False
    assert latest_paper["regime_selected_exposure_increase_operational"] is False
    assert latest_paper["performance_health_feedback_operational"] is False
    assert latest_paper["strategy_discovery_health_trigger_requested"] is False
    assert latest_paper["issue_984_state_touched"] is False
    assert gates["windows_user_context_recovery"]["state"] == "historical_context_limit_not_current_persistence_blocker"


def test_project_memory_records_exact_main_strategy_factory_review_boundary() -> None:
    state = _state()
    evidence = state["current_evidence"]
    factory = evidence["strategy_factory_latest"]
    lifecycle = evidence["demo_regime_lifecycle_latest"]
    gate = state["open_gates"]["strategy_factory_candidate_review"]

    assert SHA_RE.fullmatch(evidence["observed_main_sha"])
    assert factory["status"] == "EXACT_MAIN_REPLAY_V2_ROTATION_AND_RESEARCH_RUNS_VERIFIED"
    assert factory["source_sha"] == "50ac6ea8a331c08dca3e8be184ed0717380ff7f6"
    assert factory["source_sha"] != evidence["observed_main_sha"]
    assert factory["controller_stage_count"] == 8
    assert factory["controller_ready_stage_count"] == 8
    assert factory["replay_semantic_dataset_sha256"] == "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"
    assert factory["regime_v6"]["qualifies_for_derivatives_validation_and_prospective_paper_forward"] is False
    assert factory["neighborhood_v7"]["qualifies_for_derivatives_validation_and_prospective_paper_forward"] is True
    assert factory["neighborhood_v7"]["automatic_paper_forward_started"] is False
    assert factory["qualification_authority"] is False
    assert factory["automatic_strategy_promotion"] is False
    assert factory["live_trading_authority"] is False
    assert factory["private_credentials_used"] is False
    assert factory["real_exchange_orders"] is False
    assert factory["deterministic_risk_final_authority"] is True
    assert factory["issue_984_state_touched"] is False

    assert lifecycle["source_sha"] == factory["source_sha"]
    assert lifecycle["verification_decision"] == "pass"
    assert lifecycle["deterministic_risk_final_authority"] is True
    assert lifecycle["automatic_strategy_promotion"] is False
    assert lifecycle["live_trading_authority"] is False

    assert gate["state"] == "human_review_required_no_automatic_forward"
    assert gate["workflow_run"] == factory["neighborhood_v7"]["workflow_run"]
    assert gate["artifact_id"] == factory["neighborhood_v7"]["artifact_id"]


def test_project_memory_records_repaired_exact_main_multipair_feedback_boundary() -> None:
    state = _state()
    evidence = state["current_evidence"]
    discovery = evidence["strategy_discovery_latest_runtime"]
    paper = evidence["persistent_paper_runtime_latest"]
    feedback = evidence["multipair_paper_boundary_feedback_latest"]
    gate = state["open_gates"]["multipair_paper_boundary_feedback_runtime"]
    source_sha = feedback["source_sha"]

    assert source_sha == "21af398b9e73896f98c792a99230cf1562f7a04b"
    assert source_sha != evidence["observed_main_sha"]
    assert paper["source_sha"] == discovery["source_sha"] == source_sha
    assert paper["workflow_run"] == feedback["paper_workflow_run"] == 34413401197
    assert discovery["physical_proof_workflow_run"] == feedback["discovery_workflow_run"] == 34413429714
    assert discovery["research_proposal_count"] == 0
    assert discovery["requalification_result"] == "NO_WORK"
    assert discovery["proof_artifact_id"] == feedback["discovery_proof_artifact_id"] == 10128592404
    assert feedback["workflow_run"] == 34414723066
    assert feedback["workflow_conclusion"] == "success"
    assert feedback["runtime_dependency_fix_pr"] == 1430
    assert feedback["runtime_dependency_install"] == "requirements.lock"
    assert feedback["runtime_dependency_check"] == "pass"
    assert feedback["exact_sha_pair_resolution"] == "pass"
    assert feedback["exact_run_artifact_binding"] == "pass"
    assert feedback["boundary_eligibility"] is False
    assert feedback["boundary_decision"] == "NO_OP_NOT_ELIGIBLE"
    assert feedback["feedback_artifact_created"] is False
    assert feedback["candidate_state_created"] is False
    assert feedback["paper_execution_started"] is False
    assert feedback["automatic_strategy_promotion"] is False
    assert feedback["live_trading_authority"] is False
    assert feedback["private_credentials_used"] is False
    assert feedback["real_exchange_orders"] is False
    assert feedback["deterministic_risk_final_authority"] is True
    assert feedback["issue_984_state_touched"] is False
    assert gate["state"] == "closed_dependency_provisioning_repaired"
    assert gate["workflow_run"] == feedback["workflow_run"]
    assert gate["source_sha"] == source_sha


def test_project_memory_compaction_retains_prior_state_by_git_identity() -> None:
    state = _state()
    compaction = state["history_compaction"]

    assert compaction["compacted"] is True
    assert SHA_RE.fullmatch(compaction["prior_state_blob_sha"])
    assert SHA_RE.fullmatch(compaction["prior_state_observed_main_sha"])
    assert compaction["historical_detail_preserved_via_git_history"] is True
    assert compaction["do_not_treat_compaction_as_authority_expansion"] is True
