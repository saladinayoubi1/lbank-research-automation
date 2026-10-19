"""Shared-book collisions, independent arithmetic and consumed VAL-40 gates."""
import ast
from copy import deepcopy
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

import nexus_composite_shared_cash as shared
import nexus_shared_cash_reference as reference
import nexus_composite_runtime_requalification as rq
from nexus_composite_signal_trace import capture_signals
from nexus_composite_strategy_research import backtest
from research import strategy_finder_shared_cash_physical as engine

SOURCE = "a"*40
CANDIDATE = {"candidate_digest":"b"*64,"mechanism":"structural_pullback",
             "strategy_config":{"mechanism":"structural_pullback","risk_variant":0}}


def fixture(n=400, mode="target"):
    frames, masks, rows = {}, {}, []
    times = pd.date_range("2026-01-01",periods=n,freq="15min",tz="UTC")
    bounds = (0,int(n*.6),int(n*.8),n)
    for symbol in reference.SYMBOLS:
        f = pd.DataFrame(dict(decision_at=times,open=100.,high=100.1,low=99.9,close=100.,atr=1.))
        mask = np.zeros(n,dtype=bool)
        for start,end in zip(bounds,bounds[1:]):
            mask[start] = True
            if mode == "target":
                f.loc[start+1,"high"] = 110.
            elif mode == "both":
                f.loc[start+1,["high","low"]] = [110.,95.]
            elif mode == "timeout_gap":
                f.loc[start+64,["high","close"]] = [101.2,101.]
                f.loc[start+65,["open","high","low","close"]] = [97.,97.1,96.9,97.]
        if mode == "zero": mask[:] = False
        data = {"minute15":{"timeframe":"minute15","binding_sha256":("c" if symbol=="BTCUSDT" else "d")*64,
                             "row_count":n,"first_open_time_ms":int(times[0].value//10**6)-reference.STEP,
                             "last_open_time_ms":int(times[-1].value//10**6)-reference.STEP}}
        cap = capture_signals(f,mask,candidate=CANDIDATE,source_sha=SOURCE,symbol=symbol,datasets=data,peer_binding=None)
        rows.append(dict(symbol=symbol,datasets=data,emitted_signal_trace={"capture":cap}))
        frames[symbol], masks[symbol] = f, mask
    return frames,masks,rows


def build(mode="target"):
    frames,masks,rows = fixture(mode=mode)
    return shared.build_shared_cash(frames,masks,candidate=CANDIDATE,source_sha=SOURCE,evaluations=rows),rows


def verify(value,rows):
    shared.verify_shared_cash(value,candidate=CANDIDATE,source_sha=SOURCE,evaluations=rows)


def resign(value):
    value["portfolio_digest"] = shared.digest({k:v for k,v in value.items() if k != "portfolio_digest"})


def test_existing_engine_is_consumed_once_and_independent_reference_does_not_call_it(monkeypatch):
    original, calls = engine.sidecar_summary, []
    def observed(*a,**kw):
        calls.append(True)
        return original(*a,**kw)
    monkeypatch.setattr(engine,"sidecar_summary",observed)
    proof,rows = build()
    assert calls == [True]
    monkeypatch.setattr(engine,"sidecar_summary",lambda *a,**kw:pytest.fail("reference called production"))
    verify(proof,rows)
    assert proof["diagnostic_state"] == "NUMERICALLY_POSITIVE_RESEARCH_DIAGNOSTIC_ONLY"
    for profiles in proof["cells"].values():
        for cell in profiles.values():
            assert cell["trades"] == 1
            assert cell["denial_reasons"] == {"SAME_OPEN_LOWER_PRIORITY_PEER":1}
            assert cell["ledger_rows"][0][0] == "BTCUSDT"
    assert proof["owner_shared_500_portfolio_verified"] is False


def test_positive_two_10000_books_do_not_hide_negative_shared_500_timeout_gap():
    frames,masks,rows = fixture(mode="timeout_gap")
    for s in reference.SYMBOLS:
        for fee,slip in reference.PROFILES.values():
            assert backtest(frames[s],masks[s],fee_bps=fee,slip_bps=slip,risk_variant=0)["net_pnl_usdt"] > 0
    proof = shared.build_shared_cash(frames,masks,candidate=CANDIDATE,source_sha=SOURCE,evaluations=rows)
    assert proof["diagnostic_state"] == "NEGATIVE_SHARED_CASH_CELL"
    assert rq._review_decision(12,False,True,proof) == ("REJECTED",["NEGATIVE_SHARED_500_CASH_CELL"])
    for profiles in proof["cells"].values():
        for cell in profiles.values():
            assert cell["exit_reasons"] == {"STOP_GAP_AT_WORSE_OPEN":1}
            assert cell["ledger_rows"][0][15] == "open_execution_recorded_at_legacy_bar_close"


def test_no_execution_is_inconclusive_and_no_minimum_count_is_introduced():
    proof,rows = build("zero")
    verify(proof,rows)
    assert rq._review_decision(0,False,False,proof) == ("INCONCLUSIVE",["INCONCLUSIVE_NO_SHARED_CASH_EXECUTION"])
    proof,_ = build()
    assert rq._review_decision(1,False,True,proof)[0] == "QUALIFIED_FOR_REVIEW"
    assert proof["execution_contract"]["minimum_trade_count"] is None


@pytest.mark.parametrize("mode",["both","flat","timeout_gap"])
def test_exit_order_terminal_liquidation_costs_and_full_ledgers_are_independently_recomputed(mode):
    proof,rows = build(mode)
    verify(proof,rows)
    for part in proof["cells"].values():
        for cell in part.values():
            assert abs(cell["ending_shared_cash_usdt"]-500-cell["net_pnl_usdt"]) < 1e-6
            assert abs(cell["gross_price_pnl_usdt"]-cell["total_friction_usdt"]-cell["net_pnl_usdt"]) < 1e-6


@pytest.mark.parametrize("mutation",["net","quantity","fee","event","missing_trade","input","source",
                                     "capture","cost","contract","authority","decision","missing_partition"])
def test_resigned_tampering_fails_independent_reconstruction(mutation):
    proof,rows = build()
    cell = proof["cells"]["training"]["conservative"]
    if mutation == "net": cell["net_pnl_usdt"] += 1
    elif mutation == "quantity": cell["ledger_rows"][0][5] *= 2
    elif mutation == "fee": cell["ledger_rows"][0][10] = 0
    elif mutation == "event": cell["ledger_rows"][0][-1] = "e"*64
    elif mutation == "missing_trade": cell["ledger_rows"].pop()
    elif mutation == "input": proof["physical_inputs"]["BTCUSDT"][1][1] = 100.1
    elif mutation == "source": proof["identity"]["source_sha"] = "e"*40
    elif mutation == "capture": proof["identity"]["signal_capture_digests"]["ETHUSDT"] = "e"*64
    elif mutation == "cost": proof["cells"]["training"].pop("stress")
    elif mutation == "contract": proof["execution_contract"]["initial_shared_cash_usdt"] = 10000
    elif mutation == "authority": proof["paper_execution_authority"] = True
    elif mutation == "decision": proof["diagnostic_state"] = "NEGATIVE_SHARED_CASH_CELL"
    elif mutation == "missing_partition": proof["cells"].pop("historical_test_already_inspected")
    resign(proof)
    with pytest.raises(reference.SharedCashReferenceError): verify(proof,rows)


def test_occupied_at_open_denies_peer_even_when_position_exits_that_bar():
    frames,masks,rows = fixture(mode="flat")
    for s in reference.SYMBOLS:
        masks[s][1] = True
        frames[s].loc[2,"high"] = 110.
        rows[reference.SYMBOLS.index(s)]["emitted_signal_trace"]["capture"] = capture_signals(
            frames[s],masks[s],candidate=CANDIDATE,source_sha=SOURCE,symbol=s,datasets=rows[reference.SYMBOLS.index(s)]["datasets"],peer_binding=None)
    proof = shared.build_shared_cash(frames,masks,candidate=CANDIDATE,source_sha=SOURCE,evaluations=rows)
    assert proof["cells"]["training"]["stress"]["denial_reasons"]["SHARED_CASH_POSITION_OCCUPIED"] == 2


def test_unsupported_risk_fails_before_any_data_access(tmp_path):
    candidate = deepcopy(CANDIDATE)
    candidate["strategy_config"]["risk_variant"] = 1
    with pytest.raises(rq.CompositeRuntimeRequalificationError,match="before fetching"):
        rq._default_evaluator(candidate,SOURCE,1,tmp_path)


def test_reference_and_verifier_remain_stdlib_only():
    for module in (reference,shared):
        syntax = ast.parse(Path(module.__file__).read_text())
        imports = [n.module for n in syntax.body if isinstance(n,ast.ImportFrom)]
        imports += [a.name for n in syntax.body if isinstance(n,ast.Import) for a in n.names]
        assert all(not n.startswith(("numpy","pandas","research","nexus_composite_strategy")) for n in imports)


@pytest.mark.parametrize("prior",[None,0.,-1.,100.])
def test_unavailable_or_invalid_btc_range_falls_back_to_eth_without_tuning(prior):
    frames,masks,rows = fixture()
    for start in (0,240,320):
        frames["BTCUSDT"].loc[start,"atr"] = np.nan if prior is None else prior
    # Rebind the actual capture after modifying input features.
    for row in rows:
        s=row["symbol"]
        row["emitted_signal_trace"]["capture"] = capture_signals(frames[s],masks[s],candidate=CANDIDATE,
            source_sha=SOURCE,symbol=s,datasets=row["datasets"],peer_binding=None)
    proof=shared.build_shared_cash(frames,masks,candidate=CANDIDATE,source_sha=SOURCE,evaluations=rows)
    for profiles in proof["cells"].values():
        for cell in profiles.values():
            assert cell["ledger_rows"][0][0] == "ETHUSDT"
            assert cell["attempt_counts"]["next_open_intent"] == 2


def test_fee_aware_size_and_single_notional_cap_use_one_initial_balance():
    frames,masks,rows=fixture()
    for s in reference.SYMBOLS:
        frames[s]["atr"]=.01
        row=next(r for r in rows if r["symbol"]==s)
        row["emitted_signal_trace"]["capture"]=capture_signals(frames[s],masks[s],candidate=CANDIDATE,
            source_sha=SOURCE,symbol=s,datasets=row["datasets"],peer_binding=None)
    proof=shared.build_shared_cash(frames,masks,candidate=CANDIDATE,source_sha=SOURCE,evaluations=rows)
    for profiles in proof["cells"].values():
        for profile,cell in profiles.items():
            trade=dict(zip(reference.COLUMNS,cell["ledger_rows"][0][:-1]))
            fee,slip=(x/10000 for x in reference.PROFILES[profile])
            assert trade["qty"]*trade["entry_fill"] <= 250+1e-6
            risk=trade["qty"]*(trade["entry_fill"]*(1+fee)-trade["stop"]*(1-slip)*(1-fee))
            assert risk <= 2.5+1e-6
            assert trade["qty"]*trade["entry_fill"]+trade["entry_fee_usdt"] <= 500


@pytest.mark.parametrize("observed,expected",[(1e-8,-1e-8),(1e-8,0.),(0.,-1e-8)])
def test_numeric_tolerance_cannot_change_the_gate_sign(observed,expected):
    with pytest.raises(reference.SharedCashReferenceError,match="net sign"):
        reference.compare({"net_pnl_usdt":observed},{"net_pnl_usdt":expected})
