"""Standalone read-only QuantDinger statistics + MR40 diagnostics; no copied trading engine."""
from __future__ import annotations
import gzip, hashlib, importlib.util, json, math, sys
from datetime import datetime, timezone
from pathlib import Path

BASE=Path("E:/NEXUS-Research-Sandboxes/quantdinger-stdlib-20261023")
RESEARCH=Path("E:/NEXUS-Research")
PACKAGE=BASE/"backend_api_python/app/services/strategy_evolution"
OUT=Path("E:/NEXUS-Research-Sandboxes/quantdinger-stdlib-20261023/mr40_diagnostic_20261023.json")
def module(name):
    spec=importlib.util.spec_from_file_location("qd_"+name,PACKAGE/(name+".py"))
    lib=importlib.util.module_from_spec(spec)
    sys.modules["qd_"+name]=lib
    spec.loader.exec_module(lib)
    return lib
stats=module("statistics")
wf=module("walk_forward")
from research.nexus_mr40_one_combination_ablation_v1 import inputs
source=RESEARCH/"MR40-Staged-Entry-20261022/source/inputs"
ledger=RESEARCH/"MR40-Entry-Quality-20261022/results/ledger.jsonl.gz"
lock=RESEARCH/"MR40-Entry-Event-20261022/research/mr40_one_combination_ablation_protocol_20261022.json"
p,rows,ledger_refs=inputs(source,ledger,lock)
assert len(rows)==8514
times=[datetime.fromtimestamp(int(r[0])/1000,timezone.utc) for r in rows]
plan=wf.build_walk_forward_plan(times[0],times[-1],folds=3,train_ratio=.50,blind_ratio=.20,observations=times,warmup_bars=180,embargo_bars=1)
assert len(plan.folds)==3
for f in plan.folds:
    assert f.train_end<f.validation_start and f.embargo_bars==1
assert plan.blind_start and plan.folds[-1].validation_end<plan.blind_start
windows={}
for window in ("train","evaluation"):
    ref=ledger_refs[(window,500,"stress")]
    ret=[]
    for item in ref["positions"]:
        prior=float(item["entry"]["cash_before"])
        ret.append(float(item["net_pnl_usdt"])/prior)
    windows[window]=ret
ret=windows["train"]+windows["evaluation"]
assert len(windows["train"])==25 and len(windows["evaluation"])==22 and len(ret)==47
mc=stats.monte_carlo_bootstrap(ret,paths=400,block_size=3,seed=19)
mc_again=stats.monte_carlo_bootstrap(ret,paths=400,block_size=3,seed=19)
assert mc==mc_again and mc["available"]
sh=stats.sample_sharpe(ret)
dsr=stats.deflated_sharpe(ret,observed_sharpe=sh,trials=4)
pbo=stats.probability_of_backtest_overfitting([[1,2],[2,1]])
assert pbo["available"] is False and pbo["reason"] in ("insufficientCandidates", "insufficientFolds")
report={
    "schema":"nexus.mr40.quantdinger_standalone_diagnostics.v1",
    "external_repo_commit": "d7642d7",
    "external_code_paths":["backend_api_python/app/services/strategy_evolution/statistics.py","backend_api_python/app/services/strategy_evolution/walk_forward.py"],
    "execution":"actual QuantDinger stdlib modules, imported from isolated sparse GitHub checkout",
    "market":"Bybit BTCUSDT Spot, 4h",
    "original_rows":len(rows),
    "source_hash":p["inputs"]["ohlc_digest"],
    "ledger_sha256":p["inputs"]["existing_ledger_sha256"],
    "window_trade_counts":{"train":len(windows["train"]),"evaluation_seen":len(windows["evaluation"])},
    "wfo_timeline_only":{"requested_folds":3,"effective_folds":len(plan.folds),"blind_history_bars":plan.blind_bars,
        "first_train_end":plan.folds[0].train_end.isoformat(),"last_validation_end":plan.folds[-1].validation_end.isoformat(),
        "embargo_bars":plan.embargo_bars,"blind_start":plan.blind_start.isoformat(),
        "note":"These timestamps and entire 2023-2026 history are ALREADY SEEN; not unbiased blind verification."},
    "monte_carlo":{"source":"47 BASELINE historically seen position returns, STRESS fees/slippage; not new independent trials","paths":mc["paths"],"effective_block_size":mc["effectiveBlockSize"],"loss_probability":mc["lossProbability"],"drawdown_percentiles":mc["drawdownPercentiles"],"terminal_percentiles":mc["percentiles"],"deterministic_seed_check":True},
    "deflated_sharpe":{"on_47_trade_returns_not_daywise_returns":True,**dsr},
    "pbo_refusal":{"two_independent_time_windows_only":True,**pbo},
    "safety":{"live":False,"real_orders":0,"private_api":False,"paper_modified":False,"promote":False},
    "limitations":["47 previously-seen trades; bootstrap samples correlated episodes, no fresh external validity","DSR computed on per-trade returns not time-indexed daily strategy returns, not approved economic gate","WFO calendar plan not a new walk-forward backtest; no strategy discovery or venue connectivity","PBO unavailable with only two genuinely independent historical windows, and fee profiles are not extra independent folds"]
}
if OUT.exists():raise ValueError("refuse_to_overwrite_research_report")
OUT.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
print(json.dumps({"rows":report["original_rows"],"folds":len(plan.folds),"trades":len(ret),"MC_loss_probability":mc["lossProbability"],"MC_drawdown_median":mc["drawdownPercentiles"].get("50"),"DSR_available":dsr["available"],"PBO":pbo["reason"],"report":str(OUT),"live":False},sort_keys=True))
