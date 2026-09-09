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


def test_project_memory_windows_persistence_is_historical_and_probe_remains_bounded() -> None:
    state = _state()
    evidence = state["current_evidence"]
    probe = evidence["windows_recovery_probe"]
    persistence = evidence["windows_dr_persistence"]

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

    assert persistence["status"] == "SUCCESS_HISTORICAL_FIXED_SHA_PHYSICAL"
    assert persistence["evidence_scope"] == "historical_fixed_sha"
    assert SHA_RE.fullmatch(persistence["source_sha"])
    assert persistence["source_sha"] != evidence["observed_main_sha"]
    assert persistence["runner"] == "NEXUS-WINDOWS-DR"
    assert persistence["persistence_install_decision"] == "SUCCESS"
    assert persistence["exact_source_fetch_verified"] is True
    assert persistence["runner_registration_modified"] is False
    assert persistence["runner_credentials_modified"] is False
    assert persistence["other_runner_paths_modified"] is False
    assert persistence["live_trading_authority"] is False


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
    assert latest_paper["source_sha"] == state["current_evidence"]["observed_main_sha"]
    assert latest_paper["workflow_run"] == 34397395277
    assert latest_paper["workflow_conclusion"] == "success"
    assert latest_paper["fresh_cell_count"] == 8
    assert latest_paper["expected_cell_count"] == 12
    assert latest_paper["engine_verification_decision"] == "pass"
    assert latest_paper["independent_workflow_verification_decision"] == "pass"
    assert latest_paper["verification_valid_waiting_state_persisted"] is True
    assert latest_paper["unverified_partial_state_persisted"] is False
    assert latest_paper["endpoint_http403_root_cause_of_eight_of_twelve"] is False
    assert latest_paper["regime_selected_rebalance_operational"] is False
    assert latest_paper["regime_selected_exposure_increase_operational"] is False
    assert latest_paper["performance_health_feedback_operational"] is False
    assert latest_paper["strategy_discovery_health_trigger_requested"] is False
    assert latest_paper["issue_984_state_touched"] is False
    assert gates["windows_user_context_recovery"]["state"] == "historical_context_limit_not_current_persistence_blocker"


def test_project_memory_compaction_retains_prior_state_by_git_identity() -> None:
    state = _state()
    compaction = state["history_compaction"]

    assert compaction["compacted"] is True
    assert SHA_RE.fullmatch(compaction["prior_state_blob_sha"])
    assert SHA_RE.fullmatch(compaction["prior_state_observed_main_sha"])
    assert compaction["historical_detail_preserved_via_git_history"] is True
    assert compaction["do_not_treat_compaction_as_authority_expansion"] is True
