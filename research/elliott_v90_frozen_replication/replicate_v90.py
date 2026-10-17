"""V90 locked July 2024 Elliott structural replication; NO trades.

Never modify V88 rule definitions or fit to either week. Reuse certified
V82/V83/V85/V86/V87 code and retain all source-visible rejection reasons.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import zipfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v82_causal_degree_observer.observer_v82 import (
    MINUTE_MS, Minute, Witness, digest, observe, validate_minutes,
)
from research.elliott_v83_impulse_geometry.geometry_v83 import check_candidate
from research.elliott_v85_diagonal_scope.diagonal_scope_v85 import (
    evaluate_diagonal_preconditions,
)
from research.elliott_v86_diagonal_inner_witness.inner_witness_v86 import inspect_candidate
from research.elliott_v87_correction_witness.correction_v87 import assess_correction
from research.elliott_v89_source_intake import intake_v89 as v89

RESEARCH_ONLY = True
ENTRY_SIGNAL = False
PAPER_ELIGIBLE = False
LIVE_ENABLED = False
V52_UNCHANGED = True
SOURCE_RECEIPT_SHA = "e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df"
V89_HEAD = "7f61fa134ecd1e937f3aa9a242820f5f3e99d322"
ROOT = Path(r"E:\NEXUS-QA\elliott-v90-replication-20261017")
END_MS = 1721001600000
START_MS = 1719792000000
SPLIT_MS = 1720396800000


def verify_locked_receipts() -> tuple[dict,dict]:
    locked=v89.locked_manifest()
    v89.verify_committed_lock()
    raw=v89.RECEIPT.read_bytes()
    if digest(raw)!=SOURCE_RECEIPT_SHA:
        raise ValueError("source receipt changed after V89")
    repo=v89.v88.REPOSITORY_ROOT
    rel="docs/evidence/elliott-v89-official-source-20261017/V89_SOURCE_INTAKE.json"
    historic=subprocess.run(["git","show",V89_HEAD+":"+rel],
                            cwd=repo,capture_output=True,check=True).stdout
    if historic!=raw:
        raise ValueError("V89 committed receipt bytes do not match Laptop2")
    subprocess.run(["git","merge-base","--is-ancestor",V89_HEAD,"HEAD"],
                   cwd=repo,capture_output=True,check=True)
    receipt=json.loads(raw)
    if (receipt.get("status")!="VERIFIED_ALL_28_OFFICIAL_DAILY_FILES"
            or receipt["preregistration_bytes_sha256"]!=v89.PREREG_HASH):
        raise ValueError("unauthenticated V89 source population")
    return locked,receipt


def _parse_verified_source(symbol: str, lock: dict,receipt: dict) -> list[Minute]:
    """Reopen 14 official daily ZIPs; verify each against V89 and CHECKSUM."""
    source=[]
    expected=[x for x in lock["scheduled_inputs"] if x["symbol"]==symbol]
    prior={x["name"]:x for x in receipt["archives"]}
    if len(expected)!=14:
        raise ValueError("missing frozen days")
    for entry in expected:
        z=v89.BASE/entry["zip_file"]
        check=v89.BASE/entry["official_checksum_file"]
        if not z.is_file() or not check.is_file():
            raise ValueError("cached official source absent")
        archived=z.read_bytes()
        observed=v89.verify_archive(entry,archived,check.read_bytes())
        if any(observed[k]!=value for k,value in prior[entry["zip_file"]].items()
               if k in observed):
            raise ValueError("V89 official source receipt mismatch")
        with zipfile.ZipFile(io.BytesIO(archived)) as bundle:
            data=bundle.read(entry["csv_member"])
        for line in csv.reader(io.StringIO(data.decode("utf-8-sig"))):
            source.append(Minute(int(line[0]),Decimal(line[2]),Decimal(line[3])))
    if (len(source)!=20160 or source[0].ms!=START_MS
            or source[-1].ms+MINUTE_MS!=END_MS):
        raise ValueError("invalid 14-day source range")
    validate_minutes(source)
    return source


def split_for(first_observable_ms: int) -> str:
    """Closed final UTC candle is observable exactly at July 15 00:00."""
    if type(first_observable_ms) is not int:
        raise ValueError("typed first-observable instant required")
    if START_MS<=first_observable_ms<SPLIT_MS:
        return "A"
    if SPLIT_MS<=first_observable_ms<=END_MS:
        return "B"
    raise ValueError("candidate outside original 14-day observable period")


def matching_children(a: Witness,b: Witness,child: list[Witness],
                      cutoff: int) -> list[Witness]:
    return [w for w in child if a.center_ms<w.center_ms<b.center_ms
            and w.confirmed_ms<=cutoff]


def assess_symbol(symbol: str,lock: dict,receipt: dict) -> dict:
    minutes=_parse_verified_source(symbol,lock,receipt)
    observed=observe(minutes,END_MS)
    parents=[Witness(**w) for w in observed["parent_witnesses"]]
    children=[Witness(**w) for w in observed["child_witnesses"]]
    legs=observed["leg_assessments"]
    if len(parents)-1!=len(legs):
        raise ValueError("source observer parent/interval cardinality changed")
    total=Counter()
    per_split={"A":Counter(),"B":Counter()}
    motives=[]
    corrections=[]
    intervals=[]
    for a,b,diagnostic in zip(parents,parents[1:],legs):
        asof=diagnostic["hypothesis_first_seen_ms"]
        if asof!=max(a.confirmed_ms,b.confirmed_ms):
            raise ValueError("V82 first observable time diverged")
        if (diagnostic["parent_left_center_ms"]!=a.center_ms
            or diagnostic["parent_right_center_ms"]!=b.center_ms):
            raise ValueError("V82 source parent interval misassigned")
        if a.center_ms>=b.center_ms or asof>END_MS:
            raise ValueError("future/ill-formed interval")
        middle=matching_children(a,b,children,asof)
        if ([w.center_ms for w in middle]!=diagnostic["all_child_centers_ms"]
            or [w.confirmed_ms for w in middle]!=diagnostic["all_child_confirmation_ms"]):
            raise ValueError("source witness population was retrospectively changed")
        week=split_for(asof)
        counts=(total,per_split[week])
        for tally in counts:
            tally["parent_intervals_observed"]+=1
            tally["child_pivots_inside_all_parent_intervals"]+=len(middle)
            tally["reason_"+diagnostic["reason"]]+=1
        case={
            "first_observable_ms":asof,
            "week":week,
            "parent_left_center_ms":a.center_ms,
            "parent_right_center_ms":b.center_ms,
            "parent_left_confirmed_ms":a.confirmed_ms,
            "parent_right_confirmed_ms":b.confirmed_ms,
            "child_count":len(middle),
            "child_centers_ms":[x.center_ms for x in middle],
            "child_confirmed_ms":[x.confirmed_ms for x in middle],
            "v82_reason":diagnostic["reason"],
            "motive_five_leg_skeleton":diagnostic["hypotheses"]["MOTIVE_FIVE_LEG_SKELETON"],
            "correction_three_leg_skeleton":diagnostic["hypotheses"]["CORRECTION_THREE_LEG_SKELETON"],
        }
        if case["motive_five_leg_skeleton"]:
            for tally in counts:
                tally["motive_skeletons"]+=1
            hard=check_candidate(a,b,middle,minutes,asof)
            if (hard["first_observable_ms"]!=asof
                or hard.get("entry_signal") is not False
                or hard.get("paper_eligible") is not False):
                raise ValueError("V83 motive hard-geometry changed causal contract")
            diagonal=evaluate_diagonal_preconditions(hard)
            wrapped={**hard,"diagonal_precondition_state":diagonal["state"]}
            degree=inspect_candidate(wrapped,minutes)
            if degree["asof_ms"]!=asof:
                raise ValueError("V86 inner witness as-of mismatch")
            case["v83_motive_state"]=hard["state"]
            case["v85_diagonal_state"]=diagonal["state"]
            case["v86_inner_degree_state"]=degree["state"]
            case["v86_inner_counts"]=degree["per_leg_inner_counts"]
            case["v83_rule_failures"]=hard["rule_failures"]
            case["v83_physical_failures"]=hard["physical_failures"]
            case["v85_diagonal_veto_reasons"]=diagonal["hard_veto_reasons"]
            for tally in counts:
                tally["v83_"+hard["state"]]+=1
                tally["v85_"+diagonal["state"]]+=1
                tally["v86_"+degree["state"]]+=1
                for reason in hard["rule_failures"]+hard["physical_failures"]:
                    tally["hard_fail_"+reason]+=1
                for reason in diagonal["hard_veto_reasons"]:
                    tally["diagonal_veto_"+reason]+=1
            motives.append({
                "first_observable_ms":asof,"week":week,
                "source_parent_centers_ms":[a.center_ms,b.center_ms],
                "v83":hard,"v85":diagonal,"v86":degree,
            })
        if case["correction_three_leg_skeleton"]:
            for tally in counts:
                tally["correction_skeletons"]+=1
            correction=assess_correction([a,*middle,b],minutes,asof)
            if (correction["asof_ms"]!=asof
                or correction.get("entry_signal") is not False
                or correction.get("paper_eligible") is not False):
                raise ValueError("V87 correction grammar changed causal contract")
            case["v87_correction_state"]=correction["state"]
            case["v87_inner_counts"]=correction["inner_counts_ABC"]
            for tally in counts:
                tally["v87_"+correction["state"]]+=1
            corrections.append({
                "first_observable_ms":asof,"week":week,
                "source_parent_centers_ms":[a.center_ms,b.center_ms],
                "v87":correction,
            })
        intervals.append(case)
    if total["parent_intervals_observed"]!=len(parents)-1:
        raise ValueError("missing one or more parent intervals")
    if (per_split["A"]["parent_intervals_observed"]
        +per_split["B"]["parent_intervals_observed"]!=len(intervals)):
        raise ValueError("week split does not exhaust whole source universe")
    return {
        "symbol":symbol,
        "total_source_minutes":len(minutes),
        "physical_source_first_open_ms":minutes[0].ms,
        "physical_source_end_exclusive_ms":minutes[-1].ms+MINUTE_MS,
        "parent_15m_pivot_witnesses":len(parents),
        "child_3m_pivot_witnesses":len(children),
        "primitive_rejections":observed["raw_rejection_counts"],
        "V82_leg_summary":observed["leg_summary"],
        "all_intervals":intervals,
        "five_leg_candidate_details":motives,
        "three_leg_candidate_details":corrections,
        "all_weeks_counts":dict(total),
        "week_A_counts":dict(per_split["A"]),
        "week_B_counts":dict(per_split["B"]),
        "wave_pattern_certificates":0,
        "new_trade_signals":0,
        "net_pnl":None,
    }


def full_replication() -> dict:
    lock,receipt=verify_locked_receipts()
    if (lock["period"]["first_open_utc"]!="2024-07-01T00:00:00Z"
        or lock["period"]["exclusive_end_utc"]!="2024-07-15T00:00:00Z"
        or lock["frozen_recognition"]["zigzag_535_inner_1m_pivot_counts_ABC"]!=[4,2,4]
        or lock["frozen_recognition"]["flat_335_inner_1m_pivot_counts_ABC"]!=[2,2,4]):
        raise ValueError("locked source or frozen classifier contract differs")
    symbols={}
    for symbol in ("BTCUSDT","ETHUSDT"):
        symbols[symbol]=assess_symbol(symbol,lock,receipt)
    output={
        "schema":"nexus.elliott-v90-locked-independent-structural-replication.v1",
        "observed_utc":datetime.now(timezone.utc).isoformat(),
        "study_status":"HISTORICAL_REPLICATION_OF_FIXED_RULES_NOT_FORECAST",
        "source_period_utc":["2024-07-01T00:00:00Z","2024-07-15T00:00:00Z"],
        "split_A_end_exclusive_ms":SPLIT_MS,
        "split_B_last_observable_inclusive_ms":END_MS,
        "boundary_policy":"left edge no synthetic warmup; final July14 close at July15 00:00 included in B",
        "v88_preregistration_sha256":v89.PREREG_HASH,
        "v88_preregistration_commit":v89.EXPECTED_LOCK_COMMIT,
        "v89_source_receipt_sha256":SOURCE_RECEIPT_SHA,
        "v89_source_receipt_commit":V89_HEAD,
        "raw_market_archives_stored_in_git":False,
        "observer_versions":["V82","V83","V85","V86","V87"],
        "classifier_thresholds_modified":False,
        "historical_not_prospective":True,
        "frozen_V52_untouched":True,
        "signal_count":0,
        "valid_full_recursive_elliott_counts":0,
        "paper_eligible":False,
        "live_enabled":False,
        "entry_signal":False,
        "net_pnl":None,
        "symbols":symbols,
    }
    ROOT.mkdir(parents=True,exist_ok=True)
    file=ROOT/"V90_REPLICATION_AUDIT.json"
    # Raw observation is immutable after first write; no silent rewriting.
    encoded=(json.dumps(output,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode("utf8")
    if file.exists():
        existing=json.loads(file.read_bytes())
        existing.pop("observed_utc",None)
        check=json.loads(encoded)
        check.pop("observed_utc",None)
        if existing!=check:
            raise ValueError("V90 already observed; cannot overwrite outcome")
        encoded=file.read_bytes()
    else:
        file.write_bytes(encoded)
    print(json.dumps({
        "schema":output["schema"],
        "evidence_sha256":hashlib.sha256(encoded).hexdigest(),
        "receipt_file":str(file),
        "symbols":{
            symbol:{
                "total_parent_intervals":info["all_weeks_counts"]["parent_intervals_observed"],
                "total_parent_pivots":info["parent_15m_pivot_witnesses"],
                "total_child_pivots":info["child_3m_pivot_witnesses"],
                "total_motive_skeletons":info["all_weeks_counts"].get("motive_skeletons",0),
                "total_correction_skeletons":info["all_weeks_counts"].get("correction_skeletons",0),
                "week_A_counts":info["week_A_counts"],
                "week_B_counts":info["week_B_counts"],
                "new_trading_signals":0,
            } for symbol,info in symbols.items()
        },
        "proven_pattern_or_trade":False,
    },indent=2))
    return output


if __name__=="__main__":
    full_replication()
