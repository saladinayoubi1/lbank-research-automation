"""Research-only V18 raw archive continuity and bounded Elliott candidate audit.

Does NOT retrieve Bybit, authenticate a purported data supplier, register a
strategy, place orders, rerun losing historical folds or promote Paper/Demo.
UTC 15m timestamps represent candle OPENS. Missing Aug-Oct 2026 bridge fails
closed; historical archive ends 2026-07-31 23:45 UTC.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

from nexus_elliott_source_bound_v15 import (
    _independent_selected_pivots, certify_seven_pivots_from_closed_15m,
)
from nexus_elliott_quality_audit_v14 import review_quality_observation
from nexus_elliott_prospective_exit_v17 import FORWARD_START_UTC, FORWARD_END_UTC

RESEARCH_ONLY = True
LIVE_ENABLED = AUTO_DEMO = ENTRY_SIGNAL = PAPER_ELIGIBLE = False
RECURSIVE_ELLIOTT_PROVEN = False
BASE_BARS = 128544
BASE_FIRST_OPEN = pd.Timestamp("2022-12-01T00:00:00Z")
BASE_LAST_OPEN = pd.Timestamp("2026-07-31T23:45:00Z")
STEP = pd.Timedelta(minutes=15)
STEP_NS = STEP.value
FROZEN_SHA = {
    "BTCUSDT": "c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
    "ETHUSDT": "ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}
PAIR_DIR = {"BTCUSDT":"btc_usdt", "ETHUSDT":"eth_usdt"}
COLUMNS = ("open","high","low","close","volume")


def digest_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clock(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation requires timezone-aware UTC clock")
    t = value.astimezone(timezone.utc)
    if t.second or t.microsecond or t.minute % 15:
        raise ValueError("observation not on 15m UTC grid")
    return t


def validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or not {"timestamp", *COLUMNS} <= set(frame.columns):
        raise ValueError("source must supply timestamp and all 15m OHLCV columns")
    f = frame.copy().reset_index(drop=True)
    if f.empty:
        raise ValueError("source must not be empty")
    if any(pd.Timestamp(x).tzinfo is None or pd.Timestamp(x).utcoffset() is None for x in f.timestamp):
        raise ValueError("source timestamps require timezone")
    f["timestamp"] = pd.to_datetime(f.timestamp, utc=True, errors="raise")
    ns = f.timestamp.astype("int64").to_numpy()
    if (ns % STEP_NS).any() or (len(ns) > 1 and (np.diff(ns) != STEP_NS).any()):
        raise ValueError("15m source is gapped, duplicated, unsorted or not UTC aligned")
    x = f[list(COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(x).all() or (x[:, :4] <= 0).any() or (x[:, 4] < 0).any() or (
        x[:, 1] < x[:, [0, 2, 3]].max(axis=1)
    ).any() or (x[:, 2] > x[:, [0, 1, 3]].min(axis=1)).any():
        raise ValueError("source OHLCV is invalid")
    return f


def validated_bridge(base: pd.DataFrame, continuation: pd.DataFrame,
                     observed_at_utc: datetime) -> pd.DataFrame:
    """No gaps or duplicated bars at the July/August frozen-file boundary."""
    b = validate_frame(base)
    n = validate_frame(continuation)
    seen = clock(observed_at_utc)
    if n.timestamp.iloc[0] != b.timestamp.iloc[-1] + STEP:
        raise ValueError("missing/overlapping historical-to-future bridge")
    if n.timestamp.iloc[-1] + STEP > pd.Timestamp(seen):
        raise ValueError("future/forming source candle")
    return pd.concat([b, n], ignore_index=True)


def closed_higher_timeframes(frame: pd.DataFrame):
    """Only complete 4- and 16-bar buckets are visible to feature review."""
    def agg(freq: str, expected: int):
        group=frame.groupby(frame.timestamp.dt.floor(freq),sort=True)
        df=group.agg(timestamp=("timestamp","first"),count=("timestamp","size"),
                     high=("high","max"),low=("low","min"),
                     close=("close","last")).reset_index(drop=True)
        return df.loc[df["count"]==expected].reset_index(drop=True)
    return agg("h",4),agg("4h",16)


def inspect_latest_closed_decision(
    full_frame: pd.DataFrame, *, symbol: str,
    observed_at_utc: datetime, continuation_sha256: str,
) -> dict:
    """Derive source and V14/V15 claims from real closed OHLCV, never input flags."""
    if symbol not in PAIR_DIR:
        raise ValueError("only two preregistered pairs allowed")
    seen=clock(observed_at_utc)
    f=validate_frame(full_frame)
    if not isinstance(continuation_sha256,str) or len(continuation_sha256)!=64 or (
        any(c not in "0123456789abcdef" for c in continuation_sha256)
    ):
        raise ValueError("lowercase continuation file SHA256 required")
    end=f.timestamp.iloc[-1]+STEP
    if end != pd.Timestamp(seen):
        raise ValueError("source snapshot is stale or contains forming bars")
    if not FORWARD_START_UTC <= end.to_pydatetime() < FORWARD_END_UTC:
        raise ValueError("decision outside preregistered forward period")
    result={
        "schema":"nexus.elliott.v18.source-gate.v1",
        "symbol":symbol,"decision_close_utc":end.isoformat(),
        "continuation_raw_sha256":continuation_sha256,
        "status":"NOT_ELIGIBLE", "source_closed_bars":len(f),
        "external_bybit_authenticity_verified":False,
        "research_only":True,"live_enabled":False,
        "paper_eligible":False,"auto_demo":False,"orders_placed":0,
        "recursive_elliott_proven":False,"entry_signal":False,
    }
    i=len(f)-1
    if i < 300:
        return {**result,"reason":"INSUFFICIENT_HISTORY"}
    h,q=closed_higher_timeframes(f)
    if len(h)<74 or len(q)<16:
        return {**result,"reason":"INCOMPLETE_HIGHER_TF_WARMUP"}
    if h.timestamp.iloc[-1]+pd.Timedelta(hours=1)>end or (
        q.timestamp.iloc[-1]+pd.Timedelta(hours=4)>end
    ):
        raise AssertionError("forming H1/H4 context")
    normalized=(h.high.astype(float)-h.low.astype(float))/h.close.astype(float)
    h1_ok=normalized < normalized.shift(1).rolling(72,min_periods=72).median()*1.65
    qclose=q.close.astype(float)
    qlow=q.low.astype(float)
    h4_up=(qclose>qclose.shift(1).rolling(12).median())&(
        qlow>qlow.shift(4).rolling(8).min()
    )
    prices=f[["open","high","low","close"]].to_numpy(dtype=float)
    pivots=_independent_selected_pivots(prices,i)
    if len(pivots)!=7:
        return {**result,"reason":"NO_SEVEN_ACCEPTED_PIVOTS"}
    proof=certify_seven_pivots_from_closed_15m(f,pivots,i,decision_close_utc=end)
    if not proof.source_bound:
        return {**result,"reason":"V15_"+proof.reason}
    correction=pivots[-1].index
    path=[
        ((f.timestamp.iloc[k]+STEP).to_pydatetime(),f.low.iloc[k],f.close.iloc[k])
        for k in range(correction,i+1)
    ]
    tr=[]
    for k in range(i-14,i):
        hi=Decimal(str(f.high.iloc[k]))
        lo=Decimal(str(f.low.iloc[k]))
        prior=Decimal(str(f.close.iloc[k-1]))
        tr.append(max(hi-lo,abs(hi-prior),abs(lo-prior)))
    review=review_quality_observation(
        pivots,i,decision_close_utc=end.to_pydatetime(),
        h1_closed_utc=(h.timestamp.iloc[-1]+pd.Timedelta(hours=1)).to_pydatetime(),
        h4_closed_utc=(q.timestamp.iloc[-1]+pd.Timedelta(hours=4)).to_pydatetime(),
        previous_close_price=f.close.iloc[i-1],decision_close_price=f.close.iloc[i],
        decision_low_price=f.low.iloc[i],post_correction_closed_path=path,
        prior_14_true_ranges=tr,h4_closed_up=bool(h4_up.iloc[-1]),
        h1_normalized_range_ok=bool(h1_ok.iloc[-1]),
    )
    if not review["study_eligible"]:
        return {**result,"reason":"V14_FILTERS_REJECTED","v14_reasons":review["reasons"],
                "v15_source_bound":True}
    identity=proof.structure_id
    if identity is None:
        raise AssertionError("source-bound structure identity missing")
    event_id=f"{symbol}:{end.strftime('%Y%m%dT%H%MZ')}:{identity[0]}-{identity[1]}"
    # This is NOT a runtime signal. The V17 evaluator remains unwired;
    # no assertion of externally authenticated exchange origin is made.
    return {**result,"status":"LIMITED_SOURCE_BOUND_RESEARCH_EVENT",
            "reason":"NO_STRATEGY_OR_ORDER_AUTHORITY",
            "v15_source_bound":True,
            "research_observation":{
                "event_id":event_id,"symbol":symbol,
                "decision_close_utc":end.to_pydatetime().isoformat(),
                "previous_close":str(f.close.iloc[i-1]),
                "decision_close":str(f.close.iloc[i]),
                "fifth_high":str(pivots[5].price),
                "correction_low":str(pivots[6].price),
                "source_bound_seven_pivot":True,
                "closed_first_breakout":True,
                "post_correction_path_valid":True,
            }}


def replay_source_model_status(archive_root: Path) -> dict:
    """Read-only proof of source *model* compatibility, not market fidelity.

    A replay ZIP schema_version=2 is NOT evidence that its underlying candles
    follow the independently versioned v2 source-row-stable trade aggregation.
    Never append a new row-stable candle collection to a legacy unversioned
    trade-derived series, even when timestamps and OHLCV otherwise validate.
    """
    base=Path(archive_root)
    file=base/"REPLAY_DATASET_MANIFEST.json"
    if not file.is_file():
        raise ValueError("frozen replay source manifest required")
    manifest=json.loads(file.read_text(encoding="utf-8"))
    if not isinstance(manifest,dict):
        raise ValueError("frozen replay manifest malformed")
    digest=manifest.get("manifest_sha256")
    unsigned={k:v for k,v in manifest.items() if k!="manifest_sha256"}
    canonical=(json.dumps(unsigned,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
    if not isinstance(digest,str) or digest!=sha256(canonical).hexdigest():
        raise ValueError("frozen replay manifest SHA256 fails canonical check")
    if manifest.get("source")!="official_public_spot_trade_archives" or (
        manifest.get("venue")!="bybit"
    ):
        raise ValueError("unexpected historical source category")
    model=manifest.get("candle_model")
    if model is None:
        return {
            "status":"BLOCKED_LEGACY_UNVERSIONED_TRADE_CANDLE_MODEL",
            "replay_manifest_sha256":digest,
            "replay_schema_version":manifest.get("schema_version"),
            "original_source":"official_public_spot_trade_archives",
            "actual_candle_model_proven":False,
            "future_append_allowed":False,
            "reason":"Replay package schema v2 does not bind the candle-model v2 row-tie ordering. Full separate raw-trade replay required; no mixed-source append.",
        }
    from bybit_spot_backfill import (
        CANDLE_MODEL_SCHEMA, validate_candle_model_state, BybitBackfillError
    )
    if not isinstance(model,dict) or model.get("schema")!=CANDLE_MODEL_SCHEMA or (
        model.get("timestamp_tie_order")!="original_archive_row_order"
    ):
        raise ValueError("replay source model incompatible with v2 row-stable trades")
    try:
        validate_candle_model_state(base)
    except BybitBackfillError as exc:
        raise ValueError("replay source model sidecar/manifest validation failed") from exc
    return {
        "status":"VERSIONED_TRADE_CANDLE_MODEL_VALIDATED",
        "replay_manifest_sha256":digest,
        "original_source":"official_public_spot_trade_archives",
        "actual_candle_model_proven":True,
        "future_append_allowed":True,
    }


def inspect_frozen_archive_and_future_bridge(
    archive_root: Path, continuation_path: Path, *,
    symbol: str, observed_at_utc: datetime,
) -> dict:
    """Actual ingress verifies base raw file hash. No external API called."""
    if symbol not in PAIR_DIR:
        raise ValueError("unknown pair")
    base_path=Path(archive_root)/"bybit_market"/PAIR_DIR[symbol]/"minute15.parquet"
    if digest_file(base_path)!=FROZEN_SHA[symbol]:
        raise AssertionError("original Bybit archive identity mismatch")
    base=validate_frame(pd.read_parquet(base_path))
    if len(base)!=BASE_BARS or base.timestamp.iloc[0]!=BASE_FIRST_OPEN or (
        base.timestamp.iloc[-1]!=BASE_LAST_OPEN
    ):
        raise AssertionError("frozen archived 15m window inconsistent")
    candle_model=replay_source_model_status(archive_root)
    if not Path(continuation_path).is_file():
        return {
            "schema":"nexus.elliott.v18.ingress-gate.v1",
            "status":"BLOCKED_NO_VERIFIED_CONTINUATION_FILE",
            "frozen_archive_last_open_utc":BASE_LAST_OPEN.isoformat(),
            "required_bridge_first_open_utc":(BASE_LAST_OPEN+STEP).isoformat(),
            "external_bybit_authenticity_verified":False,
            "source_model_status":candle_model["status"],
            "future_append_allowed":False,
            "orders_placed":0,"research_only":True,
            "live_enabled":False,"paper_eligible":False,"auto_demo":False,
        }
    if not candle_model["future_append_allowed"]:
        return {
            "schema":"nexus.elliott.v18.ingress-gate.v1",
            "status":"BLOCKED_CANDLE_SEMANTICS_REPLAY_REQUIRED",
            "source_model_status":candle_model["status"],
            "research_only":True,"live_enabled":False,
            "paper_eligible":False,"auto_demo":False,"orders_placed":0,
            "archive_files_rewritten":False,
            "required_action":"Replay original untouched trade archives into a new v2 row-order-stable, source-manifest-bound archive; preserve old research.",
        }
    if Path(continuation_path).suffix.lower()!=".parquet":
        raise ValueError("only pinned local parquet continuation supported")
    new_hash=digest_file(Path(continuation_path))
    new_source=pd.read_parquet(continuation_path)
    joined=validated_bridge(base,new_source,observed_at_utc)
    report=inspect_latest_closed_decision(
        joined,symbol=symbol,observed_at_utc=observed_at_utc,
        continuation_sha256=new_hash,
    )
    report["frozen_reference_sha256"]=FROZEN_SHA[symbol]
    report["external_bybit_authenticity_verified"]=False
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--archive",type=Path,required=True)
    parser.add_argument("--continuation",type=Path,required=True)
    parser.add_argument("--symbol",choices=tuple(PAIR_DIR),required=True)
    args=parser.parse_args()
    now=datetime.now(timezone.utc)
    asof=now.replace(minute=now.minute//15*15,second=0,microsecond=0)
    out=inspect_frozen_archive_and_future_bridge(
        args.archive,args.continuation,symbol=args.symbol,observed_at_utc=asof
    )
    print(json.dumps(out,sort_keys=True,default=str))
    if out["status"].startswith("BLOCKED"):
        raise SystemExit(2)


if __name__=="__main__":
    main()
