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


def test_project_memory_same_sha_demo_evidence_is_internally_bound() -> None:
    state = _state()
    evidence = state["current_evidence"]
    demo = evidence["same_sha_demo_proof"]

    assert SHA_RE.fullmatch(evidence["observed_main_sha"])
    assert demo["status"] == "VERIFIED"
    assert demo["source_sha"] == evidence["observed_main_sha"]
    assert demo["verified_cell_count"] == demo["expected_cell_count"] == 6
    assert demo["expected_lane_count"] == 18
    assert demo["paper_only"] is True
    assert demo["live_trading_authority"] is False
    assert demo["private_credentials_used"] is False
    assert demo["automatic_strategy_promotion"] is False
    assert demo["deterministic_risk_final_authority"] is True
    assert demo["frozen_prospective_hour4_lane_mutated"] is False
    assert demo["paper_position_maintenance"]["exposure_increased"] is False


def test_project_memory_keeps_real_time_and_production_gates_fail_closed() -> None:
    state = _state()
    prospective = state["current_evidence"]["prospective_paper_gate"]
    gates = state["open_gates"]

    assert prospective["issue"] == 984
    assert prospective["status"] == "COLLECTING"
    assert prospective["verified_completed_hour4_bars"] < prospective["required_completed_hour4_bars"]
    assert prospective["may_be_accelerated_or_fabricated"] is False
    assert gates["prospective_paper"]["state"] == "open"
    assert gates["production_release"]["issue"] == 43
    assert gates["production_release"]["state"] == "open"
    assert gates["production_release"]["deny_by_default"] is True
    assert gates["physical_windows_final_proof"]["state"] == "required_before_installation_acceptance"


def test_project_memory_compaction_retains_prior_state_by_git_identity() -> None:
    state = _state()
    compaction = state["history_compaction"]

    assert compaction["compacted"] is True
    assert SHA_RE.fullmatch(compaction["prior_state_blob_sha"])
    assert SHA_RE.fullmatch(compaction["prior_state_observed_main_sha"])
    assert compaction["historical_detail_preserved_via_git_history"] is True
    assert compaction["do_not_treat_compaction_as_authority_expansion"] is True
