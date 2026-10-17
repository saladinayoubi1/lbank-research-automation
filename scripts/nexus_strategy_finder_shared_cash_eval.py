"""Explicit offline strategy-finder -> single BTC/ETH 500-USDT cash evaluator.

Uses the EXISTING NEXUS original reviewed mechanism grammar and independently
verified replay archive loader, no user-programmable Python. Does not alter the
existing standalone 10k-per-symbol research workflow, closed history, terminal
rotation cursor, current Demo, Live flag, or qualification. This command makes
old accounting discrepancy observable for review; it does not manufacture edge.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from nexus_composite_strategy_research import (
    FRONTIER_CONFIGS,CONFIGS,ALL_MECHANISMS,
    SCHEMA as COMPOSITE_SCHEMA,digest as composite_digest,
    signal_for,_load_frontier_features
)
from nexus_demo_archive_replay import ARCHIVE_SHA256
from research.strategy_finder_shared_cash_physical import (
    sidecar_summary, SharedCashDiagnosticError, SYMBOLS, _digest
)


class CandidateBridgeError(ValueError):
    pass


def reviewed_config(mechanism:str,expected_fingerprint:str)->dict[str,Any]:
    """One source-bound REVIEWED config, not arbitrary generated script."""
    if (type(mechanism) is not str or type(expected_fingerprint) is not str
        or len(expected_fingerprint)!=64 or any(c not in "0123456789abcdef"
                                            for c in expected_fingerprint)):
        raise CandidateBridgeError("exact reviewed mechanism and sha256 config required")
    matches=[row for row in (*CONFIGS,*FRONTIER_CONFIGS)
             if row["mechanism"]==mechanism]
    if not matches or mechanism not in ALL_MECHANISMS:
        raise CandidateBridgeError("unreviewed candidate cannot enter research replay")
    candidates=[{**row,"fingerprint":composite_digest({
        "config":row,"dataset":ARCHIVE_SHA256,"contract":COMPOSITE_SCHEMA,
    })} for row in matches]
    matched=[c for c in candidates if c["fingerprint"]==expected_fingerprint]
    if len(matched)!=1:
        raise CandidateBridgeError("reviewed source/config exact fingerprint mismatch")
    return matched[0]


def evaluate_readonly(
    archive_root:Path,mechanism:str,expected_fingerprint:str,
    source_sha256:str
)->dict[str,Any]:
    """No order credentials, no download, no automatic ranking/promotion."""
    if (not isinstance(archive_root,Path) or archive_root.is_symlink()
        or not archive_root.is_dir() or source_sha256!=ARCHIVE_SHA256):
        raise CandidateBridgeError("immutable verified Bybit research archive required")
    candidate=reviewed_config(mechanism,expected_fingerprint)
    # In the original system this independently hashes and validates all
    # minute15/hour1/hour4 exact archive inputs, then point-in-time merges
    # only completed higher-timeframe and current/lagged peer observations.
    features=_load_frontier_features(archive_root)
    if set(features)!=set(SYMBOLS):
        raise CandidateBridgeError("both original peer source features required")
    signals={symbol:np.asarray(signal_for(features[symbol],candidate),dtype=bool)
             for symbol in SYMBOLS}
    result=sidecar_summary(features,signals)
    result.update({
        "selected_reviewed_mechanism":mechanism,
        "selected_exact_config_fingerprint":expected_fingerprint,
        "research_source_archive_sha256":source_sha256,
        "source_authentication":"EXISTING_VERIFIED_ARCHIVE_LOADER_PLUS_EXACT_SHA",
        "source_history_preinspected_not_independent_holdout":True,
        "qualification":"DIAGNOSTIC_ONLY_NO_AUTOMATIC_DEMO_PROMOTION",
        "paper_eligible":False,"live_enabled":False,"orders":0,
    })
    result["result_digest"]=_digest({k:v for k,v in result.items() if k!="result_digest"})
    return result


def write_once(path:Path,obj:dict[str,Any])->None:
    if not isinstance(path,Path) or path.is_symlink() or path.exists():
        raise CandidateBridgeError("write-once new research evidence output required")
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf8",newline="\n") as f:
        json.dump(obj,f,sort_keys=True,indent=2,allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp,path)


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive-root",type=Path,required=True)
    ap.add_argument("--mechanism",required=True)
    ap.add_argument("--exact-fingerprint",required=True)
    ap.add_argument("--source-archive-sha256",required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    evidence=evaluate_readonly(args.archive_root,args.mechanism,
                               args.exact_fingerprint,args.source_archive_sha256)
    write_once(args.output,evidence)
    print(json.dumps({
        "mechanism":args.mechanism,
        "exact_fingerprint":args.exact_fingerprint,
        "account":"500_USDT_one_shared_spot_BTC_ETH",
        "partition_summary":{
            p:{profile:{"trades":v["trades"],"net_pnl_usdt":v["net_pnl_usdt"]}
               for profile,v in profiles.items()}
            for p,profiles in evidence["partitions"].items()},
        "qualification":"DIAGNOSTIC_ONLY_NO_AUTOMATIC_DEMO_PROMOTION",
        "paper_eligible":False,"live_enabled":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
