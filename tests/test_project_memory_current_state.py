import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "docs/project_memory/STATE.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


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
    assert policy["approved_public_bybit_mainnet_hosts"] == [
        "api.bybit.eu",
        "api.bybit.com",
        "api.bytick.com",
    ]
    assert policy["physical_eea_endpoint_order"] == policy["approved_public_bybit_mainnet_hosts"]
    assert policy["proxy_vpn_geographic_circumvention_allowed"] is False
    assert policy["testnet_substitution_allowed"] is False
    assert policy["synthetic_market_data_substitution_allowed"] is False
    assert policy["cross_exchange_substitution_for_acceptance_allowed"] is False


def test_project_memory_current_paper_acceptance_is_fail_closed_and_provenance_bound() -> None:
    state = _state()
    evidence = state["current_evidence"]
    paper = evidence["paper_runtime_acceptance"]

    assert SHA_RE.fullmatch(evidence["observed_main_sha"])
    assert paper["issue"] == 1041
    assert paper["issue_state"] == "open"
    assert paper["status"] == "POST_BOUNDARY_BLOCKED_SELF_HOSTED_EXECUTION_PLANE_UNCLAIMED"
    assert paper["genuine_hour4_boundary_reached"] is True
    assert paper["fresh_cell_count"] == 5
    assert paper["fresh_cell_count"] < paper["expected_cell_count"] == 6
    assert paper["remaining_cell"] == "ETHUSDT:hour4"
    assert SHA_RE.fullmatch(paper["remaining_cell_source_sha"])
    assert paper["remaining_cell_source_sha"] != evidence["observed_main_sha"]
    assert paper["source_bound_lane_count"] == 15
    assert paper["expected_lane_count"] == 18
    assert paper["trading_engine_complete"] is False
    assert paper["latest_physical_run_source_sha"] == evidence["observed_main_sha"]
    assert SHA256_RE.fullmatch(paper["latest_physical_state_artifact_digest"])
    assert paper["post_boundary_scheduled_run_conclusion"] == "cancelled"
    assert paper["post_boundary_scheduled_paper_job_claimed"] is False
    assert paper["post_boundary_bounded_retry_job_status"] == "queued"
    assert paper["post_boundary_bounded_retry_job_steps_observed"] == 0
    assert paper["post_boundary_state_artifact_proven"] is False
    assert paper["remaining_gap_classification"] == "self_hosted_execution_plane_unavailable_after_genuine_hour4_boundary"
    assert paper["paper_only"] is True
    assert paper["live_trading_authority"] is False
    assert paper["private_credentials_used"] is False
    assert paper["automatic_strategy_promotion"] is False
    assert paper["deterministic_risk_final_authority"] is True


def test_project_memory_current_windows_recovery_is_fail_closed_without_authority_expansion() -> None:
    state = _state()
    evidence = state["current_evidence"]
    recovery = evidence["windows_recovery"]
    runtime = state["runtime_status"]

    assert recovery["status"] == "SELF_HOSTED_CONTROL_PLANE_UNAVAILABLE_POST_BOUNDARY"
    assert recovery["windows_dr_persistence_decision"] == "BLOCKED_USER_CONTEXT_REQUIRED"
    assert recovery["bybit_wsl_wake_decision"] == "BLOCKED_SCHEDULED_TASKS_DISABLED"
    assert recovery["post_boundary_wake_retry_job_status"] == "completed"
    assert recovery["post_boundary_wake_retry_job_conclusion"] == "cancelled"
    assert recovery["post_boundary_wake_retry_job_steps_observed"] == 0
    assert recovery["current_control_plane_liveness_proven"] is False
    assert recovery["bybit_wsl_runner_subsequently_proven_operational"] is True
    assert recovery["privilege_acl_service_account_change_authorized"] is False
    assert recovery["runner_reregistration_authorized"] is False
    assert recovery["task_mutation_performed_by_wake_workflow"] is False
    assert runtime["current_self_hosted_listener_liveness_proven"] is False
    assert runtime["windows_runner_identity_class"] == "NETWORK_SERVICE"
    assert runtime["windows_user_context_token_available"] is False
    assert runtime["windows_user_context_token_error"] == 1314
    assert runtime["windows_dr_persistence_requires_interactive_signed_in_user"] is True
    assert runtime["bybit_wsl_wake_scheduled_tasks_enabled"] is False
    assert runtime["post_boundary_paper_job_queued_without_steps"] is True
    assert runtime["post_boundary_windows_wake_job_queued_without_steps"] is False
    assert runtime["post_boundary_windows_wake_job_cancelled_without_steps"] is True
    assert runtime["runner_registration_modified_by_recovery_work"] is False
    assert runtime["security_authority_expanded_by_recovery_work"] is False


def test_project_memory_keeps_runtime_real_time_and_production_gates_fail_closed() -> None:
    state = _state()
    prospective = state["current_evidence"]["prospective_paper_gate"]
    gates = state["open_gates"]

    assert gates["paper_runtime_acceptance"]["issue"] == 1041
    assert gates["paper_runtime_acceptance"]["state"] == "open"
    assert prospective["issue"] == 984
    assert prospective["status"] == "COLLECTING"
    assert prospective["verified_completed_hour4_bars"] < prospective["required_completed_hour4_bars"]
    assert prospective["latest_verified_workflow_run"] == 33452499286
    assert prospective["latest_verified_source_sha"] == state["current_evidence"]["observed_main_sha"]
    assert prospective["latest_verified_artifact_id"] == 9780274451
    assert SHA256_RE.fullmatch(prospective["latest_verified_artifact_digest"])
    assert prospective["may_be_accelerated_or_fabricated"] is False
    assert gates["prospective_paper"]["state"] == "open"
    assert gates["production_release"]["issue"] == 43
    assert gates["production_release"]["state"] == "open"
    assert gates["production_release"]["deny_by_default"] is True
    assert gates["windows_user_context_recovery"]["state"] == "supporting_blocker_not_primary_delivery_gate"


def test_project_memory_compaction_retains_prior_state_by_git_identity() -> None:
    state = _state()
    compaction = state["history_compaction"]

    assert compaction["compacted"] is True
    assert SHA_RE.fullmatch(compaction["prior_state_blob_sha"])
    assert SHA_RE.fullmatch(compaction["prior_state_observed_main_sha"])
    assert compaction["historical_detail_preserved_via_git_history"] is True
    assert compaction["do_not_treat_compaction_as_authority_expansion"] is True
