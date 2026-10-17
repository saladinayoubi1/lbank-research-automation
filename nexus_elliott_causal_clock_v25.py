"""V25 causal clock / actionable-entry honesty gate for Elliott V17/V24.

Pure, research-only temporal feasibility review. A closed candle's price
and its close TIMESTAMP do not establish when source data, an Elliott pivot
signal, or an actual next-open quote became available to the strategy.

In particular, a simulated next-open fill after signal computation is
NOT a broker-executable fill. Never revise V17 historical PNL or choose
an optimal delayed-fill price retrospectively.

No Bybit request, signal routing, Paper or Live orders, hindsight tuning.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Mapping, Sequence

from nexus_elliott_entry_exit_integrity_v24 import audit_single
from nexus_elliott_prospective_exit_v17 import _utc_aligned

RESEARCH_ONLY = True
LIVE_ENABLED = False
AUTO_DEMO = False
PAPER_ELIGIBLE = False
BROKER_FILL_VERIFIED = False
PROSPECTIVE_STRATEGY_REGISTERED = False


def aware_utc_instant(value: object, field: str) -> datetime:
    """Accept subsecond real events, unlike OHLC 15m bar close grids."""
    if not isinstance(value, datetime) or value.tzinfo is None or (
        value.utcoffset() is None
    ):
        raise ValueError(field + " requires timezone-aware instant")
    return value.astimezone(timezone.utc)


def verify_temporal_feasibility(
    observation: Mapping[str, object],
    future_closed_bars: Sequence[Mapping[str, object]],
    *,
    profile: str,
    evaluated_asof_utc: datetime,
    source_received_at_utc: datetime,
    signal_committed_at_utc: datetime,
    entry_quote_received_at_utc: datetime,
    supplied_v17_receipt: Mapping[str, object] | None = None,
) -> dict:
    """Do not mistake an observed backtest opening price for an actionable fill.

    caller-supplied clock receipts are NOT independently timestamp-attested.
    An idealized zero-latency chronology is merely "not disproven by clocks",
    never proof of a real fill or that a source was genuine.
    """
    checked = audit_single(
        observation, future_closed_bars, profile=profile,
        observed_at_utc=evaluated_asof_utc,
        supplied_v17_receipt=supplied_v17_receipt,
    )
    decision = _utc_aligned(observation["decision_close_utc"], "decision close")
    source = aware_utc_instant(source_received_at_utc, "source_received_at")
    signal = aware_utc_instant(signal_committed_at_utc, "signal_committed_at")
    quote = aware_utc_instant(entry_quote_received_at_utc, "entry_quote_received_at")
    evaluated = aware_utc_instant(evaluated_asof_utc, "evaluated_asof")
    if source < decision:
        raise ValueError("source received before source candle was closed")
    if signal < source:
        raise ValueError("signal committed before source close was received")
    if quote < signal:
        raise ValueError("entry quote evidence predates signal commitment")
    if evaluated < quote:
        raise ValueError("future review predates purported entry-quote evidence")
    if not isinstance(future_closed_bars,(tuple,list)) or not future_closed_bars:
        raise ValueError("at least one actual complete future bar required")
    entry_open = _utc_aligned(future_closed_bars[0]["open_at"], "entry open")
    if entry_open != decision:
        raise ValueError("entry open not the fixed next 15m bar boundary")
    if quote < entry_open:
        raise ValueError("entry quote received before next candle opened")
    if signal > entry_open:
        clock_disposition = "SIMULATED_NEXT_OPEN_FILL_PRECEDES_SIGNAL"
    elif quote > entry_open:
        clock_disposition = "SIMULATED_NEXT_OPEN_FILL_PRECEDES_QUOTE_OBSERVATION"
    else:
        clock_disposition = "IDEAL_ZERO_LATENCY_CLOCK_ONLY_NOT_FILL_PROOF"
    # Never claim that the tiny idealized window proves trading/execution.
    # No actual later quote price/volume/size can be derived from 15m OHLC.
    warnings = set(checked["warning_codes"])
    if signal > entry_open:
        warnings.add("SIGNAL_PUBLISHED_AFTER_NEXT_OPEN_NO_RETROACTIVE_FILL")
    if quote > entry_open:
        warnings.add("ENTRY_OPEN_ALREADY_PASSED_WHEN_QUOTE_OBSERVED")
    if source > entry_open:
        warnings.add("BAR_CLOSE_DELIVERY_LATENCY_EXCLUDES_NEXT_OPEN")
    warnings.add("TIMESTAMP_EVIDENCE_CALLER_SUPPLIED_NOT_ATTESTED")
    warnings.add("OHLC_DOES_NOT_PROVE_ACTIONABLE_BID_ASK_OR_MARKET_FILL")
    retained_observation = {
        "event_id":observation["event_id"],"symbol":observation["symbol"],
        "decision_close_utc":decision.isoformat(),
        "fifth_high":str(observation["fifth_high"]),
        "correction_low":str(observation["correction_low"]),
        "decision_close":str(observation["decision_close"]),
        "previous_close":str(observation["previous_close"]),
    }
    obs_digest=sha256(
        json.dumps(retained_observation,sort_keys=True,separators=(",",":")).encode()
    ).hexdigest()
    return {
        "schema":"nexus.elliott-v25-causal-clock-integrity.v1",
        "event_id":checked["event_id"],"symbol":checked["symbol"],
        "profile":profile,
        "frozen_observation_fields_sha256":obs_digest,
        "future_closed_bar_sha256":checked["future_closed_bar_sha256"],
        "decision_close_utc":decision.isoformat(),
        "source_received_at_utc":source.isoformat(),
        "signal_committed_at_utc":signal.isoformat(),
        "entry_quote_received_at_utc":quote.isoformat(),
        "entry_open_at_utc":entry_open.isoformat(),
        "clock_disposition":clock_disposition,
        "next_open_latency_source_seconds":str((source-entry_open).total_seconds()),
        "next_open_latency_signal_seconds":str((signal-entry_open).total_seconds()),
        "next_open_latency_quote_seconds":str((quote-entry_open).total_seconds()),
        "v24_price_only_gate_passed":checked["prospective_price_path_entry_gate_passed"],
        "v24_entry_exit_ledger_reconciled":(
            checked["entry_model_validated"] and checked["exit_model_validated"]
        ),
        "v17_original_hypothetical_status":checked["v17_hypothetical_status_unmodified"],
        "v17_original_hypothetical_net_pnl_not_executable":checked[
            "v17_hypothetical_net_pnl_unmodified"
        ],
        "v17_original_hypothetical_exit_reason":checked[
            "v17_hypothetical_exit_reason_unmodified"
        ],
        "warning_codes":sorted(warnings),
        "decision_and_quote_clock_attestation_independent":False,
        "source_market_authenticity_independently_verified":False,
        "broker_fill_verified":False,
        "may_treat_v17_fill_as_executable":False,
        "may_count_as_profitable_trading_result":False,
        "requires_post_signal_actionable_tick_quote_and_separate_preregistered_fill_rule":True,
        "historical_tuning_or_selective_trades_removed":False,
        "research_only":True,"live_enabled":False,
        "auto_demo":False,"paper_eligible":False,"orders_placed":0,
    }
