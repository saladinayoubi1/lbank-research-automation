"""Strategy Finder reviewed, declarative -> executable -> shared-cash research intake.

No new strategy is approved by adding this component. A catalog design row is
NOT executable. Acceptance requires an actual strict factory DSL JSON checked
into GitHub, a separate explicit reviewed SHA256 allowlist entry, and a coarse
qualitative topology check against all known factory DSL candidates. Mere ID,
name, family text and threshold tuning cannot bypass the novelty barrier.

The allowlist starts EMPTY. Review of ANY proposed entry must include external
source provenance and independent semantic overlap review vs older Python
families (which a simple grammar cannot mechanically prove). No runtime
dispatch, paper qualification, Demo promotion or live order permission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from nexus_mechanism_factory import (
    MechanismFactoryError,load_factory_contract,factory_signal
)
from nexus_composite_strategy_research import (
    FACTORY_SPECS,build_features
)
from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
from nexus_demo_archive_replay import ARCHIVE_SHA256
from research.strategy_finder_shared_cash_physical import (
    SYMBOLS,sidecar_summary,_digest
)
from scripts.nexus_strategy_finder_shared_cash_eval import (
    verify_pinned_market_files,write_once
)

SCHEMA="nexus.strategy-finder-reviewed-executable-intake.v1"
APPROVAL_SCHEMA="nexus.strategy-finder-executable-intake-allowlist.v1"
DEFAULT_ALLOWLIST=Path("research/strategy_finder_executable_intake_allowlist_v1.json")
APPROVED_ROOT=Path("research/intake_candidates")
ROOT=Path(__file__).resolve().parents[1]
MAX_CANDIDATE_BYTES=100_000
MAX_ALLOWLIST_BYTES=200_000
MAX_WINDOW_DAYS=150
_REVIEW_PR=re.compile(r"^https://github\.com/saladinayoubi1/lbank-research-automation/pull/[1-9][0-9]*$")
_SHA64=re.compile(r"^[0-9a-f]{64}$")


class IntakeError(ValueError):
    pass


def _reviewed_bytes(path:Path,limit:int)->bytes:
    if path.is_symlink() or not path.is_file() or not 0<path.stat().st_size<=limit:
        raise IntakeError("missing/linked/oversized executable review material")
    return path.read_bytes()


def _load_json_strict(path:Path,limit:int)->dict:
    try:
        value=json.loads(_reviewed_bytes(path,limit).decode("utf-8"))
    except (ValueError,UnicodeDecodeError,OSError) as exc:
        raise IntakeError("unreadable executable review JSON") from exc
    if type(value) is not dict:
        raise IntakeError("executable review JSON is not an object")
    return value


def structural_signature(spec:Mapping[str,Any])->str:
    """Coarse heuristic; never asserts global economic/semantic novelty.

    Order of independent AND conditions and family/name/hypothesis metadata
    are immaterial. A changed scalar cut (0.45 -> 0.50) is *not* a new
    mechanism. Direction and input-feature topology remain distinguishable.
    """
    def term(cond:Mapping[str,Any])->dict[str,Any]:
        result={"field":cond["field"],"op":cond["op"]}
        if "other" in cond:
            scale=float(cond["scale"])
            result.update({"rhs":"field","other":cond["other"],
                           "scale_sign":-1 if scale<0 else 1 if scale>0 else 0})
        else:
            value=float(cond["value"])
            result.update({"rhs":"scalar","scalar_sign":
                           -1 if value<0 else 1 if value>0 else 0})
            # Boolean condition states must remain meaningfully distinct.
            if cond["field"] in {"h4_up","h4_range","h1_compression","h1_vol_ok"}:
                result["binary_gate"]=value
        return result
    signature={}
    for stage in ("context","entry"):
        if not isinstance(spec.get(stage),list):
            raise IntakeError("missing reviewed stage")
        terms=[term(v) for v in spec[stage]]
        payloads=[json.dumps(t,sort_keys=True,separators=(",",":")) for t in terms]
        if len(payloads)!=len(set(payloads)):
            raise IntakeError("repeated structurally identical conjunctive gate")
        signature[stage]=sorted(payloads)
    return _digest(signature)


def existing_signatures()->dict[str,set[str]]:
    signatures={}
    for ident,spec in FACTORY_SPECS.items():
        token=structural_signature(spec)
        signatures.setdefault(token,set()).add(ident)
    return signatures


def inspect_candidate(
    root:Path,candidate_relative:str,allowlist:Mapping[str,Any]
)->dict[str,Any]:
    """Gate both qualitative novelty and separate explicit approval.

    If not yet approved, return a real machine-readable REVIEW_REQUIRED row;
    do not execute a market backtest, claim novelty or dispatch a job.
    """
    if (not isinstance(candidate_relative,str)
        or not re.fullmatch(r"research/intake_candidates/[a-z0-9_-]+\.json",
                            candidate_relative)):
        raise IntakeError("candidate must be a reviewed repo-local intake JSON")
    path=root/candidate_relative
    if path.resolve().parent!=(root/APPROVED_ROOT).resolve():
        raise IntakeError("candidate escapes committed intake candidate directory")
    raw=_reviewed_bytes(path,MAX_CANDIDATE_BYTES)
    rawsha=hashlib.sha256(raw).hexdigest()
    try:
        specs=load_factory_contract(path)
    except (MechanismFactoryError,ValueError,OSError) as exc:
        raise IntakeError("candidate not accepted by strict original reviewed factory DSL") from exc
    if len(specs)!=1:
        raise IntakeError("one candidate per separate review to forbid posthoc tournament")
    ident,spec=next(iter(specs.items()))
    signature=structural_signature(spec)
    matches=sorted(existing_signatures().get(signature,set()))
    if (type(allowlist) is not dict or set(allowlist)!={
        "schema","status","research_only","paper_only","live_trading_authority",
        "automatic_strategy_promotion","qualification_authority",
        "approved_executable_contracts"
    } or allowlist.get("schema")!=APPROVAL_SCHEMA
        or allowlist.get("research_only") is not True
        or allowlist.get("paper_only") is not True
        or allowlist.get("live_trading_authority") is not False
        or allowlist.get("automatic_strategy_promotion") is not False
        or allowlist.get("qualification_authority") is not False
        or not isinstance(allowlist.get("approved_executable_contracts"),list)):
        raise IntakeError("independent research review allowlist invalid")
    approved=allowlist["approved_executable_contracts"]
    if len(approved)>16:
        raise IntakeError("unbounded approval registry")
    seen=set()
    for row in approved:
        if (type(row) is not dict or set(row)!={
            "candidate_path","candidate_id","candidate_sha256",
            "qualitative_signature","review_pr_url",
            "independent_legacy_semantic_review","source_provenance_review",
            "rationale"
        } or not isinstance(row["candidate_path"],str)
            or not isinstance(row["candidate_id"],str)
            or not isinstance(row["candidate_sha256"],str)
            or not _SHA64.fullmatch(row["candidate_sha256"])
            or not isinstance(row["qualitative_signature"],str)
            or not _SHA64.fullmatch(row["qualitative_signature"])
            or not isinstance(row["review_pr_url"],str)
            or not _REVIEW_PR.fullmatch(row["review_pr_url"])
            or row["independent_legacy_semantic_review"] is not True
            or row["source_provenance_review"] is not True
            or not isinstance(row["rationale"],str) or len(row["rationale"])<50):
            raise IntakeError("independent reviewed SHA permit malformed")
        pair=(row["candidate_id"],row["candidate_path"])
        if pair in seen:
            raise IntakeError("duplicated review admission key")
        seen.add(pair)
    permits=[row for row in approved if row["candidate_path"]==candidate_relative
             or row["candidate_id"]==ident]
    if len(permits)>1:
        raise IntakeError("ambiguous reviewed candidate approval")
    permit=permits[0] if permits else None
    # Exact structural alias of ANY fixed or generated factory candidate
    # cannot be papered over by a self-asserted independent-review entry.
    if ident in FACTORY_SPECS:
        status="REJECT_DUPLICATE_EXECUTABLE_ID"
    elif matches:
        status="REJECT_DUPLICATE_EXECUTABLE_TOPOLOGY"
    elif permit is None:
        status="REVIEW_REQUIRED_NO_SEPARATE_APPROVAL"
    elif (permit["candidate_path"]!=candidate_relative
          or permit["candidate_id"]!=ident
          or permit["candidate_sha256"]!=rawsha
          or permit["qualitative_signature"]!=signature):
        status="REJECT_STALE_OR_MISMATCHED_APPROVAL"
    else:
        status="APPROVED_FOR_RESEARCH_SIMULATION_ONLY"
    return {
        "schema":SCHEMA,
        "candidate_id":ident,
        "candidate_path":candidate_relative,
        "candidate_sha256":rawsha,
        "original_factory_contract_digest":spec["contract_digest"],
        "qualitative_signature":signature,
        "matching_existing_executable_ids":matches,
        "status":status,
        "review_pr_url":permit["review_pr_url"] if permit else None,
        "global_economic_semantic_novelty_proven":False,
        "automatic_dispatch":False,
        "strategy_proven_profitable":False,
        "paper_eligible":False,
        "live_enabled":False,
        "orders":0,
    }


def evaluate_approved(
    root:Path,candidate_relative:str,archive:Path,
    warmup_utc:str,start_utc:str,end_exclusive_utc:str,
)->dict[str,Any]:
    allowlist=_load_json_strict(root/DEFAULT_ALLOWLIST,MAX_ALLOWLIST_BYTES)
    row=inspect_candidate(root,candidate_relative,allowlist)
    if row["status"]!="APPROVED_FOR_RESEARCH_SIMULATION_ONLY":
        raise IntakeError("unreviewed, duplicate or stale strategy contract cannot run: "+row["status"])
    try:
        warm=pd.Timestamp(warmup_utc)
        start=pd.Timestamp(start_utc)
        end=pd.Timestamp(end_exclusive_utc)
    except (ValueError,TypeError) as exc:
        raise IntakeError("invalid source research time window") from exc
    if (any(x.tzinfo is None or x.utcoffset().total_seconds()!=0
            for x in (warm,start,end))
        or not warm<start<end
        or (end-warm)>pd.Timedelta(days=MAX_WINDOW_DAYS)
        or (start-warm)<pd.Timedelta(days=25)
        or (end-start)<pd.Timedelta(days=30)
        or any(x.value%(900_000*1_000_000)!=0 for x in (warm,start,end))):
        raise IntakeError("research window must be UTC, 15m-aligned, 25d warmup, >=30d trial, <=150d total")
    # Actual physical source byte hashes are checked before ANY features.
    locked=verify_pinned_market_files(archive)
    frames={}
    for sym in SYMBOLS:
        frames[sym]={}
        for tf in ("minute15","hour1","hour4"):
            whole=load_verified_archive_frame(archive,sym,tf)
            original_ts=pd.to_datetime(whole["timestamp"],utc=True)
            scoped=whole.loc[(original_ts>=warm)&(original_ts<end)]
            frames[sym][tf]=scoped.reset_index(drop=True)
            del whole
    features={}
    for sym in SYMBOLS:
        other=next(s for s in SYMBOLS if s!=sym)
        features[sym]=build_features(frames[sym],
                                     peer_15m=frames[other]["minute15"])
    specs=load_factory_contract(root/candidate_relative)
    spec=specs[row["candidate_id"]]
    source={}
    signal={}
    for sym in SYMBOLS:
        f=features[sym]
        ix=(f["decision_at"]>=start)&(f["decision_at"]<end)
        source[sym]=f.loc[ix].reset_index(drop=True)
        signal[sym]=factory_signal(
            source[sym],row["candidate_id"],specs=specs,
            expected_contract_digest=spec["contract_digest"]
        ) & (
            np.isfinite(source[sym]["atr"].to_numpy(dtype=float))
            & (source[sym]["atr"].to_numpy(dtype=float)>0)
        )
    replay=sidecar_summary(source,signal)
    evidence={
        **replay,
        "source_scope":"SIX_PHYSICAL_SHA_ATTESTED_ORIGINAL_BYBIT_SPOT",
        "exact_market_file_sha256":locked,
        "source_canonical_semantic_sha256":ARCHIVE_SHA256,
        "readiness":row,
        "warmup_utc":warm.isoformat(),
        "evaluation_start_utc":start.isoformat(),
        "evaluation_end_exclusive_utc":end.isoformat(),
        "raw_closed_bar_signals":{sym:int(signal[sym].sum()) for sym in SYMBOLS},
        "historical_source_already_inspected":True,
        "independent_untouched_future_holdout":False,
        "demo_eligible":False,"paper_eligible":False,"live_enabled":False,
        "real_exchange_orders":0,
    }
    evidence["result_digest"]=_digest({k:v for k,v in evidence.items()
                                        if k!="result_digest"})
    return evidence


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-relative",required=True)
    ap.add_argument("--archive-root",type=Path,required=True)
    ap.add_argument("--warmup-utc",required=True)
    ap.add_argument("--start-utc",required=True)
    ap.add_argument("--end-exclusive-utc",required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    result=evaluate_approved(
        ROOT,args.candidate_relative,args.archive_root,
        args.warmup_utc,args.start_utc,args.end_exclusive_utc
    )
    write_once(args.output,result)
    print(json.dumps({
        "readiness":result["readiness"]["status"],
        "candidate_id":result["readiness"]["candidate_id"],
        "result_digest":result["result_digest"],
        "partitions":{segment:{cost:{
            "trades":out["trades"],"net_pnl_usdt":out["net_pnl_usdt"]
        } for cost,out in profiles.items()}
        for segment,profiles in result["partitions"].items()},
        "paper_eligible":False,"live_enabled":False,"real_exchange_orders":0,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
