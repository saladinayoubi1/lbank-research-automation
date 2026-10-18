"""One frozen source-system Research task and an orthogonal numerical QA worker.

Uses the existing reviewed intake, original Bybit loader and shared-cash engine.
The QA reference does not call factory_signal, sidecar_summary or replay_shared_cash.
Source features are shared: execution independence is not independent feature research.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from nexus_complete_strategy_system import digest, _read
from nexus_composite_strategy_research import build_features, ALL_MECHANISMS, FACTORY_SPECS, signal_for
from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
from scripts import nexus_strategy_finder_executable_intake as intake
from scripts.nexus_strategy_finder_shared_cash_eval import verify_pinned_market_files, write_once
from scripts.select_nexus_bybit_replay_artifact import _ARTIFACT_OPENER

REQUEST = "research/source_system_economic_requests/failure_test_structural_v1.json"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
REPOSITORY = "saladinayoubi1/lbank-research-automation"
SCHEMA = "nexus.source-system-economic-task.v1"
SCRIPT = "scripts/nexus_source_system_economic_execution.py"
SUPPORT = ("nexus_complete_strategy_system.py","scripts/select_nexus_bybit_replay_artifact.py",
           "nexus_demo_archive_replay.py","research/mechanism_factory_v1.json",
           "requirements.lock","requirements-dev.lock")


class EconomicTaskError(ValueError):
    pass


def read_json(path: Path, limit: int = 5_000_000) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise EconomicTaskError("missing, linked or oversized economic evidence")
    value = json.loads(path.read_bytes().decode("utf-8"))
    if type(value) is not dict:
        raise EconomicTaskError("economic evidence must be an object")
    return value


def load_task(root: Path = ROOT) -> tuple[dict, dict, str]:
    req = read_json(root / REQUEST, 100_000)
    keys = {"schema", "id", "candidate_path", "system_specification_path",
            "system_specification_sha256", "worker_source_sha256", "support_source_sha256", "selection_basis",
            "research_only", "paper_eligible", "live_enabled", "automatic_strategy_promotion"}
    if (set(req) != keys or req["schema"] != SCHEMA or req["id"] != "failure_test_structural_v1"
        or req["selection_basis"] != "one_frozen_hypothesis_no_posthoc_tournament"
        or req["research_only"] is not True or any(req[k] is not False for k in (
            "paper_eligible", "live_enabled", "automatic_strategy_promotion"))):
        raise EconomicTaskError("unreviewed or unsupported economic task")
    actual = hashlib.sha256((Path(__file__).resolve()).read_bytes()).hexdigest()
    if req["worker_source_sha256"] != actual or hashlib.sha256((root / SCRIPT).read_bytes()).hexdigest() != actual:
        raise EconomicTaskError("economic worker changed after request freeze")
    def support_hashes(base):
        result = {}
        for relative in SUPPORT:
            p = base/relative
            if p.is_symlink() or p.parent.is_symlink() or not p.is_file():
                raise EconomicTaskError("economic supporting source missing or linked")
            result[relative] = hashlib.sha256(p.read_bytes()).hexdigest()
        return result
    if req["support_source_sha256"] != support_hashes(ROOT) or support_hashes(root) != support_hashes(ROOT):
        raise EconomicTaskError("economic supporting code or dependency locks changed after freeze")
    permits = intake._load_json_strict(root / intake.DEFAULT_ALLOWLIST, 200_000)
    row = intake.inspect_candidate(root, req["candidate_path"], permits)
    complete = row.get("complete_system", {})
    if (row["status"] != "APPROVED_FOR_RESEARCH_SIMULATION_ONLY"
        or row.get("candidate_sha256") != "ad20bb4b3d18da4b601793c6bdccdf42623187803df7389ffb2b6da3e75be92d"
        or row.get("candidate_id") != "factory_prior_day_sweep_peer_resilience"
        or complete.get("system_specification_path") != req["system_specification_path"]
        or complete.get("system_specification_sha256") != req["system_specification_sha256"]):
        raise EconomicTaskError("exact complete-system research permit required")
    system, _ = _read(root, req["system_specification_path"], "system")
    if system["execution_contract"].get("stop_policy") != "signal_bar_low_v1":
        raise EconomicTaskError("this bounded task models only the source-defined signal-low stop")
    task_id = "SYSTEM-ECON-" + hashlib.sha256((root / REQUEST).read_bytes()).hexdigest()[:24]
    return req, row, task_id


def scoped_features(archive: Path, window: dict) -> dict:
    verify_pinned_market_files(archive)
    warm, end = pd.Timestamp(window["warmup_utc"]), pd.Timestamp(window["end_exclusive_utc"])
    frames = {}
    for symbol in SYMBOLS:
        frames[symbol] = {}
        for tf in ("minute15", "hour1", "hour4"):
            frame = load_verified_archive_frame(archive, symbol, tf)
            ts = pd.to_datetime(frame["timestamp"], utc=True)
            frames[symbol][tf] = frame.loc[(ts >= warm) & (ts < end)].reset_index(drop=True)
    result = {}
    start = pd.Timestamp(window["start_utc"])
    for symbol, peer in ((SYMBOLS[0], SYMBOLS[1]), (SYMBOLS[1], SYMBOLS[0])):
        f = build_features(frames[symbol], peer_15m=frames[peer]["minute15"])
        result[symbol] = f.loc[(f["decision_at"] >= start) & (f["decision_at"] < end)].reset_index(drop=True)
    return result


def reference_signal(f: pd.DataFrame) -> np.ndarray:
    """Explicit nine fixed equations; independent of the factory DSL interpreter."""
    fields = ["h4_range","h1_vol_ok","lagged_peer_beta_residual","lagged_downside_variance_share_64",
              "low","prior_day_low","close","open","close_location","rel_vol"]
    finite = np.isfinite(f[fields].to_numpy(float)).all(axis=1)
    return finite & ((f.h4_range == 1) & (f.h1_vol_ok == 1)
            & (f.lagged_peer_beta_residual > 0) & (f.lagged_downside_variance_share_64 > .5)
            & (f.low < f.prior_day_low) & (f.close > f.prior_day_low)
            & (f.close > f.open) & (f.close_location >= .6) & (f.rel_vol >= 1)).fillna(False).to_numpy(bool)


def reference_partition(frames: dict, lo: int, hi: int, profile: str) -> dict:
    """Independent event/accounting reference with the frozen source stop.

    Keeps cash deltas, raw price contribution and each cost separate. No calls
    to the production signal interpreter or simulator are made in this worker.
    """
    fee, slip = {"conservative":(.001, .0005), "stress":(.0025, .0015)}[profile]
    sig = {s: reference_signal(f) for s, f in frames.items()}
    prices = {s: f[["open", "high", "low", "close"]].to_numpy(float) for s, f in frames.items()}
    ts = {s: pd.DatetimeIndex(f.decision_at).asi8 // 1_000_000 for s, f in frames.items()}
    cash, peak, dd, position = 500., 500., 0., None
    rows, denials, attempts, count = [], Counter(), Counter(), 0
    for i in range(lo, hi):
        due = [s for s in SYMBOLS if i > lo and sig[s][i-1]]
        count += len(due)
        if position is not None:
            denials["SHARED_CASH_POSITION_OCCUPIED"] += len(due)
        else:
            for s in due:
                attempts["next_open_intent"] += 1
                mid, anchor = float(prices[s][i, 0]), float(prices[s][i-1, 2])
                if mid <= anchor:
                    denials["NEXT_OPEN_AT_OR_BELOW_SIGNAL_LOW"] += 1
                    continue
                buy = mid * (1 + slip)
                risk = buy * (1 + fee) - anchor * (1 - slip) * (1 - fee)
                qty = math.floor(min(250 / buy, 2.5 / risk, cash / (buy * (1 + fee))) * 1e8) / 1e8
                if qty <= 0:
                    denials["NO_SHARED_CASH_OR_RISK_CAPACITY"] += 1
                    continue
                cost = qty * buy * (1 + fee)
                cash -= cost
                position = dict(symbol=s, i=i, mid=mid, buy=buy, stop=anchor,
                                target=buy + 2 * (buy-anchor), qty=qty, cost=cost)
                attempts["admitted"] += 1
                denials["SAME_OPEN_LOWER_PRIORITY_PEER"] += len(due) - due.index(s) - 1
                break
        if position is not None:
            p = position
            op, high, low, close = prices[p["symbol"]][i]
            reason, mark = None, None
            if op <= p["stop"]:
                reason, mark = "STOP_GAP_AT_WORSE_OPEN", op
            elif i - p["i"] >= 64:
                reason, mark = "TIMEOUT_AT_PHYSICAL_NEXT_OPEN", op
            elif low <= p["stop"]:
                reason, mark = ("STOP_FIRST_INTRABAR_BOTH" if high >= p["target"] else "STRUCTURAL_STOP"), p["stop"]
            elif high >= p["target"]:
                reason, mark = "PRECOMMITTED_TARGET", p["target"]
            elif i == hi-1:
                reason, mark = "PARTITION_LAST_COMPLETED_CLOSE", close
            if reason is not None:
                sell, qty = float(mark) * (1-slip), p["qty"]
                entry_fee, exit_fee = qty*p["buy"]*fee, qty*sell*fee
                net = qty*sell-exit_fee-p["cost"]
                gross = qty*(float(mark)-p["mid"])
                slippage = qty*((p["buy"]-p["mid"])+(float(mark)-sell))
                cash += qty*sell-exit_fee
                open_exit = reason in {"STOP_GAP_AT_WORSE_OPEN","TIMEOUT_AT_PHYSICAL_NEXT_OPEN"}
                rows.append(dict(symbol=p["symbol"], entry_open_ms=int(ts[p["symbol"]][p["i"]]-900000),
                                 exit_event_ms=int(ts[p["symbol"]][i]-(900000 if open_exit else 0)),
                                 exit_bar_close_ms=int(ts[p["symbol"]][i]), exit_reason=reason,
                                 exit_clock="exact_open" if open_exit else "bounded_to_completed_15m_bar",
                                 qty=round(qty,8), entry_mid=round(p["mid"],8), exit_mid=round(float(mark),8),
                                 entry_fill=round(p["buy"],8), exit_fill=round(sell,8),
                                 stop=round(p["stop"],8), target=round(p["target"],8),
                                 entry_fee_usdt=round(entry_fee,8), exit_fee_usdt=round(exit_fee,8),
                                 gross_price_pnl_usdt=round(gross,8), slippage_usdt=round(slippage,8),
                                 total_friction_usdt=round(slippage+entry_fee+exit_fee,8), pnl_usdt=round(net,8)))
                position = None
        value = cash if position is None else cash + position["qty"]*prices[position["symbol"]][i,3]
        peak = max(peak, value)
        dd = max(dd, 1-value/peak)
    return dict(ledger=rows, ending_shared_cash_usdt=cash, net_pnl_usdt=cash-500,
                max_drawdown_pct=100*dd, signals_due_at_next_open=count,
                attempt_counts={k:v for k,v in attempts.items() if v},
                denial_reasons={k:v for k,v in denials.items() if v})


def verify_partition(actual: dict, expected: dict) -> None:
    if len(actual["ledger"]) != len(expected["ledger"]):
        raise EconomicTaskError("independent QA: missing or invented closed position")
    for got, want in zip(actual["ledger"], expected["ledger"]):
        for key, value in want.items():
            if isinstance(value, (float, int)):
                if not isinstance(got.get(key), (float,int)) or abs(got[key]-value)>1e-7:
                    raise EconomicTaskError("independent QA: trade mismatch " + key)
            elif got.get(key) != value:
                raise EconomicTaskError("independent QA: event mismatch " + key)
    for key in ("ending_shared_cash_usdt", "net_pnl_usdt", "max_drawdown_pct"):
        if abs(actual[key]-expected[key])>1e-6:
            raise EconomicTaskError("independent QA: capital book mismatch " + key)
    for key in ("signals_due_at_next_open", "attempt_counts", "denial_reasons"):
        if actual[key] != expected[key]:
            raise EconomicTaskError("independent QA: admission mismatch " + key)
    rows = expected["ledger"]
    average = expected["net_pnl_usdt"]/len(rows) if rows else None
    if (average is None and actual["mean_pnl_usdt"] is not None
        or average is not None and abs(actual["mean_pnl_usdt"]-average)>1e-7):
        raise EconomicTaskError("independent QA: average closed-position PNL mismatch")
    totals = {"fees_paid_usdt":sum(t["entry_fee_usdt"]+t["exit_fee_usdt"] for t in rows),
              **{k:sum(t[k] for t in rows) for k in (
                  "gross_price_pnl_usdt","slippage_usdt","total_friction_usdt")}}
    for key, value in totals.items():
        if abs(actual[key]-value)>1e-6:
            raise EconomicTaskError("independent QA: cost summary mismatch " + key)
    if (actual["trades"] != len(rows)
        or actual["positive_trades"] != sum(t["pnl_usdt"]>0 for t in rows)
        or abs(totals["gross_price_pnl_usdt"]-totals["total_friction_usdt"]-actual["net_pnl_usdt"])>1e-6):
        raise EconomicTaskError("independent QA: gross minus friction does not equal net")
    monthly = {}
    for row in rows:
        month = pd.Timestamp(row["exit_event_ms"],unit="ms",tz="UTC").strftime("%Y-%m")
        n, pnl = monthly.get(month,(0,0.))
        monthly[month] = (n+1,pnl+row["pnl_usdt"])
    if (len(actual["monthly"]) != len(monthly)
        or {r["month"] for r in actual["monthly"]} != set(monthly)):
        raise EconomicTaskError("independent QA: monthly book missing")
    for r in actual["monthly"]:
        n, pnl = monthly[r["month"]]
        if (r["round_trips"] != n or abs(r["net_pnl_usdt"]-pnl)>1e-6
            or abs(r["mean_pnl_usdt"]-pnl/n)>1e-6):
            raise EconomicTaskError("independent QA: monthly book drift")


def benchmark(frames: dict, lo: int, hi: int, profile: str) -> dict:
    """Passive 250-USDT budget per asset, fees inside 500 cash, same costs."""
    fee, slip = {"conservative":(.001,.0005), "stress":(.0025,.0015)}[profile]
    cash = 500.
    for f in frames.values():
        # lo is the partition's initial completed-close decision. The earliest
        # observable fill for both strategy and benchmark is the next open.
        buy = float(f.open.iloc[lo+1])*(1+slip)
        qty = math.floor((250/(buy*(1+fee)))*1e8)/1e8
        cash -= qty*buy*(1+fee)
        cash += qty*float(f.close.iloc[hi-1])*(1-slip)*(1-fee)
    return {"cash_only_net_pnl_usdt":0., "equal_budget_buy_hold_net_pnl_usdt":round(cash-500,8),
            "benchmark_entry":"first_permitted_next_open_after_initial_partition_close",
            "benchmark_is_research_comparison_not_strategy_selection":True}


def check_result(result: dict, req: dict, row: dict, task_id: str) -> None:
    if (result.get("result_digest") != digest({k:v for k,v in result.items() if k!="result_digest"})
        or result.get("economic_task",{}).get("task_id") != task_id
        or result.get("economic_task",{}).get("producer") != "research-agent"
        or result.get("economic_task",{}).get("lane") != "github-cloud"
        or not re.fullmatch(r"[0-9a-f]{40}",str(result.get("economic_task",{}).get("source_sha","")))
        or result.get("complete_system_digest") != row["complete_system"]["system_digest"]
        or result.get("readiness") != row
        or result.get("paper_eligible") is not False or result.get("live_enabled") is not False
        or result.get("real_exchange_orders") != 0):
        raise EconomicTaskError("stale, altered or unauthorized economic result")


def _api_json(url: str) -> dict:
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise EconomicTaskError("GitHub artifact read token unavailable")
    request = urllib.request.Request(url,headers={"Authorization":"Bearer "+token,
                                                  "Accept":"application/vnd.github+json"})
    with urllib.request.urlopen(request,timeout=60) as response:
        data = response.read(5_000_001)
    if len(data)>5_000_000:
        raise EconomicTaskError("oversized GitHub artifact metadata")
    return json.loads(data)


def restore_result(destination: Path, task_id: str, *, current_run: bool = False) -> bool:
    """Reuse completed main producer evidence; a QA retry never replays markets."""
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise EconomicTaskError("economic artifact repository mismatch")
    committed = ROOT/"research/source_system_economic_results"/(task_id+".json")
    if committed.is_file():
        req,row,expected_id = load_task()
        if expected_id != task_id:
            raise EconomicTaskError("committed economic task mismatch")
        value = read_json(committed)
        check_result(value,req,row,task_id)
        write_once(destination,value)
        return True
    base = "https://api.github.com/repos/"+REPOSITORY
    name = "nexus-source-system-economic-"+task_id
    endpoint = (base+"/actions/runs/"+os.environ["GITHUB_RUN_ID"]+"/artifacts?per_page=100"
                if current_run else base+"/actions/artifacts?name="+name+"&per_page=100")
    artifacts = _api_json(endpoint).get("artifacts",[])
    candidates = sorted((a for a in artifacts if a.get("name")==name and not a.get("expired")),
                        key=lambda a:a["created_at"],reverse=True)
    for artifact in candidates:
        run_id = artifact.get("workflow_run",{}).get("id") or os.environ["GITHUB_RUN_ID"]
        run = _api_json(base+"/actions/runs/"+str(run_id))
        if (run.get("head_branch") != "main" or run.get("event") not in {"push","workflow_dispatch"}
            or run.get("path") != ".github/workflows/nexus_multitimeframe_strategy_discovery.yml"):
            continue
        request = urllib.request.Request(base+"/actions/artifacts/"+str(artifact["id"])+"/zip",
                                         headers={"Authorization":"Bearer "+os.environ["GH_TOKEN"]})
        with _ARTIFACT_OPENER.open(request,timeout=60) as response:
            raw = response.read(10_000_001)
        if len(raw)>10_000_000:
            raise EconomicTaskError("oversized economic result artifact")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            matches = [x for x in archive.infolist() if x.filename=="research.json"]
            if len(matches)!=1 or not 0<matches[0].file_size<5_000_000:
                raise EconomicTaskError("economic artifact has no unique bounded research result")
            value = json.loads(archive.read(matches[0]).decode("utf-8"))
        req,row,expected_id = load_task()
        if expected_id != task_id:
            raise EconomicTaskError("economic artifact task mismatch")
        check_result(value,req,row,task_id)
        if (str(value["economic_task"].get("workflow_run_id")) != str(run_id)
            or value["economic_task"].get("source_sha") != run.get("head_sha")):
            continue
        write_once(destination,value)
        return True
    if not current_run:
        started_name = "nexus-source-system-economic-started-"+task_id
        started = _api_json(base+"/actions/artifacts?name="+started_name+"&per_page=100").get("artifacts",[])
        for artifact in started:
            if artifact.get("name") != started_name or artifact.get("expired"):
                continue
            run_id = artifact.get("workflow_run",{}).get("id")
            run = _api_json(base+"/actions/runs/"+str(run_id))
            if (run.get("head_branch")=="main" and run.get("event")=="push"
                and run.get("path")==".github/workflows/nexus_multitimeframe_strategy_discovery.yml"):
                raise EconomicTaskError("prior economic evaluation started without a finished artifact; reconcile it, do not replay automatically")
    return False


def research(archive: Path, output: Path) -> dict:
    req,row,task_id = load_task()
    window = row["complete_system"]["study_window"]
    result = intake.evaluate_approved(ROOT,req["candidate_path"],archive,**{
        "warmup_utc":window["warmup_utc"],"start_utc":window["start_utc"],
        "end_exclusive_utc":window["end_exclusive_utc"]})
    result["economic_task"] = {"task_id":task_id,"producer":"research-agent", "lane":"github-cloud",
                               "source_sha":os.environ.get("GITHUB_SHA",""),
                               "workflow_run_id":os.environ.get("GITHUB_RUN_ID","")}
    result["result_digest"] = digest({k:v for k,v in result.items() if k!="result_digest"})
    write_once(output,result)
    return result


def economic_disposition(rows: list[dict]) -> str:
    if not any(v["trades"] for v in rows):
        return "NO_EXECUTION_EVIDENCE"
    if any(v["net_pnl_usdt"]<0 for v in rows):
        return "HISTORICAL_NEGATIVE_DO_NOT_RETUNE"
    if any(v["trades"]==0 for v in rows):
        return "MIXED_ACTIVITY_NO_EXECUTION_EVIDENCE_IN_SOME_PARTITIONS"
    return "HISTORICAL_POSITIVE_ONLY_FUTURE_EVIDENCE_REQUIRED"


def qa(archive: Path, producer: Path, output: Path) -> dict:
    req,row,task_id = load_task()
    result = read_json(producer)
    check_result(result,req,row,task_id)
    features = scoped_features(archive,row["complete_system"]["study_window"])
    clocks = [pd.DatetimeIndex(features[s].decision_at) for s in SYMBOLS]
    if (not clocks[0].equals(clocks[1]) or not clocks[0].is_unique
        or not np.all(np.diff(clocks[0].asi8)==900_000_000_000)):
        raise EconomicTaskError("independent QA: inconsistent physical BTC/ETH clock")
    if any(int(reference_signal(features[s]).sum())!=result["raw_closed_bar_signals"][s] for s in SYMBOLS):
        raise EconomicTaskError("independent signal equations disagree with producer")
    n = len(features[SYMBOLS[0]])
    boundaries = {"training":(0,int(n*.6)), "validation_already_inspected":(int(n*.6),int(n*.8)),
                  "historical_test_already_inspected":(int(n*.8),n)}
    summary = {}
    for part,(lo,hi) in boundaries.items():
        summary[part] = {}
        for cost in ("conservative","stress"):
            actual = result["partitions"][part][cost]
            verify_partition(actual,reference_partition(features,lo,hi,cost))
            summary[part][cost] = {k:actual[k] for k in (
                "trades","gross_price_pnl_usdt","total_friction_usdt","net_pnl_usdt",
                "max_drawdown_pct","mean_pnl_usdt","ending_shared_cash_usdt")}
            summary[part][cost].update(benchmark(features,lo,hi,cost))
    overlap = {}
    for s,f in features.items():
        proposed = reference_signal(f)
        union = np.zeros(len(f),bool)
        per_family = {}
        for mechanism in ALL_MECHANISMS:
            cfg = {"mechanism":mechanism,"risk_variant":0}
            if mechanism in FACTORY_SPECS:
                cfg["factory_contract_digest"] = FACTORY_SPECS[mechanism]["contract_digest"]
            old = signal_for(f,cfg)
            hit = int((old & proposed).sum())
            if hit:
                per_family[mechanism] = hit
            union |= old
        overlap[s] = {"proposal_events":int(proposed.sum()),"legacy_union_overlap":int((proposed & union).sum()),
                      "unmatched_on_this_window":int((proposed & ~union).sum()),"overlapping_mechanisms":per_family}
    rows = [v for p in summary.values() for v in p.values()]
    disposition = economic_disposition(rows)
    evidence = {"schema":SCHEMA,"task_id":task_id,"status":"DONE_NUMERICAL_QA",
                "producer_result_digest":result["result_digest"],"verifier":"qa-verifier-agent",
                "verifier_source_sha":os.environ.get("GITHUB_SHA",""),
                "independent_signal_equations_verified":True,"independent_execution_arithmetic_verified":True,
                "feature_engine_shared_with_producer":True,"minimum_trade_count":None,
                "partitions":summary,"legacy_mechanisms_compared":len(ALL_MECHANISMS),
                "event_overlap":overlap,"global_semantic_novelty_proven":False,
                "disposition":disposition,"economic_edge_established":False,"prospective_holdout":False,
                "paper_eligible":False,"demo_eligible":False,"live_enabled":False,"orders":0}
    evidence["receipt_digest"] = digest(evidence)
    write_once(output,evidence)
    return evidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mode",choices=("preflight","research","restore-current","qa"))
    ap.add_argument("--archive-root",type=Path,default=Path("build/bybit_dataset"))
    ap.add_argument("--output-dir",type=Path,default=Path("build/source-system-economic"))
    args = ap.parse_args()
    req,row,task_id = load_task()
    dest = args.output_dir/"research.json"
    if args.mode=="preflight":
        reused = restore_result(dest,task_id)
        if not reused:
            write_once(args.output_dir/"start.json",{
                "task_id":task_id,"request_sha256":hashlib.sha256((ROOT/REQUEST).read_bytes()).hexdigest(),
                "source_sha":os.environ.get("GITHUB_SHA",""),"market_replay_performed":False,
                "policy":"one_frozen_run_no_automatic_replay_after_start", "live_enabled":False})
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"],"a",encoding="utf-8") as f:
                f.write("task_id="+task_id+"\nreused="+str(reused).lower()+"\n")
        print(json.dumps({"task_id":task_id,"reused_completed_market_evidence":reused}))
    elif args.mode=="restore-current":
        if not (restore_result(dest,task_id,current_run=True) or restore_result(dest,task_id)):
            raise EconomicTaskError("current Research job produced no exact task artifact")
    elif args.mode=="research":
        result = research(args.archive_root,dest)
        print(json.dumps({"task_id":task_id,"result_digest":result["result_digest"],"market_replay_performed":True}))
    else:
        print(json.dumps(qa(args.archive_root,dest,args.output_dir/"qa.json"),sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
