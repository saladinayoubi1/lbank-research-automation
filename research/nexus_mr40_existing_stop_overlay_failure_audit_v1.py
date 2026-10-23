"""MR40 risk-overlay outcome reconciliation against ALREADY completed source studies.

This is an audit of old results, NOT a newly blinded experiment, optimization,
trade simulator or suggestion to promote any stop or risk rule to Paper.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path

SOURCES={
"trigger_ratchet_result":"e5287176023ace0da642559bbe848bb709d222fdf273c277ea9cd6567e2ad285",
"early_fuse_result":"2a6bfb6c6f7870056c70c2f4accb9362a8337717c23a5649d2b122db26344cd9",
"partial_trim_result":"01444ccb9346416dd948d5679692f359cc78a75f493695077cff8e7477ded6f4",
"ratchet_unarmed_audit":"423aa9c28fbb3e23ebce62ea1e731db8922a84ee87da04f891473c9a236852bc",
"ratchet_equal_cash_audit":"f4bdae81685bb8ec4c28e57a4afc14b3efdbf12c9c02af8eda4d5bd350bb88a2",
"trigger_policy":"f791ef3ae7044ba5dac21d716ebafac153e615ec9a7d0426320fa71007261714",
"early_policy":"8e87c146248598495fe86d58baf2d4535d7ed8e6303467bd4d22bb865667dc33",
"trim_policy":"0c71de53fc54c2298d8660306be75d54a25661c82f453101ae1d2c0dad0698f0",
}
RESULT_DIGEST={
"trigger_ratchet_result":"56623e1509ccc3a88a1fba1bb47d1a87a699cf953d8a661b71e49db4e18cd5b3",
"early_fuse_result":"7c573b72a0907e573b67f4f552ab8fb0b6c131a55f0ec2b2328b42e64f7b67a7",
"partial_trim_result":"61971ef7504cd269f04ae4512727f648a2a720791b73b983c2d0a3090adb3fb6",
"ratchet_unarmed_audit":"2a8f7d1c97b0eadb4b719ad65ddb8aa6543eb3a972c84921e6dbf3d137f22db1",
"ratchet_equal_cash_audit":"99cb681c4169a70a3a273e74a394f2edfab9440e72e65b0df4aeaad17d84ac91",
}

def canon(d):
    return json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()

def read_pinned(paths):
    data={}
    for key,expected in SOURCES.items():
        source=Path(paths[key]);raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise ValueError("PINNED_SOURCE_CHANGED_"+key)
        d=json.loads(raw)
        if key in RESULT_DIGEST and d.get("digest")!=RESULT_DIGEST[key]:
            raise ValueError("SOURCE_RESULT_DIGEST_CHANGED_"+key)
        data[key]=d
    return data

def select_row(d,window,profile,case):
    matched=[r for r in d["rows"] if r.get("window")==window and
             r.get("profile")==profile and r.get("case")==case and
             r.get("venue")=="Bybit" and r.get("capital")==10000]
    if len(matched)!=1:
        raise ValueError("MISSING_OR_AMBIGUOUS_10K_RESULT_"+window+"_"+profile+"_"+case)
    r=matched[0]
    return {k:r[k] for k in ("net_pnl_usdt","max_close_drawdown_pct",
                             "longest_underwater_days","cagr_pct")}

def audit_source(docs):
    names=("trigger_ratchet_result","early_fuse_result","partial_trim_result")
    cases={
       "trigger_ratchet_result":("arm2_be",True),
       "early_fuse_result":("baseline",False),
       "partial_trim_result":("trim75at8",True),
    }
    out={}
    for key in names:
        x=docs[key];candidate,changes=cases[key]
        if (x["paper_changed"] is not False or x["research_only"] is not True or
            x["evaluation_success"]!={"efficiency":False,"profit":False}):
            raise ValueError("PREVIOUS_STUDY_CONCLUSION_CHANGED_"+key)
        selection=x["selection"]
        if key=="trigger_ratchet_result" and (selection["profit"]!="arm2_be" or selection["efficiency"]!="arm2_be"):
            raise ValueError("RATCHET_TRAIN_SELECTION_CHANGED")
        if key=="early_fuse_result" and (selection["profit"]!="baseline" or selection["efficiency"]!="baseline"
                                         or selection["profit_eligible"] or selection["efficiency_eligible"]):
            raise ValueError("EARLY_FUSE_NO_TRAIN_QUALIFIER_CHANGED")
        if key=="partial_trim_result" and (selection["profit"]!="baseline" or selection["efficiency"]!="trim75at8"):
            raise ValueError("PARTIAL_TRIM_TRAIN_SELECTION_CHANGED")
        rows={}
        for window in ("train","evaluation"):
            rows[window]={}
            for profile in ("normal","stress"):
                baseline=select_row(x,window,profile,"baseline")
                selected=select_row(x,window,profile,candidate)
                rows[window][profile]={
                    "baseline":baseline,"previous_training_selected":selected,
                    "net_pnl_change_usdt_10000_reference":round(selected["net_pnl_usdt"]-baseline["net_pnl_usdt"],8),
                    "closed_dd_change_percentage_points":round(selected["max_close_drawdown_pct"]-baseline["max_close_drawdown_pct"],8),
                }
        out[key]={
            "training_selected_profit":selection["profit"],
            "training_selected_efficiency":selection["efficiency"],
            "evaluation_success_profit":False,"evaluation_success_efficiency":False,
            "underlying_historical_results_are_not_untouched_today":True,
            "capital_per_separate_old_path_usdt":10000,
            "windows":rows,
        }
    rat=out["trigger_ratchet_result"]["windows"]["evaluation"]
    for profile in ("normal","stress"):
        if (rat[profile]["net_pnl_change_usdt_10000_reference"]!=0 or
            rat[profile]["closed_dd_change_percentage_points"]!=0):
            raise ValueError("ARM2_EVAL_REPLAY_IS_NOT_INERT")
    tri=out["partial_trim_result"]["windows"]["evaluation"]
    for profile in ("normal","stress"):
        if (tri[profile]["net_pnl_change_usdt_10000_reference"]>=0 or
            tri[profile]["closed_dd_change_percentage_points"]<=0):
            raise ValueError("TRIM_EVAL_OUTCOME_NO_LONGER_ADVERSE")
    unarmed=docs["ratchet_unarmed_audit"]["unarmed_loss_coverage"]
    ev=unarmed["evaluation"]
    if (ev["losers"]!=4 or ev["losers_without_2pct_closed_trigger"]!=4 or
        len(ev["worst_unarmed"])!=4 or
        any(p["hit_arm2_close"] or p["first_arm_close_utc"] is not None for p in ev["worst_unarmed"])):
        raise ValueError("RATCHET_UNARMED_EVAL_LOSSES_CHANGED")
    cash=docs["ratchet_equal_cash_audit"]["windows"]
    train=[w for w in cash if w["window"]=="train"]
    evals=[w for w in cash if w["window"]=="evaluation"]
    if (len(train)!=2 or len(evals)!=2 or
        any(w["focus_log_contribution_pct"]<=100 for w in train) or
        any(w["relative_terminal_wealth_gain_pct"]!=0 for w in evals)):
        raise ValueError("TRAIN_ADVANTAGE_SINGLE_EVENT_DEPENDENCE_CHANGED")
    # Per-study 10k profiles are NOT the user's unchanged 500 USDT Paper
    # reference and do NOT prove subsequent fill / economic outperformance.
    return {
        "studies":out,
        "ratchet_failure_mode":{
            "evaluation_baseline_loss_makers":4,
            "no_2pct_completed_close_arm_on_any_eval_loser":True,
            "evaluation_selected_case_did_not_reduce_any_risk_or_raise_profit":True,
            "unarmed_losers_source_rows":[
               {k:p[k] for k in ("entry_utc","exit_utc","holding_h",
                                  "max_completed_close_gain_pct","baseline_pnl")}
               for p in ev["worst_unarmed"]
            ],
            "train_ratchet_relative_gain_log_contribution_from_aug2024_focus_pct":{
                x["profile"]:x["focus_log_contribution_pct"] for x in train
            },
            "fair_comparison_limit":"Separate compounded-path USDT PNL deltas are NOT equal-capital causal treatment effects; normalized log contributions also not counterfactual reruns.",
        },
        "research_decision":{
            "new_stop_parameter_optimization_done":False,
            "existing_trigger_staged_stop_demonstrated_forward_success":False,
            "new_Paper_rule_authorized":False,
            "why":"Previously trained improvements failed independent historical evaluation; trigger after closed +2% cannot protect positions never achieving that arm condition. Existing 2025–26 evaluation has now been seen; future OOS requires fresh chronology, actual source receipt and execution-cost evidence.",
        },
    }

def run(paths,out):
    out=Path(out)
    if out.exists():raise ValueError("REFUSE_OVERWRITE_SOURCE_AUDIT")
    old=read_pinned(paths)
    info=audit_source(old)
    doc={
        "schema":"nexus.mr40.existing_stop_overlay_studies_integrity_and_failure_attribution.v1",
        "classification":"RETROSPECTIVE_AUDIT_ALREADY_SEEN_TRAIN_EVALUATION_NOT_NEW_BACKTEST",
        "source_file_sha256":SOURCES,
        "source_result_digest":RESULT_DIGEST,
        **info,
        "no_orders":True,"paper_reference_500_usdt_unchanged":True,
        "private_exchange_API":False,"live":False,"merge":False,"promote":False
    }
    doc["digest"]=hashlib.sha256(canon(doc)).hexdigest()
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(doc,ensure_ascii=False,sort_keys=True,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"digest":doc["digest"],
      "selected":{k:v["training_selected_efficiency"] for k,v in info["studies"].items()},
      "evaluation_passes":{k:v["evaluation_success_efficiency"] for k,v in info["studies"].items()},
      "ratchet_unarmed_eval_losers":ev["losers"] if (ev:=old["ratchet_unarmed_audit"]["unarmed_loss_coverage"]["evaluation"]) else None,
      "evaluation_deltas":{k:v["windows"]["evaluation"] for k,v in info["studies"].items()}},ensure_ascii=False))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in SOURCES:p.add_argument("--"+name,required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    opts=vars(p.parse_args());out=opts.pop("output")
    run(opts,out)
