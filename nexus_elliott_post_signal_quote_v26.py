"""V26 Elliott post-signal Spot quote admission diagnostic (no orders or fills).

This is a DIFFERENT research contract than V17's frozen next-OPEN, and
must never revise, filter or relabel inspected V17 trades or backtest PNL.
It accepts neither later completed OHLCs nor future outcome information.

All quote timestamps/prices are supplied by caller and NOT independently
provider-attested; an observed ask is NOT a guaranteed execution price.
No network, private API, signal dispatch, Paper/Demo/Live or outcome PNL.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from typing import Mapping

from nexus_elliott_causal_clock_v25 import aware_utc_instant
from nexus_elliott_prospective_exit_v17 import (
    FORWARD_START_UTC, FORWARD_END_UTC, MAX_REWARD_RISK,
    PROFILES, _decimal, _utc_aligned
)

RESEARCH_ONLY=True
LIVE_ENABLED=False
AUTO_DEMO=False
PAPER_ELIGIBLE=False
BROKER_ORDER_AUTHORITY=False
BROKER_FILL_VERIFIED=False
SOURCE_AND_QUOTE_ATTESTED=False
MAX_QUOTE_DELIVERY_LAG=timedelta(seconds=2)  # fixed ex ante, NOT PNL-tuned
NEXT_CANDLE_DURATION=timedelta(minutes=15)


def assess_quote_only(
    observation: Mapping[str,object],
    quote: Mapping[str,object],
    *,
    profile: str,
    source_received_at_utc: datetime,
    signal_committed_at_utc: datetime,
    examined_at_utc: datetime,
) -> dict:
    """Audit one price quote recorded after a confirmed closed-bar decision.

    There is no exit simulation here. The quote is not inferred from 15m OPEN
    and no future bar is accepted or inspected. The two-second delivery lag
    is a preregistered reliability *screen*, not a profitability threshold.
    """
    if profile not in PROFILES:
        raise ValueError("unsupported preregistered cost profile")
    if not isinstance(observation,Mapping) or not isinstance(quote,Mapping):
        raise ValueError("observation and quote must be maps")
    allowed_quote_keys={
        "symbol","venue","category","best_bid","best_ask",
        "market_quoted_at_utc","client_received_at_utc"
    }
    if set(quote)!=allowed_quote_keys:
        raise ValueError("quote missing required fields or contains unapproved future/side-channel data")
    if quote.get("venue")!="Bybit" or quote.get("category")!="spot":
        raise ValueError("only Bybit spot quote envelope is permitted")
    symbol=observation.get("symbol")
    event_id=observation.get("event_id")
    if symbol not in ("BTCUSDT","ETHUSDT") or (
        not isinstance(event_id,str) or not event_id.strip()
    ):
        raise ValueError("unsupported Bybit pair or event identity")
    if observation.get("source_bound_seven_pivot") is not True or (
        observation.get("closed_first_breakout") is not True
    ) or observation.get("post_correction_path_valid") is not True:
        raise ValueError("causal seven-pivot claim absent; independent source proof still needed")
    decision=_utc_aligned(observation.get("decision_close_utc"),"closed decision")
    if not FORWARD_START_UTC<=decision<FORWARD_END_UTC:
        raise ValueError("outside fixed future research observation window")
    before=_decimal(observation.get("previous_close"),"previous close")
    signal_close=_decimal(observation.get("decision_close"),"decision close")
    high=_decimal(observation.get("fifth_high"),"fifth pivot high")
    correction=_decimal(observation.get("correction_low"),"correction low")
    if not before<=high<signal_close or not correction<high:
        raise ValueError("no first-closed breakout or valid correction geometry")
    if quote.get("symbol")!=symbol:
        raise ValueError("quote source symbol mismatches event")
    bid=_decimal(quote.get("best_bid"),"best bid")
    ask=_decimal(quote.get("best_ask"),"best ask")
    if bid>=ask:
        raise ValueError("crossed/locked/invalid order book; must have bid < ask")
    source=aware_utc_instant(source_received_at_utc,"closed source receipt")
    signal=aware_utc_instant(signal_committed_at_utc,"signal commit")
    quoted=aware_utc_instant(quote.get("market_quoted_at_utc"),"market quote time")
    received=aware_utc_instant(quote.get("client_received_at_utc"),"quote receipt time")
    asof=aware_utc_instant(examined_at_utc,"current review time")
    if source<decision:
        raise ValueError("source received before decision candle closed")
    if signal<source:
        raise ValueError("signal before closed candle source received")
    if quoted<signal:
        raise ValueError("market quote timestamp precedes signal commitment")
    if received<quoted:
        raise ValueError("client receipt precedes market quote timestamp")
    if asof<received:
        raise ValueError("quote receipt lies in the future of review")
    # Quote must belong to the first candle after decision; no use of
    # quotes from the next-next candle and no later closed outcome evidence.
    if received>=decision+NEXT_CANDLE_DURATION or (
        asof>=decision+NEXT_CANDLE_DURATION
    ):
        raise ValueError("quote/review after next 15m entry-window closure")
    lag=received-quoted
    if lag>MAX_QUOTE_DELIVERY_LAG:
        state="REJECT_STALE_QUOTE_DELIVERY"
    elif bid<=high:
        # A wide spread with ASK alone above high is NOT continued breakout
        # confirmation and must not be called a buyable breakout.
        state="REJECT_BID_NOT_ABOVE_FIFTH_PIVOT_HIGH"
    elif bid<=correction:
        state="REJECT_BID_AT_OR_BELOW_CORRECTION"
    else:
        state="ADVISORY_QUOTED_PRICE_PATH_ONLY_NOT_EXECUTABLE"
    with localcontext() as ctx:
        ctx.prec=46
        fee=PROFILES[profile]["fee_bps"]/Decimal("10000")
        slip=PROFILES[profile]["slip_bps"]/Decimal("10000")
        conservative_buy_reference=ask*(1+slip)
        risk=conservative_buy_reference-correction
        if risk<=0:
            state="REJECT_INVALID_QUOTED_STRUCTURAL_RISK"
        if risk>0 and state=="ADVISORY_QUOTED_PRICE_PATH_ONLY_NOT_EXECUTABLE":
            hypothetical_target=conservative_buy_reference+MAX_REWARD_RISK*risk
            after_cost_target=hypothetical_target*(1-slip)*(1-fee)-conservative_buy_reference*(1+fee)
            after_cost_stop=correction*(1-slip)*(1-fee)-conservative_buy_reference*(1+fee)
        else:
            hypothetical_target=None
            after_cost_target=None
            after_cost_stop=None
        canonical={
            "event_id":event_id, "symbol":symbol,"profile":profile,
            "decision_close_utc":decision.isoformat(),
            "signal_commit_utc":signal.isoformat(),
            "source_received_utc":source.isoformat(),
            "market_quote_utc":quoted.isoformat(),
            "client_received_utc":received.isoformat(),
            "best_bid":str(bid),"best_ask":str(ask),
            "fifth_high":str(high),"correction_low":str(correction),
        }
        receipt_sha=sha256(
            json.dumps(canonical,sort_keys=True,separators=(",",":")).encode()
        ).hexdigest()
        return {
            "schema":"nexus.elliott-v26-post-signal-quote-only.v1",
            "disposition":state,"symbol":symbol,"event_id":event_id,
            "profile":profile,"quote_and_decision_sha256":receipt_sha,
            "quote_delivery_lag_ms":str(Decimal(str(lag.total_seconds()))*1000),
            "signal_to_quote_ms":str(Decimal(str((quoted-signal).total_seconds()))*1000),
            "next_open_was_not_retroactively_assumed":True,
            "market_quote_timestamp_independently_attested":False,
            "price_quote_independently_provider_attested":False,
            "actual_actionable_quantity_available_not_proven":True,
            "bid_above_breakout_high":bid>high,
            "raw_best_bid":str(bid),"raw_best_ask":str(ask),
            "raw_spread_bps":str((ask-bid)/((bid+ask)/2)*Decimal("10000")),
            "cost_profile_fee_bps":str(PROFILES[profile]["fee_bps"]),
            "cost_profile_slippage_bps":str(PROFILES[profile]["slip_bps"]),
            "quote_ask_plus_frozen_profile_slippage_reference":str(conservative_buy_reference),
            "nominal_risk_per_unit_research_only":str(risk) if risk>0 else None,
            "nominal_target_2r_research_only":str(hypothetical_target) if hypothetical_target is not None else None,
            "conditional_target_net_per_unit_not_observed":str(after_cost_target) if after_cost_target is not None else None,
            "conditional_stop_net_per_unit_not_observed":str(after_cost_stop) if after_cost_stop is not None else None,
            "actual_position_filled":False,
            "exit_bars_consulted":0,
            "observed_trade_pnl":None,
            "promotable_to_demo":False,
            "recursive_elliott_count_proven":False,
            "research_only":True,"live_enabled":False,"auto_demo":False,
            "paper_eligible":False,"entry_signal":False,"orders_placed":0,
        }
