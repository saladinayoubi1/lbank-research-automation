"""V99 source-authenticated close-only causal directional-change multiscale observer.

A deterministic RESEARCH HEURISTIC, not an Elliott degree classifier,
a signal generator, retrospective economic optimization or a live feed.
Levels 3 and 8 times trailing 60-minute median |close differences|, with
0.03 percent past-price floor, are arbitrary predeclared future-test
hypotheses, never chosen using historical P&L or old Elliott labels.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import statistics
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v93_recursive_proof import proof_v93 as v93
from research.elliott_v98_correction_inner import inner_v98 as v98

ROOT=Path(tempfile.gettempdir())/"nexus-elliott-v99-scale"
V98_REL="docs/evidence/elliott-v98-abc-inner-20261017/V98_ABC_SOURCE_INNER_GEOMETRY.json"
V98_SHA="dd6dd322ac84c80559dadc54f439ded417f1befd24b0c611310a06e4b080f490"
V98_COMMIT="545e705a710fad5ec185c334a66216bdbf5c76f8"
LOOKBACK_CLOSED_RETURNS=60
TRAILING_MEDIAN_MULTIPLIERS=(Decimal("3"),Decimal("8"))
ABSOLUTE_PAST_PRICE_FLOOR=Decimal("0.0003")
MINUTE=60_000
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ORDER_ADAPTER=None
V52_UNCHANGED=True
HAS_CERTIFIED_ELLIOTT_DEGREE=False


@dataclass(frozen=True)
class CloseMinute:
    ms:int
    close:Decimal


@dataclass(frozen=True)
class ObservedSwing:
    kind:str
    center_ms:int
    confirmed_ms:int
    center_close:Decimal
    confirm_close:Decimal
    center_index:int
    confirmed_index:int


def validate_closed_prefix(bars:list[CloseMinute],asof:int|None=None)->list[CloseMinute]:
    if type(bars) is not list or len(bars)<LOOKBACK_CLOSED_RETURNS+4:
        raise ValueError("complete 1m warmup and subsequent prefix required")
    if asof is None:
        asof=bars[-1].ms+MINUTE
    if type(asof) is not int or asof%MINUTE:
        raise ValueError("unaligned as-of time")
    count,rem=divmod(asof-bars[0].ms,MINUTE)
    if rem or not LOOKBACK_CLOSED_RETURNS+4<=count<=len(bars):
        raise ValueError("unavailable completed 1m source prefix")
    source=bars[:count]
    for i,x in enumerate(source):
        if (type(x) is not CloseMinute or type(x.ms) is not int
            or type(x.close) is not Decimal or not x.close.is_finite()
            or x.close<=0 or x.ms!=source[0].ms+i*MINUTE):
            raise ValueError("invalid, nonchronological or physically gapped close")
    return source


def trailing_threshold(bars:list[CloseMinute], index:int,multiple:Decimal)->Decimal:
    """Reference only closes ending strictly before current decision bar."""
    if (type(index) is not int or index<LOOKBACK_CLOSED_RETURNS+1
        or index>=len(bars) or multiple not in TRAILING_MEDIAN_MULTIPLIERS):
        raise ValueError("out-of-bound threshold or unregistered scale")
    moves=[abs(bars[j].close-bars[j-1].close)
           for j in range(index-LOOKBACK_CLOSED_RETURNS,index)]
    return max(
        statistics.median(moves)*multiple,
        bars[index-1].close*ABSOLUTE_PAST_PRICE_FLOOR,
    )


def observe_scale(bars:list[CloseMinute],multiple:Decimal,
                  asof:int|None=None)->list[ObservedSwing]:
    """One-pass observable turning-point confirmations, no future revision.

    Every emitted swing is a previously observed CLOSE extreme, and the
    confirmation decision occurs at the first later *closed* minute crossing
    a lagging, pre-decision threshold. Different scales may disagree; do not
    force higher-level pivots to be nested or drop lower-level swings.
    """
    source=validate_closed_prefix(bars,asof)
    if multiple not in TRAILING_MEDIAN_MULTIPLIERS:
        raise ValueError("unregistered causal scale")
    direction="UNSET"
    extreme_index=LOOKBACK_CLOSED_RETURNS
    extreme=source[extreme_index].close
    events=[]
    for i in range(LOOKBACK_CLOSED_RETURNS+1,len(source)):
        now=source[i].close
        threshold=trailing_threshold(source,i,multiple)
        if direction=="UNSET":
            if now>=extreme+threshold:
                direction="UP"
                extreme=now
                extreme_index=i
            elif now<=extreme-threshold:
                direction="DOWN"
                extreme=now
                extreme_index=i
        elif direction=="UP":
            if now>extreme:
                extreme=now
                extreme_index=i
            elif now<=extreme-threshold:
                events.append(ObservedSwing(
                    "HIGH",source[extreme_index].ms,source[i].ms+MINUTE,
                    extreme,now,extreme_index,i))
                direction="DOWN"
                extreme=now
                extreme_index=i
        else:
            if now<extreme:
                extreme=now
                extreme_index=i
            elif now>=extreme+threshold:
                events.append(ObservedSwing(
                    "LOW",source[extreme_index].ms,source[i].ms+MINUTE,
                    extreme,now,extreme_index,i))
                direction="UP"
                extreme=now
                extreme_index=i
    # A final tentative extreme is never certified as a pivot.
    if any(e.confirmed_ms<=e.center_ms or
           e.confirmed_index<=e.center_index or
           e.confirmed_ms>source[-1].ms+MINUTE
           for e in events):
        raise ValueError("noncausal confirmed swing")
    if any(a.kind==b.kind or a.center_ms>=b.center_ms or
           a.confirmed_ms>=b.confirmed_ms
           for a,b in zip(events,events[1:])):
        raise ValueError("duplicate or retroactively revised swing")
    return events


def load_verified_closes(symbol:str,locked:dict,receipt:dict)->list[CloseMinute]:
    """Re-open 14 cached V89 official ZIPs and independently validate CLOSE.

    No network fetch. Exact ZIP, official CHECKSUM, receipt provenance and
    physical 1m HIGH/LOW reference are checked before using close prices.
    """
    if symbol not in ("BTCUSDT","ETHUSDT"):
        raise ValueError("frozen source symbols only")
    original=v90._parse_verified_source(symbol,locked,receipt)
    inputs=[x for x in locked["scheduled_inputs"] if x["symbol"]==symbol]
    reference={x["name"]:x for x in receipt["archives"]}
    result=[]
    for entry in inputs:
        archive=v90.v89.BASE/entry["zip_file"]
        checksum=v90.v89.BASE/entry["official_checksum_file"]
        zipped=archive.read_bytes()
        observed=v90.v89.verify_archive(entry,zipped,checksum.read_bytes())
        if any(observed.get(k)!=value
               for k,value in reference[entry["zip_file"]].items()
               if k in observed):
            raise ValueError("V89 committed official close archive differs")
        with zipfile.ZipFile(io.BytesIO(zipped)) as z:
            rows=csv.reader(io.StringIO(z.read(entry["csv_member"]).decode("utf-8-sig")))
            for row in rows:
                if len(row)!=12:
                    raise ValueError("official 12-field CSV altered")
                ms=int(row[0])
                if ms+59999!=int(row[6]):
                    raise ValueError("unclosed or timestamp-tampered source minute")
                close=v90.v89.strict_decimal(row[4])
                high=v90.v89.strict_decimal(row[2])
                low=v90.v89.strict_decimal(row[3])
                previous=original[len(result)]
                if (ms!=previous.ms or high!=previous.high or low!=previous.low
                    or not low<=close<=high):
                    raise ValueError("closed minute differs from certified V90 source")
                result.append(CloseMinute(ms,close))
    if len(result)!=20160 or result[0].ms!=v90.START_MS or (
        result[-1].ms+MINUTE!=v90.END_MS):
        raise ValueError("incomplete historical close sample")
    validate_closed_prefix(result)
    return result


def summarize(events:list[ObservedSwing],split_ms:int)->dict:
    if any(type(e) is not ObservedSwing for e in events):
        raise ValueError("opaque source-bound swing required")
    confirmations=Counter("A" if e.confirmed_ms<split_ms else "B" for e in events)
    return {
        "confirmed_swings":len(events),
        "high_swings":sum(e.kind=="HIGH" for e in events),
        "low_swings":sum(e.kind=="LOW" for e in events),
        "confirmed_A":confirmations["A"],
        "confirmed_B":confirmations["B"],
        "minimum_confirmation_lag_minutes":min(
            ((e.confirmed_ms-e.center_ms)//MINUTE for e in events),default=None),
        "maximum_confirmation_lag_minutes":max(
            ((e.confirmed_ms-e.center_ms)//MINUTE for e in events),default=None),
        "source_validated_event_digest":hashlib.sha256(
            json.dumps([
                [e.kind,e.center_ms,e.confirmed_ms,str(e.center_close),
                 str(e.confirm_close),e.center_index,e.confirmed_index]
                for e in events
            ],separators=(",",":"),ensure_ascii=False).encode()).hexdigest(),
        "elliott_degree_certificate":False,
        "order_or_entry_eligible":False,
    }


def run_historical_diagnostic()->dict:
    """Audit formerly examined July 2024 only, not new-data validation."""
    prior=v93.immutable_receipt(
        V98_REL,V98_SHA,V98_COMMIT,
        "nexus.elliott-v98-physical-abc-inner-geometry-diagnostics.v1")
    locked,receipt=v90.verify_locked_receipts()
    if (prior["v97_immutable_receipt_sha256"]!=v98.V97_SHA
        or prior["v89_official_source_receipt_sha256"]!=v90.SOURCE_RECEIPT_SHA
        or prior["recursive_elliott_certificates"]!=0):
        raise ValueError("source or V98 research-only lineage differs")
    out={
        "schema":"nexus.elliott-v99-causal-close-multiscale-diagnostic.v1",
        "recorded_utc":datetime.now(timezone.utc).isoformat(),
        "old_period":"2024-07-01--2024-07-14-UTC_PREINSPECTED_ONLY",
        "source_kind":"28 official Binance Spot 1m ZIPs validated against V89 receipts",
        "v98_immutable_commit":V98_COMMIT,
        "v98_immutable_sha256":V98_SHA,
        "v89_source_receipt_sha256":v90.SOURCE_RECEIPT_SHA,
        "research_rulebook_only_not_tuned_on_july_outcomes":True,
        "future_forward_validation_on_uninspected_data":False,
        "volatility_window_prior_closed_1m_returns":LOOKBACK_CLOSED_RETURNS,
        "scale_multipliers":[str(x) for x in TRAILING_MEDIAN_MULTIPLIERS],
        "minimum_threshold_fraction_prior_price":str(ABSOLUTE_PAST_PRICE_FLOOR),
        "no_ohlc_intrabar_order_inferred":True,
        "causal_close_stream_only":True,
        "no_discretionary_pivot_deletion":True,
        "multiple_scales_independent_not_force_nested":True,
        "no_elliott_family_or_degree_certification":True,
        "research_only":True,"paper_eligible":False,"live_enabled":False,
        "net_pnl":None,"orders":0,"signals":0,"v52_unchanged":True,
        "symbols":{},
    }
    for symbol in ("BTCUSDT","ETHUSDT"):
        closes=load_verified_closes(symbol,locked,receipt)
        sample={
            "official_complete_1m_close_candles":len(closes),
            "verified_first_open_ms":closes[0].ms,
            "verified_end_exclusive_ms":closes[-1].ms+MINUTE,
            "source_closes_sha256":hashlib.sha256(
                json.dumps([[x.ms,str(x.close)] for x in closes],
                separators=(",",":")).encode()).hexdigest(),
            "scales":{},
            "confirmed_elliott_pattern":False,
            "signals":0,
        }
        for multiple in TRAILING_MEDIAN_MULTIPLIERS:
            complete=observe_scale(closes,multiple)
            # Prefix consistency invariant on a separate run; all earlier
            # confirmed events must survive unchanged after more data arrives.
            mid=v90.SPLIT_MS
            earlier=observe_scale(closes,multiple,mid)
            retained=[x for x in complete if x.confirmed_ms<=mid]
            if earlier!=retained:
                raise ValueError("future observations revised earlier confirmed swing")
            sample["scales"][str(multiple)]=summarize(
                complete,v90.SPLIT_MS)
            sample["scales"][str(multiple)]["week_A_prefix_invariant"]=True
        out["symbols"][symbol]=sample
    ROOT.mkdir(parents=True,exist_ok=True)
    dest=ROOT/"V99_CAUSAL_MULTISCALE_CLOSE_DIAGNOSTIC.json"
    raw=(json.dumps(out,sort_keys=True,indent=2)+"\n").encode()
    if dest.exists():
        a=json.loads(dest.read_bytes())
        b=json.loads(raw)
        a.pop("recorded_utc",None)
        b.pop("recorded_utc",None)
        if a!=b:
            raise ValueError("V99 prior evidence changed; fail closed")
        raw=dest.read_bytes()
    else:
        dest.write_bytes(raw)
    print(json.dumps({
        "status":"V99_SOURCE_VERIFIED_CAUSAL_SWING_SCALES_RESEARCH_ONLY",
        "sha256":hashlib.sha256(raw).hexdigest(),
        "summary":{s:{k:{"swing_count":v["confirmed_swings"],
            "week_A":v["confirmed_A"],"week_B":v["confirmed_B"],
            "min_lag":v["minimum_confirmation_lag_minutes"]}
            for k,v in entry["scales"].items()}
            for s,entry in out["symbols"].items()},
        "elliott_certificates":0,"orders":0,
    },indent=2))
    return out


if __name__=="__main__":
    run_historical_diagnostic()
