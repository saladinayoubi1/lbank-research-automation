"""Causal (as of confirmed 4h signal close) regime features for frozen MR40 47.

No PnL or future bar enters feature extraction. Historical AFTER-THE-FACT
labels appear only in descriptive strata, never as inputs to a trading rule.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal as D, localcontext
import hashlib
import json
from pathlib import Path
from statistics import median

from research.nexus_mr40_independent_closed_signal_v1 import (
    ROWS_SHA, canon, frozen_rows,
)

PROTOCOL = "mr40_signal_time_regime_matrix_protocol_20261023.json"
CROSS = "mr40_cross_evidence_47_entry_diagnosis_20261023.json"
OUTPUT = "mr40_signal_time_regime_matrix_20261023.json"
CROSS_SHA = "f59266ab01e373c761c2d03f187d739a0d77e9297ecabe65f8a248c0e0f13dd9"
CROSS_DIGEST = "25e03b6d098bb2205533be3c20d69721b37fae931a57e5be691ee5db393927c4"
STEP = 14_400_000
Q = D("0.00000001")


def file_sha(path):
    h = hashlib.sha256()
    with path.open("rb") as inp:
        for part in iter(lambda: inp.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def eight(v):
    return str(v.quantize(Q)) if v is not None else None


def signal_features(rows, j):
    """Only rows through closed bar j; fixed horizons, no label dependency."""
    if type(j) is not int or j < 180 or j >= len(rows):
        raise ValueError("insufficient_closed_signal_history")
    s = rows[:j + 1]
    if not all(isinstance(x, (tuple, list)) and len(x) == 6 for x in s[-181:]):
        raise ValueError("invalid_ohlcv_shape")
    if any(s[k][0] - s[k-1][0] != STEP for k in range(j-180+1, j+1)):
        raise ValueError("signal_history_utc_discontinuity")
    with localcontext() as context:
        context.prec = 40
        def row(k):
            return [D(str(v)) for v in s[k][1:]]
        op, high, low, close, volume = row(j)
        if min(op, high, low, close) <= 0 or volume < 0 or high < max(op, close) or low > min(op, close):
            raise ValueError("invalid_signal_ohlcv")
        for k in range(j-13, j+1):
            a,b,c,d,e = row(k)
            if min(a,b,c,d) <= 0 or e < 0 or b < max(a,d) or c > min(a,d):
                raise ValueError("invalid_ATR_history_ohlcv")
        past40 = [D(str(s[k][4])) for k in range(j-40,j)]
        mu = sum(past40,D(0)) / D(40)
        var = sum(((c-mu)**2 for c in past40), D(0))/D(40)
        z = (close-mu)/var.sqrt() if var>0 else None
        atr = D(0)
        for k in range(j-13,j+1):
            _, hi, lo, _, _ = row(k)
            prev_cl = D(str(s[k-1][4]))
            atr += max(hi-lo,abs(hi-prev_cl),abs(lo-prev_cl))
        atr /= D(14)
        def pct(n): return D(100) * (close/D(str(s[j-n][4]))-D(1))
        return {
            "return_10_closed_bars_pct": eight(pct(10)),
            "return_40_closed_bars_pct": eight(pct(40)),
            "return_180_closed_bars_pct": eight(pct(180)),
            "ATR14_pct": eight(D(100)*atr/close),
            "signal_4h_range_pct": eight(D(100)*(high-low)/close),
            "signal_close_location_in_range": eight((close-low)/(high-low)) if high>low else None,
            "MR40_zscore": eight(z),
        }


def load_locked(root, original_dir):
    specfile = root/"research"/PROTOCOL
    protocol = json.loads(specfile.read_bytes())
    if (protocol.get("schema") != "nexus.mr40.signal_time_regime_matrix.protocol.v1"
        or protocol.get("historical_seen_only") is not True
        or protocol.get("safety",{}).get("promote") is not False
        or protocol.get("safety",{}).get("orders") != 0
        or protocol.get("source_digest",{}).get("canonical_8514_ohlcv_sha256") != ROWS_SHA
        or protocol.get("source_digest",{}).get("cross_evidence_47_full_report_sha256") != CROSS_SHA
        or protocol.get("source_digest",{}).get("cross_evidence_47_full_report_logical_digest") != CROSS_DIGEST):
        raise ValueError("locked_regime_protocol_drift")
    rows = frozen_rows(original_dir)
    if len(rows) != 8514:
        raise ValueError("wrong_original_market_length")
    crossfile = root/"results"/CROSS
    if file_sha(crossfile) != CROSS_SHA:
        raise ValueError("cross47_SHA_changed")
    cross = json.loads(crossfile.read_bytes())
    digest = cross.pop("digest", None)
    if digest != CROSS_DIGEST or hashlib.sha256(canon(cross)).hexdigest() != CROSS_DIGEST:
        raise ValueError("cross47_logical_digest_drift")
    if not cross.get("historic_seen_47_not_OOS") or cross.get("decision") != "DESCRIPTIVE_ONLY_NO_PROMOTE":
        raise ValueError("historical_labels_not_trusted")
    return rows,cross,file_sha(specfile)


def audit(root, original_dir):
    rows,cross,protocol_sha=load_locked(root,original_dir)
    per = []
    seen = set()
    for original in cross["entries"]:
        j = original["signal_index"]
        w = original["window"]
        if w not in ("train","evaluation") or j in seen:
            raise ValueError("bad_or_duplicate_47_signal_index")
        seen.add(j)
        entry_ms=int(datetime.fromisoformat(original["entry_open_utc"]).timestamp()*1000)
        if j+1>=len(rows) or entry_ms != rows[j+1][0] or rows[j+1][0]-rows[j][0]!=STEP:
            raise ValueError("signal_next_open_timestamp_mismatch")
        f = signal_features(rows, j)
        if f["MR40_zscore"] is None or D(f["MR40_zscore"]) > D("-2.0"):
            raise ValueError("expected_MR40_closed_entry_threshold")
        if D(f["return_180_closed_bars_pct"]) < 0:
            raise ValueError("original_Momentum30_admission_drift")
        per.append({
            "window":w,"signal_index":j,
            "entry_next_open_utc":original["entry_open_utc"],
            "historical_label_after_exit_only":original["historical_result_label"],
            "historical_held_low_MAE_pct":original["held_low_MAE_pct"],
            "structural_break_prior30":original["prior30_low_break"],
            "historical_loss_unarmed_by_plus2pct_close":
                original["unarmed_loss_before_2pct_profitable_close"],
            "features_at_completed_signal_close":f,
        })
    if len(per)!=47 or sum(t["window"]=="train" for t in per)!=25 or sum(t["window"]=="evaluation" for t in per)!=22:
        raise ValueError("frozen_47_train_eval_count_changed")
    names=list(per[0]["features_at_completed_signal_close"])
    summary={}
    for win in ("train","evaluation","all_47"):
        d=[v for v in per if win=="all_47" or v["window"]==win]
        group={"positions":len(d),"winners":sum(x["historical_label_after_exit_only"]=="winner" for x in d),
               "losers":sum(x["historical_label_after_exit_only"]=="loser" for x in d)}
        for label in ("winner","loser"):
            subset=[v["features_at_completed_signal_close"] for v in d if v["historical_label_after_exit_only"]==label]
            group[label+"_signal_feature_medians"]={
                n:eight(median([D(x[n]) for x in subset if x[n] is not None]))
                    if any(x[n] is not None for x in subset) else None
                for n in names
            }
        summary[win]=group
    result={
        "schema":"nexus.mr40.signal_time_regime_matrix.v1",
        "protocol_sha256":protocol_sha,
        "frozen_market_SHA256":ROWS_SHA,
        "joined_47_report_SHA256":CROSS_SHA,
        "seen_historical_train_and_evaluation_not_unseen_OOS":True,
        "signals_only_use_market_bars_at_or_before_confirmed_close":True,
        "pnl_not_passed_to_signal_features":True,
        "new_filter_created":False,
        "strategy_economic_edge_claim":False,
        "paper_or_order_change":False,
        "summary":summary,
        "per_position":per,
        "decision":"ENTRY_CAUSE_DESCRIPTIVE_ONLY_NO_PROMOTE"
    }
    result["digest"]=hashlib.sha256(canon(result)).hexdigest()
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True)
    p.add_argument("--original-dir",type=Path,required=True)
    args=p.parse_args()
    outcome=audit(args.root,args.original_dir)
    dest=args.root/"results"/OUTPUT
    created=False
    try:
        with dest.open("xb") as fp:
            created=True
            fp.write(json.dumps(outcome,sort_keys=True,indent=2,ensure_ascii=False).encode())
            fp.write(b"\n")
    except OSError:
        if created and dest.exists():
            dest.unlink()
        raise
    print(json.dumps({"sha256":file_sha(dest),"digest":outcome["digest"],
                      "summary":outcome["summary"]},ensure_ascii=False))


if __name__=="__main__":
    main()
