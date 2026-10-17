"""V17 immutable-contract forward Elliott exit QA: research-only, no orders.

Only evaluate a PRE-REGISTERED, future UTC 15m observation. Bar timestamps
mean OPEN and must already be CLOSED at the supplied observation timestamp.
Never backtest inspected history, fetch an exchange, emit trade instructions,
register a strategy, or modify a Paper/Live wallet.

This is a LIMITED-seven-pivot study contract, not verified recursive Elliott.
Source-bound pivot validation is an upstream prerequisite but is not repeated
inside this small independent next-open/exit mathematics model.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
from typing import Mapping, Sequence

RESEARCH_ONLY = True
AUTO_DEMO = False
LIVE_ENABLED = False
ENTRY_SIGNAL = False
PAPER_ELIGIBLE = False
COMPLETE_RECURSIVE_ELLIOTT_COUNT = False

# Frozen for prospective sampling while the historical v9 / five-swing /
# ABC folds are already inspected. The cutoff cannot be tuned after seeing P/L.
FORWARD_START_UTC = datetime(2026, 10, 16, tzinfo=timezone.utc)
FORWARD_END_UTC = datetime(2026, 11, 16, tzinfo=timezone.utc)
MAX_HOLD_BARS = 64
MAX_REWARD_RISK = Decimal("2")
REFERENCE_CELL_CASH = Decimal("10000")
MAX_POSITION_FRACTION = Decimal("0.10")
MAX_STOP_RISK_FRACTION = Decimal("0.001")
PROFILES = {
    "conservative": {"fee_bps": Decimal("10"), "slip_bps": Decimal("5")},
    "stress": {"fee_bps": Decimal("25"), "slip_bps": Decimal("15")},
}
CANDLE_MINUTES = 15


def _decimal(value: object, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(field+" must be a finite positive Decimal")
    try:
        value = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError(field+" must be a finite positive Decimal") from exc
    if not value.is_finite() or value <= 0:
        raise ValueError(field+" must be a finite positive Decimal")
    return value


def _utc_aligned(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(field+" requires aware UTC/offset datetime")
    normalized = value.astimezone(timezone.utc)
    if normalized.second or normalized.microsecond or normalized.minute % CANDLE_MINUTES:
        raise ValueError(field+" must be on completed 15m UTC grid")
    return normalized


def _validated_bars(
    bars: Sequence[Mapping[str, object]],
    first_open: datetime,
    observed_at: datetime,
) -> tuple[tuple[dict, ...], str]:
    if not isinstance(bars, (tuple, list)) or not 1 <= len(bars) <= MAX_HOLD_BARS:
        raise ValueError("between 1 and 64 consecutive completed future 15m candles required")
    parsed = []
    for index, bar in enumerate(bars):
        if not isinstance(bar, Mapping) or not {"open_at","open","high","low","close"} <= set(bar):
            raise ValueError("future candle missing timestamp/OHLC")
        stamp = _utc_aligned(bar["open_at"], "future open_at")
        expected = first_open + timedelta(minutes=index*CANDLE_MINUTES)
        if stamp != expected:
            raise ValueError("future candles not exact contiguous next OPEN sequence")
        if stamp + timedelta(minutes=CANDLE_MINUTES) > observed_at:
            raise ValueError("forming/unavailable future candle prohibited")
        op = _decimal(bar["open"], "open")
        high = _decimal(bar["high"], "high")
        low = _decimal(bar["low"], "low")
        close = _decimal(bar["close"], "close")
        if high < max(op,low,close) or low > min(op,high,close):
            raise ValueError("future candle OHLC inconsistent")
        parsed.append({"open_at":stamp.isoformat(),
                       "open":str(op),"high":str(high),"low":str(low),"close":str(close)})
    canonical = json.dumps(parsed, sort_keys=True, separators=(",",":"),
                           ensure_ascii=True).encode("utf-8")
    return tuple(parsed), sha256(canonical).hexdigest()


def evaluate_prospective_study(
    observation: Mapping[str, object],
    future_closed_bars: Sequence[Mapping[str, object]],
    *,
    profile: str,
    observed_at_utc: datetime,
) -> dict:
    """One bounded event. All actual outcomes require complete FUTURE data.

    observation is registered from V14/V15, never from past fit results.
    Only the fixed predefined future cutoff is admissible. If fewer than
    64 complete bars and neither bracket level has been hit, return PENDING
    without fabricating an exit. Same-bar stop/target ambiguity resolves
    against the study. Close-to-next-OPEN entry, no favorable gap exits.
    """
    if profile not in PROFILES:
        raise ValueError("unregistered friction profile")
    if not isinstance(observation, Mapping):
        raise ValueError("observation must be source-certifier record")
    event_id=observation.get("event_id")
    symbol=observation.get("symbol")
    if not isinstance(event_id,str) or not event_id or symbol not in ("BTCUSDT","ETHUSDT"):
        raise ValueError("invalid fixed prospective event ID/symbol")
    if observation.get("source_bound_seven_pivot") is not True or (
        observation.get("closed_first_breakout") is not True
    ) or observation.get("post_correction_path_valid") is not True:
        raise ValueError("V14/V15 causal source-bound eligibility missing")
    decision = _utc_aligned(observation.get("decision_close_utc"),"decision close")
    seen = _utc_aligned(observed_at_utc,"current observation time")
    if decision < FORWARD_START_UTC:
        raise ValueError("historically inspected period excluded from forward evaluator")
    if decision >= FORWARD_END_UTC:
        raise ValueError("new observation outside preregistered forward month")
    if seen < decision + timedelta(minutes=CANDLE_MINUTES):
        raise ValueError("no completely observed entry candle yet")
    prev_close=_decimal(observation.get("previous_close"),"previous close")
    last_close=_decimal(observation.get("decision_close"),"decision close price")
    fifth_high=_decimal(observation.get("fifth_high"),"fifth high")
    correction=_decimal(observation.get("correction_low"),"correction low")
    if not (prev_close <= fifth_high < last_close and correction < last_close):
        raise ValueError("no valid first CLOSED breakout or structural low")
    bars,digest=_validated_bars(future_closed_bars,decision,seen)
    friction=PROFILES[profile]
    with localcontext() as ctx:
        ctx.prec=46
        bps=Decimal("10000")
        fee=friction["fee_bps"]/bps
        slip=friction["slip_bps"]/bps
        first_open=Decimal(bars[0]["open"])
        out={
            "schema":"nexus.v17.prospective-15m-single-entry-qa.v1",
            "event_id":event_id, "symbol":symbol,"profile":profile,
            "decision_close_utc":decision.isoformat(),
            "asof_utc":seen.isoformat(),
            "future_closed_bar_sha256":digest,
            "completed_bar_count":len(bars),
            "research_only":True,"live_enabled":False,"auto_demo":False,
            "entry_signal":False,"paper_eligible":False,
            "complete_recursive_elliott_count":False,
            "source_bound_claim_from_caller_not_reverified":True,
            "real_broker_fill_verified":False,
            "hypothetical_simulator_only":True,
            "orders_placed":0,"fee_bps_per_leg":str(friction["fee_bps"]),
            "slippage_bps_per_leg":str(friction["slip_bps"]),
        }
        if first_open <= correction:
            return {**out,"status":"NO_ENTRY_OPEN_AT_OR_BELOW_CORRECTION",
                    "filled":False,"exit_reason":None,"net_pnl":None}
        entry=first_open*(1+slip)
        distance=entry-correction
        if distance <= 0:
            raise AssertionError("bad structural risk")
        target=entry+MAX_REWARD_RISK*distance
        quantity=min(
            REFERENCE_CELL_CASH*MAX_STOP_RISK_FRACTION/distance,
            REFERENCE_CELL_CASH*MAX_POSITION_FRACTION/(entry*(1+fee)),
        )
        if not quantity > 0:
            raise AssertionError("zero hypothetical nonborrowed quantity")
        entry_fee=entry*quantity*fee
        worst_low=None
        best_high=None
        outcome=None
        # Entry-bar extremes included. Even when stop/target is touched,
        # intrabar sequence is unknown, so full candle extrema are NOT
        # claimed as exact realized MFE/MAE.
        for pos, b in enumerate(bars):
            op=Decimal(b["open"])
            low=Decimal(b["low"])
            high=Decimal(b["high"])
            close=Decimal(b["close"])
            worst_low=low if worst_low is None else min(worst_low,low)
            best_high=high if best_high is None else max(best_high,high)
            if low <= correction:
                ref=min(op,correction)  # open gap below stop is adverse
                reason="stop"
                ambiguous=high >= target
            elif high >= target:
                ref=target  # positive open gap not assumed beneficial
                reason="target"
                ambiguous=False
            elif pos==MAX_HOLD_BARS-1:
                ref=close
                reason="time_limit"
                ambiguous=False
            else:
                continue
            exit_price=ref*(1-slip)
            exit_fee=quantity*exit_price*fee
            net=quantity*(exit_price-entry)-entry_fee-exit_fee
            outcome={
                "status":"EXITED","filled":True,
                "entry_reference":str(first_open),"entry":str(entry),
                "structural_stop":str(correction),"target":str(target),
                "quantity":str(quantity),"reference_cell_usdt":str(REFERENCE_CELL_CASH),
                "entry_fee":str(entry_fee),"exit_fee":str(exit_fee),
                "exit_reference":str(ref),"exit_price":str(exit_price),
                "exit_reason":reason,
                "exit_bar_index_after_entry":pos,
                "exit_close_utc":(decision+timedelta(minutes=(pos+1)*CANDLE_MINUTES)).isoformat(),
                "both_levels_touched_stop_first":ambiguous,
                "net_pnl":str(net),
                "observed_bar_extremes_mae_mfe_not_exact_executed_excursion":{
                    "lowest_low_vs_entry":str(worst_low-entry),
                    "highest_high_vs_entry":str(best_high-entry),
                    "intrabar_order_unknown":True,
                },
            }
            break
        if outcome is None:
            return {**out,"status":"AWAITING_MORE_CLOSED_BARS",
                    "filled":True,"entry_reference":str(first_open),
                    "entry":str(entry),"quantity":str(quantity),
                    "structural_stop":str(correction),"target":str(target),
                    "exit_reason":None,"net_pnl":None}
        return {**out,**outcome}
