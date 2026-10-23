"""Pure MR40 candle evaluator for externally hosted Optuna ask/tell trials.

Research-only. Frozen source and baseline hashes are validated by inputs().
Do not use any exchange API, Private credentials, Paper or runtime state.
"""
import json
import math
import sys
from pathlib import Path
from research.nexus_mr40_one_combination_ablation_v1 import inputs, scenario, date_ms, STEP

CASES=("baseline","vol40_only","stop4_arm2_only","vol40_stop4_arm2")
ROOT=Path(__file__).resolve().parents[1]
INPUT_DIR=Path("E:/NEXUS-Research/MR40-Staged-Entry-20261022/source/inputs")
LEDGER=Path("E:/NEXUS-Research/MR40-Entry-Quality-20261022/results/ledger.jsonl.gz")
POLICY=Path("E:/NEXUS-Research/MR40-Entry-Event-20261022/research/mr40_one_combination_ablation_protocol_20261022.json")
ARCHIVE=ROOT/"docs/evidence/mr40-entry-event-contract-20261022/one_combination_ablation.json"

def evaluate(case,window):
    if case not in CASES or window not in ("train","evaluation"):
        raise ValueError("unregistered_case_or_window")
    contract,rows,refs=inputs(INPUT_DIR,LEDGER,POLICY)
    if len(rows)!=8514 or tuple(x["id"] for x in contract["cases"])!=CASES:
        raise ValueError("data_or_case_drift")
    if sorted(contract["capital_usdt"])!=[500,10000]:
        raise ValueError("capital_drift")
    a,b=contract["windows"][window]
    first=next(i for i,r in enumerate(rows) if r[0]==date_ms(a))
    last=next((i for i,r in enumerate(rows) if r[0]==date_ms(b)),len(rows))
    if first<181 or rows[last-1][0]+STEP!=date_ms(b):
        raise ValueError("bar_boundary_drift")
    prof=contract["profiles"]["stress"]
    setup=next(x for x in contract["cases"] if x["id"]==case)
    result,positions=scenario(rows,refs[(window,500,"stress")],contract,setup,500,prof["fee_bp"],prof["slip_bp"],first,last)
    archived=json.loads(ARCHIVE.read_text())
    if archived["promote"] is not False or archived["genuine_forward_oos"] is not False:
        raise ValueError("promotion_or_blind_claim_drift")
    expected=next(x for x in archived["cases"] if x["capital"]==500 and x["window"]==window and x["profile"]=="stress" and x["case"]==case)
    for key in ("net_pnl_usdt","max_intrabar_low_bound_pct","max_close_drawdown_pct","fees_usdt"):
        if not math.isclose(result[key],expected[key],rel_tol=1e-10,abs_tol=1e-7):
            raise ValueError("archive_oracle_mismatch:"+key)
    if result["closed_positions"]!=len(positions) or result["closed_positions"]!=expected["closed_positions"]:
        raise ValueError("closed_trades_mismatch")
    return {"case":case,"window":window,"profile":"stress","net_pnl_usdt":result["net_pnl_usdt"],"low_dd_pct":result["max_intrabar_low_bound_pct"],"closed_trades":len(positions),"fees_usdt":result["fees_usdt"],"parity":True,"live":False,"paper_changed":False,"real_orders":0,"ohlc_hash":contract["inputs"]["ohlc_digest"]}

if __name__=="__main__":
    if len(sys.argv)!=3:
        raise SystemExit("usage: python -m research.mr40_optuna_external_trial_20261023 CASE WINDOW")
    print("OPTUNA_CANDLE_TRIAL_JSON="+json.dumps(evaluate(sys.argv[1],sys.argv[2]),sort_keys=True))
