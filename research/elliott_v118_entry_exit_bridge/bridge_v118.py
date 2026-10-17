"""V118: physical historical Wave1 breakout -> next open -> Wave2 stop/2R.

Frozen ONE exploratory hypothesis on ALREADY INSPECTED JULY 2024 BINANCE SPOT.
This is not Bybit, a pristine OOS result, an Elliott certificate, or orders.
The original V106 strict Wave1/2 necessary gate and V107 full denominator
are unchanged. This adds no future entry signal or Demo qualification.
"""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import os
from pathlib import Path

from research.elliott_v90_frozen_replication import replicate_v90 as v90
from research.elliott_v115_historical_profile import profile_v115 as v115
from research.elliott_v107_prefix_census import census_v107 as v107
from research.elliott_v108_forward_outcomes import outcomes_v108 as v108
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v99_causal_scale import scale_v99 as v99

SCHEMA="nexus.elliott-v118-preinspected-wave1-breakout-physical-v1"
MINUTE=60_000
WINDOW=240
MAX_HOLD=240
INITIAL_CASH=Decimal("500")
MAX_NOTIONAL=Decimal("250")
MAX_NOMINAL_STOP_LOSS=Decimal("2.5")
PROFILES={"conservative":(Decimal("10"),Decimal("5")),
          "stress":(Decimal("25"),Decimal("15"))}
SIZE_STEP=Decimal("0.00000001")
RESEARCH_ONLY=True
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ENTRY_SIGNAL=False
ORDER_ADAPTER=None
PROSPECTIVE_V117_UNTOUCHED=True


class ElliottV118Error(ValueError):
    pass


def digest(value:object)->str:
    return hashlib.sha256(json.dumps(
        value,sort_keys=True,separators=(",",":"),allow_nan=False
    ).encode("utf-8")).hexdigest()


def _validate_bars(bars:list[v102.Candle])->None:
    v108.validate_physical_candles(bars)


def find_first_breakout(symbol:str, ordinal:int, six:list[v99.ObservedSwing],
                        decision_ms:int, bars:list[v102.Candle])->dict:
    """Observe events only after Wave2 right confirmation, no same-bar entry.

    Abstain upon ANY physical low touching Wave2 *before* breakout;
    including on the signal candle. Neither wave count nor price level may be
    revised with outcomes after the decision.
    """
    if symbol not in ("BTCUSDT","ETHUSDT") or type(ordinal) is not int or ordinal<0:
        raise ElliottV118Error("unsupported historical symbol/candidate")
    if (len(six)!=6 or any(type(x) is not v99.ObservedSwing for x in six)
        or six[-1].confirmed_ms!=decision_ms or type(decision_ms) is not int
        or decision_ms%MINUTE or not bars):
        raise ElliottV118Error("missing frozen right-confirmed Wave2 source")
    if six[3].kind!="LOW":
        return {"classification":"BEARISH_SPOT_NO_SHORT"}
    w0,w1,w2=six[3:]
    if not (Decimal("0")<w0.center_close<w2.center_close<w1.center_close):
        return {"classification":"ORIGINAL_STRUCTURAL_LEVELS_INVALID"}
    start=bars[0].ms
    at,rem=divmod(decision_ms-start,MINUTE)
    if rem or at<0 or at>=len(bars):
        return {"classification":"RIGHT_CENSORED_NO_FIRST_POST_CONFIRMATION_BAR"}
    last=min(at+WINDOW,len(bars)-1)
    previous=bars[at-1].close if at>0 else None
    for i in range(at,last):
        bar=bars[i]
        # A breakout cannot be entered after the structure was invalidated
        # intrabar, even when that very bar closes bullish.
        if bar.low<=w2.center_close:
            return {"classification":"WAVE2_INVALIDATED_BEFORE_ENTRY",
                    "invalidated_open_ms":bar.ms}
        if previous is not None and previous<=w1.center_close<bar.close:
            # Signal only becomes observable at this candle CLOSE; the
            # actual hypothetical fill is the FOLLOWING candle OPEN.
            return {
                "classification":"CLOSED_WAVE1_BREAKOUT_NEXT_OPEN",
                "symbol":symbol,"id":f"{symbol}-{ordinal}",
                "decision_ms":decision_ms,"signal_closed_ms":bar.ms+MINUTE,
                "entry_open_ms":bars[i+1].ms,"entry_index":i+1,
                "mid_open":str(bars[i+1].open),
                "wave0":str(w0.center_close),"wave1":str(w1.center_close),
                "wave2_stop":str(w2.center_close),
            }
        previous=bar.close
    if at+WINDOW>=len(bars):
        return {"classification":"RIGHT_CENSORED_NO_COMPLETE_240M_BREAKOUT_WINDOW"}
    return {"classification":"NO_CLOSED_WAVE1_BREAKOUT_WITHIN_240M"}


def replay_proposals(intents:list[dict], candles:dict[str,list[v102.Candle]],
                     profile:str)->dict:
    """Long-only ONE shared cash book, admission at next open, stop-first exit.

    No short and no simultaneous positions. All accepted signal intents count
    even if later denied due to cash overlap; future OHLC is used for outcome
    only and never to choose earlier rank or acceptance.
    """
    if profile not in PROFILES or set(candles)!={"BTCUSDT","ETHUSDT"}:
        raise ElliottV118Error("invalid profile or exact BTC/ETH source")
    for bars in candles.values():
        _validate_bars(bars)
    fee,slip=(x/Decimal("10000") for x in PROFILES[profile])
    indexed={}
    for symbol,bars in candles.items():
        indexed[symbol]=(bars[0].ms,len(bars))
    cash=INITIAL_CASH
    booked=[]
    denials=[]
    active_exit_ms=-1
    seen=set()
    for intent in sorted(intents,key=lambda x:(x["entry_open_ms"],x["symbol"],x["id"])):
        ident=intent.get("id")
        if (not isinstance(ident,str) or ident in seen
            or intent.get("symbol") not in candles
            or type(intent.get("entry_index")) is not int
            or type(intent.get("entry_open_ms")) is not int):
            raise ElliottV118Error("duplicate or malformed original candidate")
        seen.add(ident)
        symbol=intent["symbol"]
        bars=candles[symbol]
        i=intent["entry_index"]
        if (not 0<=i<len(bars) or bars[i].ms!=intent["entry_open_ms"]
            or intent.get("signal_closed_ms")!=bars[i].ms
            or intent["decision_ms"]>intent["signal_closed_ms"]-MINUTE
            or intent.get("classification")!="CLOSED_WAVE1_BREAKOUT_NEXT_OPEN"):
            raise ElliottV118Error("future-leaking or non-next-open research intent")
        if intent["entry_open_ms"]<active_exit_ms:
            denials.append({"id":ident,"why":"ONE_SHARED_CASH_POSITION_ALREADY_OPEN"})
            continue
        entry_mid=bars[i].open
        if str(entry_mid)!=intent["mid_open"]:
            raise ElliottV118Error("original physical entry price substituted")
        w0,w1,stop=(Decimal(intent[k]) for k in ("wave0","wave1","wave2_stop"))
        if not (Decimal(0)<w0<stop<w1 and entry_mid>stop):
            denials.append({"id":ident,"why":"ENTRY_BELOW_STRUCTURE_STOP"})
            continue
        entry=entry_mid*(1+slip)
        target=entry_mid+Decimal("2")*(entry_mid-stop)
        if target<=entry:
            denials.append({"id":ident,"why":"TARGET_AFTER_FRICTION_UNREACHABLE"})
            continue
        stop_after_friction=stop*(1-slip)*(1-fee)
        spend_per_qty=entry*(1+fee)
        gapless_risk_per_qty=spend_per_qty-stop_after_friction
        if gapless_risk_per_qty<=0:
            raise ElliottV118Error("risk denominator invalid")
        qty=min(MAX_NOTIONAL/entry,
                MAX_NOMINAL_STOP_LOSS/gapless_risk_per_qty,
                cash/spend_per_qty).quantize(SIZE_STEP,rounding=ROUND_DOWN)
        if qty<=0:
            denials.append({"id":ident,"why":"NO_SHARED_CASH_CAPACITY"})
            continue
        spent=qty*spend_per_qty
        if spent>cash or qty*entry>MAX_NOTIONAL or (
                qty*gapless_risk_per_qty>MAX_NOMINAL_STOP_LOSS):
            raise ElliottV118Error("shared-cash or risk cap violated")
        # Admission is the next physical OPEN. Neither stop nor target may
        # be selected based on price later than this entry.
        cash-=spent
        last=min(i+MAX_HOLD,len(bars)-1)
        exit_reason=None
        exit_level=None
        exit_i=None
        for j in range(i,last+1):
            bar=bars[j]
            if j==i+MAX_HOLD:
                exit_reason="TIMEOUT_NEXT_OPEN"
                exit_level=bar.open
                exit_i=j
                break
            if bar.low<=stop:
                exit_reason=("GAP_THROUGH_STOP_AT_WORSE_OPEN"
                             if bar.open<stop else
                             "STOP_FIRST_SAME_BAR_IF_TARGET_ALSO_HIT")
                exit_level=min(bar.open,stop)
                exit_i=j
                break
            if bar.high>=target:
                exit_reason="TARGET_LIMITED_TO_PREDECLARED_2R"
                exit_level=target
                exit_i=j
                break
        if exit_i is None:
            # No way to compute source-complete realized P/L: explicitly
            # reject any net-return "success" claim on right-censored trade.
            return {
                "status":"INCOMPLETE_SOURCE_WITH_OPEN_POSITION_NO_NET_PNL",
                "censored_id":ident,"net_pnl_usdt":None,
                "paper_eligible":False,"live_enabled":False,
            }
        exit_px=exit_level*(1-slip)
        exit_proceeds=qty*exit_px*(1-fee)
        pnl=exit_proceeds-spent
        cash+=exit_proceeds
        active_exit_ms=bars[exit_i].ms+MINUTE
        booked.append({
            "id":ident,"symbol":symbol,
            "decision_ms":intent["decision_ms"],
            "signal_closed_ms":intent["signal_closed_ms"],
            "entry_open_ms":bars[i].ms,
            "exit_open_ms":bars[exit_i].ms,
            "exit_observable_ms":bars[exit_i].ms+MINUTE,
            "entry_fill":str(entry),"exit_fill":str(exit_px),
            "qty":str(qty),"entry_cash_cost":str(spent),
            "net_pnl_usdt":str(pnl),"exit_reason":exit_reason,
            "hard_stop":str(stop),"take_profit":str(target),
        })
    net=cash-INITIAL_CASH
    return {
        "status":"RESEARCH_CLOSED_TRADES_ONLY_NO_QUALIFICATION",
        "profile":profile,"admitted_round_trips":len(booked),
        "denied_after_signal_count":len(denials),
        "net_pnl_usdt":str(net),
        "mean_pnl_usdt":str(net/len(booked)) if booked else None,
        "ending_cash_usdt":str(cash),
        "original_trade_events":booked,"all_denials":denials,
        "paper_eligible":False,"live_enabled":False,
        "no_minimum_trade_count_gate":True,
    }


def historical_preinspected()->dict:
    """Authenticates original 28 cached July 2024 Binance source days.

    This is not an untouched market test or Bybit historical archive; the
    same source was reviewed in V115/V116. No prospective V117 source access.
    """
    locked,receipt=v90.verify_locked_receipts()
    physical={s:v115.historical_seven_fields(s,locked,receipt) for s in v115.SYMBOLS}
    streams=v115.as_source_streams(physical)
    original={}
    proposals=[]
    classifications=Counter()
    for symbol in v115.SYMBOLS:
        coarse,fine,bars=streams[symbol]
        census=v107.enumerate_event_prefixes(fine,coarse,v90.END_MS)
        original[symbol]={
            "original_window_count":len(census["candidate_ledger"]),
            "strict_v106_necessary_passes":census["necessary_partial_skeleton_passes"],
            "original_coarse_sha256":census["candidate_ledger"][-1]["coarse_window_sha256"]
            if census["candidate_ledger"] else None,
        }
        for row in census["candidate_ledger"]:
            if not row["necessary_partial_skeleton_pass"]:
                continue
            ordinal=row["window_ordinal"]
            decision=find_first_breakout(
                symbol,ordinal,coarse[ordinal:ordinal+6],
                row["decision_asof_ms"],bars,
            )
            classifications[decision["classification"]]+=1
            if decision["classification"]=="CLOSED_WAVE1_BREAKOUT_NEXT_OPEN":
                proposals.append(decision)
    if (sum(x["original_window_count"] for x in original.values())!=1212
        or sum(x["strict_v106_necessary_passes"] for x in original.values())!=9
        or sum(classifications.values())!=9):
        raise ElliottV118Error("source-bound original V116 denominator changed")
    outcomes={p:replay_proposals(proposals,physical,p) for p in PROFILES}
    core={
        "schema":SCHEMA,"source_exchange":"BINANCE_SPOT_NOT_BYBIT",
        "source_period":"2024-07-01_to_2024-07-15_exclusive_UTC",
        "historical_source_preinspected":True,
        "future_nov2026_v117_source_not_accessed":True,
        "v106_original_strict_geometry_unmodified":True,
        "all_original_windows_in_denominator":1212,
        "v106_necessary_passes_not_certified_elliott_waves":9,
        "original_by_symbol":original,
        "preentry_classifications":dict(sorted(classifications.items())),
        "candidate_breakout_intents":len(proposals),
        "fixed_entry":"first_closed_1m_cross_above_original_wave1_within_240m_then_next_open",
        "fixed_preentry_veto":"any_postconfirmation_intrabar_low_at_or_below_original_wave2",
        "fixed_exit":"original_wave2_stop_first_2R_target_or_240m_timeout",
        "fee_slip_per_side_bps":{p:[str(x) for x in costs]
                                 for p,costs in PROFILES.items()},
        "initial_shared_cash_usdt":str(INITIAL_CASH),
        "max_notional_per_entry_usdt":str(MAX_NOTIONAL),
        "max_gapless_nominal_stop_risk_usdt":str(MAX_NOMINAL_STOP_LOSS),
        "no_cash_borrowing":True,
        "costed_outcomes":outcomes,
        "realized_bybit_pnl":None,
        "no_untouched_heldout_profit_claim":True,
        "independent_wave_certification":False,
        "automatic_demo_promotion":False,
        "paper_eligible":False,"live_enabled":False,
        "new_trading_order_count":0,
        "qualification":"DIAGNOSTIC_ONLY_NO_FUTURE_HOLDOUT",
    }
    return {**core,"result_digest":digest(core)}


def write_output(path:Path,data:dict)->None:
    if not isinstance(path,Path) or path.is_symlink():
        raise ElliottV118Error("explicit new non-linked output needed")
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        raise ElliottV118Error("original immutable research result cannot be overwritten")
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf8",newline="\n") as fp:
        fp.write(json.dumps(data,sort_keys=True,indent=2,allow_nan=False)+"\n")
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp,path)


def main()->int:
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    result=historical_preinspected()
    write_output(args.output,result)
    print(json.dumps({
        "source":result["source_exchange"],
        "original_windows":result["all_original_windows_in_denominator"],
        "necessary_passes":result["v106_necessary_passes_not_certified_elliott_waves"],
        "breakout_intents":result["candidate_breakout_intents"],
        "classifications":result["preentry_classifications"],
        "profiles":{p:{k:v for k,v in o.items() if k in (
           "status","admitted_round_trips","net_pnl_usdt","mean_pnl_usdt",
           "denied_after_signal_count")}
           for p,o in result["costed_outcomes"].items()},
        "result_digest":result["result_digest"],
        "automatic_demo_promotion":False,"live_enabled":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
