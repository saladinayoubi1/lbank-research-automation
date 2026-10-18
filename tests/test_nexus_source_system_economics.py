"""Source-stop counterexamples and independent economic QA fault injection."""
from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest

from research import strategy_finder_shared_cash_physical as engine
from scripts import nexus_source_system_economic_execution as qa


def physical(n=110):
    frames = {}
    for s in engine.SYMBOLS:
        f = pd.DataFrame({"decision_at":pd.date_range("2025-01-01T00:15:00Z",periods=n,freq="15min"),
                          "open":100.,"high":101.,"low":99.,"close":100.,"atr":2.,
                          "h4_range":0.,"h1_vol_ok":1.,"lagged_peer_beta_residual":.02,
                          "lagged_downside_variance_share_64":.7,"prior_day_low":99.8,
                          "close_location":.8,"rel_vol":1.25},index=range(n))
        frames[s] = f
    frames["BTCUSDT"].loc[4,["open","low","h4_range"]] = [99.5,98.,1.]
    return frames


def run(f, end=110, cost="conservative"):
    signals = {s:qa.reference_signal(v) for s,v in f.items()}
    return engine.replay_shared_cash(f,signals,0,end,cost,stop_policy="signal_bar_low_v1")


def test_source_stop_uses_signal_low_and_does_not_depend_on_range_proxy():
    f = physical()
    f["BTCUSDT"].loc[4,"atr"] = np.nan
    got = run(f)
    assert got["trades"] == 1 and got["ledger"][0]["stop"] == 98.
    assert got["ledger"][0]["target"] == pytest.approx(104.15)
    f["BTCUSDT"].loc[4,"atr"] = 9000.
    assert run(f) == got


@pytest.mark.parametrize("opening",[98.,97.5])
def test_open_at_or_below_source_invalidation_is_denied_before_spread(opening):
    f = physical()
    f["BTCUSDT"].loc[5,["open","low","close"]] = [opening,97.,opening]
    got = run(f)
    assert got["trades"] == 0
    assert got["denial_reasons"] == {"NEXT_OPEN_AT_OR_BELOW_SIGNAL_LOW":1}
    qa.verify_partition(got,qa.reference_partition(f,0,110,"conservative"))


def test_later_gap_retains_loss_larger_than_nominal_budget():
    f = physical()
    f["BTCUSDT"].loc[7,["open","high","low","close"]] = [80.,81.,79.,80.]
    got = run(f)
    assert got["ledger"][0]["exit_reason"] == "STOP_GAP_AT_WORSE_OPEN"
    assert got["ledger"][0]["pnl_usdt"] < -2.5
    bar_close_ms = int(pd.Timestamp(f["BTCUSDT"].decision_at.iloc[7]).value//1_000_000)
    assert got["ledger"][0]["exit_bar_close_ms"] == bar_close_ms
    assert got["ledger"][0]["exit_event_ms"] == bar_close_ms-900000
    qa.verify_partition(got,qa.reference_partition(f,0,110,"conservative"))


def test_source_stop_and_target_same_bar_use_worse_stop():
    f = physical()
    f["BTCUSDT"].loc[5,["high","low"]] = [110.,97.]
    got = run(f)
    assert got["ledger"][0]["exit_reason"] == "STOP_FIRST_INTRABAR_BOTH"
    qa.verify_partition(got,qa.reference_partition(f,0,110,"conservative"))


@pytest.mark.parametrize("cost",["conservative","stress"])
def test_independent_cash_reference_checks_collisions_denials_timeout_and_costs(cost):
    f = physical()
    for s in f:
        f[s].loc[[4,5,10],["open","low","h4_range"]] = [99.5,98.,1.]
    f["BTCUSDT"].loc[4,"low"] = 97.
    got = run(f,cost=cost)
    assert got["denial_reasons"]["SAME_OPEN_LOWER_PRIORITY_PEER"] == 1
    assert got["denial_reasons"]["SHARED_CASH_POSITION_OCCUPIED"] == 4
    assert got["ledger"][0]["exit_reason"] == "TIMEOUT_AT_PHYSICAL_NEXT_OPEN"
    assert got["gross_price_pnl_usdt"]-got["total_friction_usdt"] == pytest.approx(got["net_pnl_usdt"],abs=1e-7)
    qa.verify_partition(got,qa.reference_partition(f,0,110,cost))


@pytest.mark.parametrize("field",["pnl_usdt","entry_fill","exit_fill","stop","target",
                                  "entry_open_ms","exit_event_ms","entry_fee_usdt","total_friction_usdt"])
def test_independent_qa_rejects_mutated_trade_even_when_summary_unchanged(field):
    f = physical()
    got = run(f)
    got["ledger"][0][field] += 1
    with pytest.raises(qa.EconomicTaskError):
        qa.verify_partition(got,qa.reference_partition(f,0,110,"conservative"))


def test_independent_qa_rejects_missing_trade_wrong_average_and_monthly_drift():
    f = physical()
    good = run(f)
    mutations = [deepcopy(good) for _ in range(3)]
    mutations[0]["ledger"] = []
    mutations[1]["mean_pnl_usdt"] += 1
    mutations[2]["monthly"][0]["net_pnl_usdt"] += 1
    for bad in mutations:
        with pytest.raises(qa.EconomicTaskError):
            qa.verify_partition(bad,qa.reference_partition(f,0,110,"conservative"))


def test_zero_activity_does_not_establish_economic_loss_or_minimum_count_gate():
    f = physical()
    f["BTCUSDT"]["h4_range"] = 0.
    got = run(f)
    assert got["trades"] == 0 and got["net_pnl_usdt"] == 0
    assert engine.execution_contract("signal_bar_low_v1")["minimum_trade_count"] is None
    qa.verify_partition(got,qa.reference_partition(f,0,110,"conservative"))
    assert qa.economic_disposition([{"trades":0,"net_pnl_usdt":0}]) == "NO_EXECUTION_EVIDENCE"
    assert qa.economic_disposition([{"trades":0,"net_pnl_usdt":0},
                                    {"trades":1,"net_pnl_usdt":2}]).startswith("MIXED_ACTIVITY")
    assert qa.economic_disposition([{"trades":1,"net_pnl_usdt":-1}]).startswith("HISTORICAL_NEGATIVE")
    assert qa.economic_disposition([{"trades":1,"net_pnl_usdt":1}]).startswith("HISTORICAL_POSITIVE")


def test_only_two_complete_implemented_contracts_are_accepted_without_changing_old_default():
    assert "stop_policy" not in engine.execution_contract()
    assert engine.execution_contract()["stop_range_multiple"] == 1.5
    with pytest.raises(engine.SharedCashDiagnosticError):
        engine.execution_contract("unreviewed_wider_stop")
    bad = engine.execution_contract("signal_bar_low_v1")
    bad["target_r"] = 3.
    with pytest.raises(engine.SharedCashDiagnosticError):
        engine.reviewed_stop_policy(bad)


def test_source_equations_are_not_the_legacy_failed_rolling_range_equations():
    # New source-level reclaim can occur without crossing the old rolling low.
    from nexus_composite_strategy_research import signal_for
    f = physical()["BTCUSDT"]
    f["prior_lo"],f["prior_hi"],f["h4_up"],f["h1_compression"] = 97.,105.,0.,0.
    assert qa.reference_signal(f)[4]
    assert not signal_for(f,{"mechanism":"failed_range_break_reversal","risk_variant":0})[4]
    # Conversely, legacy logic can fire while the lagged peer gate vetoes ours.
    f.loc[4,"prior_lo"] = 99.
    f.loc[4,"lagged_peer_beta_residual"] = -.02
    assert signal_for(f,{"mechanism":"failed_range_break_reversal","risk_variant":0})[4]
    assert not qa.reference_signal(f)[4]


def test_independent_equations_match_frozen_dsl_and_reject_nonfinite_conditions():
    from nexus_mechanism_factory import factory_signal,load_factory_contract
    from pathlib import Path
    path = Path(qa.ROOT)/"research/intake_candidates/factory_prior_day_sweep_peer_resilience_v1.json"
    specs = load_factory_contract(path)
    ident = next(iter(specs))
    for field in ("lagged_peer_beta_residual","close_location","rel_vol","prior_day_low"):
        for value in (np.nan,np.inf,-np.inf):
            f = physical()["BTCUSDT"]
            f.loc[4,field] = value
            assert not qa.reference_signal(f)[4]
            assert np.array_equal(qa.reference_signal(f),factory_signal(
                f,ident,specs=specs,expected_contract_digest=specs[ident]["contract_digest"]))


def test_passive_benchmark_charges_costs_inside_single_500_cash_budget():
    f = physical()
    a,b = qa.benchmark(f,0,110,"conservative"),qa.benchmark(f,0,110,"stress")
    assert b["equal_budget_buy_hold_net_pnl_usdt"] < a["equal_budget_buy_hold_net_pnl_usdt"] < 0
    assert a["cash_only_net_pnl_usdt"] == 0
    for source in f.values():
        source.loc[0,["open","low"]] = [10.,9.]
    assert qa.benchmark(f,0,110,"conservative") == a


def test_finished_native_result_is_reused_without_market_replay(tmp_path,monkeypatch):
    import io,zipfile
    task_id = "SYSTEM-ECON-"+"a"*24
    row = {"complete_system":{"system_digest":"b"*64}}
    result = {"economic_task":{"task_id":task_id,"producer":"research-agent","lane":"github-cloud",
                               "source_sha":"c"*40,"workflow_run_id":"123"},
              "complete_system_digest":"b"*64,"readiness":row,
              "paper_eligible":False,"live_enabled":False,"real_exchange_orders":0}
    result["result_digest"] = qa.digest(result)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw,"w") as z:
        z.writestr("research.json",json.dumps(result))
    monkeypatch.setattr(qa,"ROOT",tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY",qa.REPOSITORY)
    monkeypatch.setenv("GITHUB_RUN_ID","999")
    monkeypatch.setenv("GH_TOKEN","synthetic-test-token")
    monkeypatch.setattr(qa,"load_task",lambda:({},row,task_id))
    def api(url):
        if "/actions/runs/" in url:
            return {"head_branch":"main","event":"push","head_sha":"c"*40,
                    "path":".github/workflows/nexus_multitimeframe_strategy_discovery.yml"}
        return {"artifacts":[{"id":1,"name":"nexus-source-system-economic-"+task_id,
                              "created_at":"2026-10-18T00:00:00Z","workflow_run":{"id":123}}]}
    monkeypatch.setattr(qa,"_api_json",api)
    monkeypatch.setattr(qa._ARTIFACT_OPENER,"open",lambda *a,**k:io.BytesIO(raw.getvalue()))
    def forbidden(*args,**kwargs):
        raise AssertionError("reused finished result tried to replay a market")
    monkeypatch.setattr(qa.intake,"evaluate_approved",forbidden)
    assert qa.restore_result(tmp_path/"out.json",task_id)
    assert json.loads((tmp_path/"out.json").read_text()) == result
    changed = deepcopy(result)
    changed["real_exchange_orders"] = 1
    changed["result_digest"] = qa.digest({k:v for k,v in changed.items() if k!="result_digest"})
    with pytest.raises(qa.EconomicTaskError):
        qa.check_result(changed,{},row,task_id)


def test_started_task_without_finished_evidence_stops_instead_of_replaying(tmp_path,monkeypatch):
    task_id = "SYSTEM-ECON-"+"d"*24
    monkeypatch.setattr(qa,"ROOT",tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY",qa.REPOSITORY)
    def api(url):
        if "economic-started-" in url:
            return {"artifacts":[{"id":1,"name":"nexus-source-system-economic-started-"+task_id,
                                  "workflow_run":{"id":123}}]}
        if "/actions/runs/" in url:
            return {"head_branch":"main","event":"push",
                    "path":".github/workflows/nexus_multitimeframe_strategy_discovery.yml"}
        return {"artifacts":[]}
    monkeypatch.setattr(qa,"_api_json",api)
    with pytest.raises(qa.EconomicTaskError,match="do not replay automatically"):
        qa.restore_result(tmp_path/"out.json",task_id)
    assert not (tmp_path/"out.json").exists()


def test_actual_committed_source_request_only_approves_one_frozen_research_system():
    req,row,task_id = qa.load_task()
    assert task_id.startswith("SYSTEM-ECON-")
    assert row["status"] == "APPROVED_FOR_RESEARCH_SIMULATION_ONLY"
    assert row["complete_system"]["source_interpretation_independently_attested_here"] is False
    assert row["complete_system"]["study_window"]["start_utc"] == "2025-01-01T00:00:00Z"
    assert row["review_pr_url"].endswith("/2733")
    assert row["paper_eligible"] is False and row["live_enabled"] is False
    assert req["automatic_strategy_promotion"] is False
    assert set(req["support_source_sha256"]) == set(qa.SUPPORT)


def test_changed_worker_pin_blocks_before_any_market_access(tmp_path,monkeypatch):
    from pathlib import Path
    req = json.loads((qa.ROOT/qa.REQUEST).read_text())
    req["worker_source_sha256"] = "0"*64
    dest = tmp_path/qa.REQUEST
    dest.parent.mkdir(parents=True)
    dest.write_text(json.dumps(req))
    def forbidden(*args,**kwargs):
        raise AssertionError("unfrozen task touched physical market inputs")
    monkeypatch.setattr(qa.intake,"evaluate_approved",forbidden)
    with pytest.raises(qa.EconomicTaskError,match="worker changed"):
        qa.load_task(tmp_path)
