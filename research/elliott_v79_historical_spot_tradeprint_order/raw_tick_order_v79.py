"""V79 independent raw public Bybit Spot trade price time-order audit.

Specific *already-inspected* 2025-09-11 12:15 UTC ETH historical stop trade.
Verify raw gzip SHA, monotonic millisecond trade stamps, original V37 trace,
V77 full-path source receipt, and exact 15m physical candle OHLC match before
interpreting which first appeared: stop or +1R trade-price threshold.

A public trade-print price is not proof of an executable retail quote/fill.
No P/L rewrite, no paper or live trading, no parameter optimization.
"""
from __future__ import annotations
import argparse,csv,gzip,json,hashlib
from pathlib import Path
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from collections import Counter

RAW_SHA="adaa67da56a9273de0343af880c06d15bc5db1988fc0bce0e2b3a1e8f89636fa"
TRACE_SHA="c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c"
V77_SHA="6e842b71af41f43a78c3e70c3e148ee1896153123aad8e4e2a8cc8f7660806e3"
UTC_DAY="2025-09-11"
ENTRY_TIME="2025-09-11T12:15:00Z"
WINDOW_MINUTES=15
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
NEW_PNL=None
EXPECTED_HEADER=["id","timestamp","price","volume","side","rpi"]

def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda:stream.read(1048576),b""):
            h.update(part)
    return h.hexdigest()

def D(value):
    if type(value) is bool or isinstance(value,float):
        raise ValueError("FLOAT_PRICE_NOT_ACCEPTED")
    try:n=Decimal(str(value))
    except (TypeError,ValueError,InvalidOperation) as error:raise ValueError("INVALID_PRICE") from error
    if not n.is_finite() or n<=0:raise ValueError("BAD_POSITIVE_PRICE")
    return n

def UTCmillis(s):
    d=datetime.fromisoformat(s.replace("Z","+00:00"))
    if d.tzinfo is None:raise ValueError("NAIVE_CLOCK")
    return int(d.timestamp()*1000)

def order(first_a,first_b):
    """Never infer intra-ms execution order from CSV line order alone."""
    if first_a is None or first_b is None:return "ONE_OR_BOTH_THRESHOLDS_NEVER_TOUCHED"
    a,b=first_a["timestamp_ms"],first_b["timestamp_ms"]
    if a==b:return "SAME_MILLISECOND_ORDER_UNRESOLVED"
    return "ONE_R_TRADE_PRICE_FIRST" if a<b else "STOP_TRADE_PRICE_FIRST"

def parse_raw_window(path,start_ms,end_ms,thresholds):
    first={profile:{"stop":None,"one_r":None} for profile in thresholds}
    window_count=0;total_count=0;last_ms=-1;prior_day=UTCmillis(UTC_DAY+"T00:00:00Z")
    next_day=prior_day+86400000
    sample_ohlc=None
    prior=Counter()
    with gzip.open(path,"rt",encoding="utf-8-sig",newline="") as source:
        rows=csv.reader(source)
        header=next(rows,None)
        if header!=EXPECTED_HEADER:raise ValueError("SOURCE_GZIP_HEADER_CHANGED")
        for row in rows:
            if len(row)!=len(header):raise ValueError("MALFORMED_SPOT_TRADE_CSV_ROW")
            row_id,rawstamp,rawprice,vol,side,rpi=row
            stamp=int(rawstamp)
            if not prior_day<=stamp<next_day:raise ValueError("TRADE_OUTSIDE_PUBLISHED_UTC_DAY")
            if stamp<last_ms:raise ValueError("TRADE_SOURCE_NOT_CHRONOLOGICALLY_ORDERED")
            last_ms=stamp
            price=D(rawprice)
            if D(vol)<=0 or side.lower() not in ("buy","sell") or rpi not in ("0","1"):
                raise ValueError("INVALID_SPOT_TRADE_ROW")
            total_count+=1
            if not start_ms<=stamp<end_ms:continue
            window_count+=1
            if sample_ohlc is None:
                sample_ohlc={"open":price,"high":price,"low":price,"close":price}
            else:
                sample_ohlc["high"]=max(sample_ohlc["high"],price)
                sample_ohlc["low"]=min(sample_ohlc["low"],price)
                sample_ohlc["close"]=price
            for profile,t in thresholds.items():
                if price<=t["stop"] and first[profile]["stop"] is None:
                    first[profile]["stop"]={"timestamp_ms":stamp,"row_id":row_id,"price":str(price)}
                if price>=t["one_r"] and first[profile]["one_r"] is None:
                    first[profile]["one_r"]={"timestamp_ms":stamp,"row_id":row_id,"price":str(price)}
    if window_count<=0 or sample_ohlc is None:
        raise ValueError("NO_PHYSICAL_TRADES_IN_STOP_BAR")
    if total_count<window_count:raise ValueError("IMPOSSIBLE_ROW_COUNT")
    return total_count,window_count,sample_ohlc,first

def audit(raw,trace_file,v77_file,archive,source_root):
    from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
    for f,h in ((raw,RAW_SHA),(trace_file,TRACE_SHA),(v77_file,V77_SHA)):
        if sha(f)!=h:raise ValueError("PINNED_HISTORICAL_SOURCE_CHANGED")
    trace=json.loads(Path(trace_file).read_text(encoding="utf8"),parse_float=Decimal)
    v77=json.loads(Path(v77_file).read_text(encoding="utf8"))
    if (trace.get("live_enabled") is not False or
        v77.get("incorrect_early_exit_holds_detected")!=0 or
        v77.get("paired_cost_profile_exit_paths_checked")!=20 or
        v77.get("live_enabled") is not False):
        raise ValueError("PREVIOUS_SOURCE_BOUND_AUDIT_NOT_VERIFIED")
    observed={}
    for cell in trace["rows"]:
        if cell["symbol"]!="ETHUSDT" or cell["part"]!="validation":continue
        profile=cell["profile"]
        if profile not in ("conservative","stress"):raise ValueError("UNEXPECTED_RISK_PROFILE")
        for trade in cell["trades"]:
            if int(trade["trade_index"])!=2:continue
            if trade["fill"]["open_at"] not in ("2025-09-11T12:15:00+00:00",ENTRY_TIME):
                raise ValueError("TARGET_TRADE_ENTRY_DIFFERENT")
            if (int(trade["fill"]["bar_index"])!=97489 or
                int(trade["exit"]["bar_index"])!=97489 or
                trade["exit_reason"]!="stop"):
                raise ValueError("TARGET_TRADE_NOT_SAME_BAR_STOP")
            origin=D(trade["entry_reference"]);stop=D(trade["stop"])
            threshold=origin+(origin-stop)
            observed[profile]={"entry_reference":origin,"stop":stop,"one_r":threshold,
                "original_target":D(trade["target"])}
    if set(observed)!={"conservative","stress"}:raise ValueError("MISSING_BOTH_COST_PROFILES")
    start=UTCmillis(ENTRY_TIME);end=start+900000
    n,nin,ohlc,first=parse_raw_window(raw,start,end,observed)
    source=load_verified_archive_frame(archive,"ETHUSDT","minute15")
    index=97489
    archived_stamp=source["timestamp"].iloc[index]
    if UTCmillis(str(archived_stamp))!=start:
        raise ValueError("RAW_TICK_DAY_AND_ARCHIVED_BAR_TIMESTAMP_MISMATCH")
    archived_ohlc={k:D(str(source[k].iloc[index])) for k in ("open","high","low","close")}
    delta={k:abs(ohlc[k]-archived_ohlc[k]) for k in archived_ohlc}
    # Tick archive and historical verified 15m original must agree within
    # one exchange cent on ALL four OHLC; otherwise no causal claim.
    matches=all(v<=Decimal("0.01") for v in delta.values())
    evaluated={}
    for profile in ("conservative","stress"):
        result=first[profile]
        evaluated[profile]=dict(
            entry_reference=str(observed[profile]["entry_reference"]),
            original_stop=str(observed[profile]["stop"]),
            original_target=str(observed[profile]["original_target"]),
            hypothetical_one_r_trade_price=str(observed[profile]["one_r"]),
            first_stop_print=result["stop"],
            first_one_r_print=result["one_r"],
            print_time_order=order(result["one_r"],result["stop"]) if matches else "BLOCKED_OHLC_SOURCE_MISMATCH",
            executable_quote_or_fill_verified=False,
            hypothetical_one_r_execution_verified=False)
    return dict(
        schema="nexus.elliott-v79-historical-spot-tradeprint-stopbar-order.v1",
        previously_inspected=True,
        source_url="https://public.bybit.com/spot/ETHUSDT/ETHUSDT_2025-09-11.csv.gz",
        raw_trade_csv_gzip_sha256=sha(raw),
        source_v77_archived_15m_first_touch_receipt_sha256=sha(v77_file),
        frozen_legacy_event_trace_sha256=sha(trace_file),
        archived_spot_symbol="ETHUSDT",
        archive_utc_day=UTC_DAY,
        ambiguous_historical_bar_start_utc=ENTRY_TIME,
        ambiguous_historical_bar_end_exclusive_utc="2025-09-11T12:30:00Z",
        total_day_trade_prints=n,window_trade_prints=nin,
        raw_tradeprint_ohlc={k:str(v) for k,v in ohlc.items()},
        original_verified_15m_ohlc={k:str(v) for k,v in archived_ohlc.items()},
        absolute_ohlc_price_differences={k:str(v) for k,v in delta.items()},
        raw_tradeprint_vs_original_15m_ohlc_match_within_one_cent=matches,
        no_archive_market_publication_timestamp_at_historical_decision=True,
        no_transaction_cost_or_entry_price_rule_changes=True,
        no_real_fills_or_executable_quotes=True,
        physical_tradeprint_not_orderbook_spread_evidence=True,
        findings_by_original_cost_profile=evaluated,
        live_enabled=False,paper_eligible=False,entry_signal=False,
        new_pnl=None)
def main():
    p=argparse.ArgumentParser()
    for name in ("raw","trace","v77","archive","output"):p.add_argument("--"+name,required=True)
    args=p.parse_args();out=Path(args.output)
    if out.exists():raise RuntimeError("IMMUTABLE_AUDIT_ALREADY_EXISTS")
    value=audit(args.raw,args.trace,args.v77,args.archive,None)
    out.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({"trades_in_bar":value["window_trade_prints"],
        "total_day":value["total_day_trade_prints"],
        "ohlc_matches_original_archive":value["raw_tradeprint_vs_original_15m_ohlc_match_within_one_cent"],
        "profiles":{k:v["print_time_order"] for k,v in value["findings_by_original_cost_profile"].items()},
        "receipt_sha256":sha(out)},ensure_ascii=False))
if __name__=="__main__":main()
