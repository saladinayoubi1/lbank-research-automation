"""V100 auditable coarse/fine relationship ledger, NOT wave-count promotion.

Uses the two independent V99 causal close-only streams and classifies
EVERY fine swing by its center, with exact boundaries, outside points and
late-confirmed inside points never pruned. No Elliott degree is certified.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from bisect import bisect_left
from collections import Counter
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path

from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v93_recursive_proof import proof_v93 as v93
from research.elliott_v99_causal_scale import scale_v99 as v99

ROOT=Path(tempfile.gettempdir())/"nexus-elliott-v100-context"
V99_REL="docs/evidence/elliott-v99-causal-scale-20261017/V99_CAUSAL_MULTISCALE_CLOSE_DIAGNOSTIC.json"
V99_SHA="69a88a3e101d53ea4d84b1bad999de9482cf153fb6a9c1674cf0f40a604666a2"
V99_COMMIT="9531efb0bdbd851e39d39322d8f37f40f92d44d6"
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
ORDER_ADAPTER=None
V52_UNCHANGED=True
CERTIFIED_MARKET_WAVES=0


def _serial(e:v99.ObservedSwing)->list:
    if type(e) is not v99.ObservedSwing:
        raise ValueError("only typed source-observed swing accepted")
    if (e.kind not in ("HIGH","LOW") or
        type(e.center_ms) is not int or type(e.confirmed_ms) is not int or
        type(e.center_index) is not int or type(e.confirmed_index) is not int or
        e.confirmed_ms<=e.center_ms or
        e.confirmed_index<=e.center_index or
        type(e.center_close) is not Decimal or
        type(e.confirm_close) is not Decimal or
        not e.center_close.is_finite() or
        not e.confirm_close.is_finite() or
        e.center_close<=0 or e.confirm_close<=0):
        raise ValueError("invalid unconfirmed swing")
    return [e.kind,e.center_ms,e.confirmed_ms,str(e.center_close),
            str(e.confirm_close),e.center_index,e.confirmed_index]


def digest_events(events:list[v99.ObservedSwing])->str:
    return hashlib.sha256(json.dumps([_serial(e) for e in events],
                separators=(",",":"),ensure_ascii=False).encode()).hexdigest()


def causal_relationships(
    fine:list[v99.ObservedSwing],coarse:list[v99.ObservedSwing],asof:int,
)->dict:
    """Exhaustive disjoint fine-event *center-position* buckets.

    Coarse intervals are descriptive, not Elliott wave degrees. Every
    fine event is assigned exactly once: strict interior, shared center,
    or outside. A center-interior fine event confirmed after that interval's
    right coarse confirmation stays in the ledger as LATE, not deleted.
    Both full streams must already be known no later than supplied asof.
    """
    if type(asof) is not int or asof%v99.MINUTE:
        raise ValueError("complete aligned cutoff required")
    if (type(fine) is not list or type(coarse) is not list or len(coarse)<2):
        raise ValueError("two independent ordered scale streams required")
    shared_origin=None
    for tag,events in (("fine",fine),("coarse",coarse)):
        for i,e in enumerate(events):
            _serial(e)
            origin=e.center_ms-e.center_index*v99.MINUTE
            if (origin%v99.MINUTE or
                e.confirmed_ms!=origin+(e.confirmed_index+1)*v99.MINUTE or
                (shared_origin is not None and origin!=shared_origin)):
                raise ValueError(tag+" event index/time disagrees with source")
            shared_origin=origin
            if e.confirmed_ms>asof:
                raise ValueError(tag+" future confirmation or unseen source")
            if i and (events[i-1].center_ms>=e.center_ms or
                      events[i-1].confirmed_ms>=e.confirmed_ms or
                      events[i-1].kind==e.kind):
                raise ValueError(tag+" nonchronological or relabeled swings")
    centers=[e.center_ms for e in coarse]
    buckets=[[] for _ in range(len(coarse)-1)]
    boundary=[]
    outside=[]
    for e in fine:
        k=bisect_left(centers,e.center_ms)
        if k<len(coarse) and centers[k]==e.center_ms:
            boundary.append(e)
        elif 0<k<len(coarse):
            buckets[k-1].append(e)
        else:
            outside.append(e)
    if sum(map(len,buckets))+len(boundary)+len(outside)!=len(fine):
        raise ValueError("failed to account for all independent fine observations")
    intervals=[]
    statuses=Counter()
    for i,(left,right,events) in enumerate(zip(coarse,coarse[1:],buckets)):
        cutoff=right.confirmed_ms
        if left.confirmed_ms>cutoff or right.center_ms<=left.center_ms:
            raise ValueError("future coarse boundary or overlapping centers")
        known=[e for e in events if e.confirmed_ms<=cutoff]
        late=[e for e in events if e.confirmed_ms>cutoff]
        expected_direction="down" if left.kind=="HIGH" else "up"
        status=("LATE_FINE_CONFIRMATION_ABSTAIN" if late else
                "OBSERVATIONAL_POSITION_ONLY_NO_WAVE_PROOF")
        statuses[status]+=1
        intervals.append({
            "index":i,
            "left_center_ms":left.center_ms,
            "right_center_ms":right.center_ms,
            "left_confirmed_ms":left.confirmed_ms,
            "right_confirmed_ms":cutoff,
            "coarse_motion_label":expected_direction,
            "all_fine_center_interior_count":len(events),
            "fine_known_by_coarse_right_confirmation":len(known),
            "fine_confirmed_too_late_count":len(late),
            "fine_unpruned_event_sha256":digest_events(events),
            "late_event_sha256":digest_events(late),
            "fine_labels_by_center":[e.kind for e in events],
            "has_left_neighbor_context":i>0,
            "has_right_neighbor_context_at_cutoff":(
                i+2<len(coarse) and coarse[i+2].confirmed_ms<=cutoff),
            "interpretation":status,
            "elliott_degree_certified":False,
            "entry_signal":False,
            "paper_eligible":False,
        })
    if sum(x["all_fine_center_interior_count"] for x in intervals
           )+len(boundary)+len(outside)!=len(fine):
        raise ValueError("lost fine center during interval assignment")
    return {
        "status":"COMPLETE_PHYSICAL_CAUSAL_CROSS_SCALE_POSITION_LEDGER_NOT_ELLIOTT",
        "decision_asof_ms":asof,
        "complete_fine_swings":len(fine),
        "complete_coarse_swings":len(coarse),
        "complete_coarse_intervals":len(intervals),
        "all_original_fine_events_sha256":digest_events(fine),
        "all_original_coarse_events_sha256":digest_events(coarse),
        "fine_center_on_coarse_boundary":len(boundary),
        "fine_boundary_digest":digest_events(boundary),
        "fine_center_outside_closed_coarse_range":len(outside),
        "fine_outside_digest":digest_events(outside),
        "all_fine_exactly_accounted":True,
        "non_deployed_rejection_counts":dict(statuses),
        "intervals":intervals,
        "wave_degree_proven":False,
        "pattern_position_proven":False,
        "any_trade_admission":False,
        "live_enabled":False,
    }


def audit_old_july_cross_scale()->dict:
    """No new-price sample, no economic result, no retrospective rule tuning."""
    old=v93.immutable_receipt(V99_REL,V99_SHA,V99_COMMIT,
        "nexus.elliott-v99-causal-close-multiscale-diagnostic.v1")
    manifest,receipt=v90.verify_locked_receipts()
    if (old["v89_source_receipt_sha256"]!=v90.SOURCE_RECEIPT_SHA or
        old["volatility_window_prior_closed_1m_returns"]!=v99.LOOKBACK_CLOSED_RETURNS or
        old["scale_multipliers"]!=["3","8"] or
        old["signals"]!=0 or old["orders"]!=0):
        raise ValueError("V99 source lineage, frozen scale or no-trade flag changed")
    report={
        "schema":"nexus.elliott-v100-causal-cross-scale-position-ledger.v1",
        "recorded_utc":datetime.now(timezone.utc).isoformat(),
        "retrospective_preinspected_july_2024_only":True,
        "v99_source_receipt_sha256":V99_SHA,
        "v99_git_commit":V99_COMMIT,
        "v89_official_source_sha256":v90.SOURCE_RECEIPT_SHA,
        "never_discarded_fine_swing":True,
        "scales_are_independent_not_forced_nested":True,
        "coarse_centers_not_source_certified_elliott_degree":True,
        "right_confirmed_by_observation_not_anticipation":True,
        "no_posthoc_parameter_selection":True,
        "paper_eligible":False,"entry_signal":False,"live_enabled":False,
        "orders":0,"pnl":None,"certified_elliott_patterns":0,
        "frozen_v52_unchanged":True,
        "symbols":{},
    }
    for symbol in ("BTCUSDT","ETHUSDT"):
        bars=v99.load_verified_closes(symbol,manifest,receipt)
        fine=v99.observe_scale(bars,v99.TRAILING_MEDIAN_MULTIPLIERS[0])
        coarse=v99.observe_scale(bars,v99.TRAILING_MEDIAN_MULTIPLIERS[1])
        expected=old["symbols"][symbol]
        for value,stream in (("3",fine),("8",coarse)):
            if (v99.summarize(stream,v90.SPLIT_MS)["source_validated_event_digest"]
                !=expected["scales"][value]["source_validated_event_digest"]):
                raise ValueError("locked V99 original swing stream changed")
        ledger=causal_relationships(fine,coarse,v90.END_MS)
        week_a_fine=v99.observe_scale(bars,v99.TRAILING_MEDIAN_MULTIPLIERS[0],v90.SPLIT_MS)
        week_a_coarse=v99.observe_scale(bars,v99.TRAILING_MEDIAN_MULTIPLIERS[1],v90.SPLIT_MS)
        if (week_a_fine!=[e for e in fine if e.confirmed_ms<=v90.SPLIT_MS]
            or week_a_coarse!=[e for e in coarse if e.confirmed_ms<=v90.SPLIT_MS]):
            raise ValueError("completed Week-A source event changed after Week-B")
        # Any complete coarse interval known by Week-A may only use interior
        # fine evidence available by that same individual right confirmation.
        for x in ledger["intervals"]:
            if x["right_confirmed_ms"]<=v90.SPLIT_MS and (
                x["fine_confirmed_too_late_count"]>0):
                # A late event remains visible in full-month hindsight, but
                # it MUST NOT be treated as observable at the coarse cutoff.
                if x["interpretation"]!="LATE_FINE_CONFIRMATION_ABSTAIN":
                    raise ValueError("late fine wave mistakenly counted as observed")
        report["symbols"][symbol]=ledger
    ROOT.mkdir(parents=True,exist_ok=True)
    dest=ROOT/"V100_CAUSAL_CROSS_SCALE_POSITION_LEDGER.json"
    serialized=(json.dumps(report,indent=2,sort_keys=True,ensure_ascii=False)+"\n").encode()
    if dest.exists():
        previous=json.loads(dest.read_bytes())
        proposed=json.loads(serialized)
        previous.pop("recorded_utc",None)
        proposed.pop("recorded_utc",None)
        if previous!=proposed:
            raise ValueError("V100 immutable retrospective observations differ")
        serialized=dest.read_bytes()
    else:
        dest.write_bytes(serialized)
    print(json.dumps({
        "status":"V100_FULL_FINE_SWING_ACCOUNTABILITY_NO_ELLIOTT_PATTERN_PROOF",
        "sha256":hashlib.sha256(serialized).hexdigest(),
        "by_symbol":{k:{
            "fine":v["complete_fine_swings"],
            "coarse":v["complete_coarse_swings"],
            "intervals":v["complete_coarse_intervals"],
            "fine_boundaries":v["fine_center_on_coarse_boundary"],
            "fine_outside":v["fine_center_outside_closed_coarse_range"],
            "late_interval_count":v["non_deployed_rejection_counts"].get(
                "LATE_FINE_CONFIRMATION_ABSTAIN",0),
            "all_fine_accounted":v["all_fine_exactly_accounted"],
        } for k,v in report["symbols"].items()},
        "elliott_certificates":0,
        "orders":0,
    },indent=2))
    return report


if __name__=="__main__":
    audit_old_july_cross_scale()
