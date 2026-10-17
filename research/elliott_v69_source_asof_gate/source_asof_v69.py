"""V69 source-availability gate: physical V59 -> V60 -> V53 provenance.

Never score an archive as if it were accessible at an earlier UTC decision.
Rescans real physical V58/V56 receipts, original raw gzip, and raw-to-1m
parquet through V59/V57/V52 BEFORE inspecting V60 receipt-stage timestamps.
Pure offline research; no trading, entry/exit, P/L or deployment capabilities.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import pandas as pd
from prospective_v52 import ProspectiveGateError, read_frozen_protocol
from trace_capture_v59 import scan_tls_bound_physical_source
from observability_v60 import audit_source_observability

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
EXIT_SIGNAL=False
PAPER_ELIGIBLE=False
AUTO_DEMO=False
LIVE_ENABLED=False
FILL_CONFIRMED=False
PNL=None

@dataclass(frozen=True)
class AsOfSourceVeto:
    symbol:str
    decision_close_utc:str
    state:str
    source_days:int
    physical_raw_archives_reverified:bool
    raw_to_minute_scanner_reverified:bool
    fixture_mode:bool
    actual_source_available_by_decision:bool
    earliest_physical_source_ready_utc:str
    availability_lag_seconds:int
    independent_origin_exchange_signature:bool=False
    research_asof_reporting_eligible:bool=False
    entry_signal:bool=False
    exit_signal:bool=False
    paper_eligible:bool=False
    live_enabled:bool=False
    fill_confirmed:bool=False
    pnl:None=None

def audit_scanned_daily_source_availability(
    symbol:str,
    tls_receipt_paths:Sequence[Path],
    minute_receipt_paths:Sequence[Path],
    *,
    decision_close_utc,
    fixture_mode:bool=False,
    observed_utc=None,
)->AsOfSourceVeto:
    """Rebuild capture->minute->scan chain from bytes, then classify arrival.

    Actual market evidence can NEVER use an injected wall clock or synthetic
    fixture. Timely delivery only permits *research as-of reporting* and NEVER
    provides an entry, fill, executable quote, or a remotely signed source.
    """
    read_frozen_protocol()
    chain=scan_tls_bound_physical_source(
        symbol,tls_receipt_paths,minute_receipt_paths,
        decision_close_utc=decision_close_utc,
        fixture_mode=fixture_mode,observed_utc=observed_utc)
    observed=audit_source_observability(
        chain,tls_receipt_paths,minute_receipt_paths)
    scan=chain.scanner
    if (chain.symbol!=symbol or scan.symbol!=symbol or
        chain.decision_close_utc!=scan.decision_close_utc or
        chain.decision_close_utc!=observed.claimed_decision_close_utc or
        chain.complete_verified_source_days!=scan.physical_independently_verified_days or
        scan.scan.decision_close_utc!=chain.decision_close_utc or
        scan.scan.symbol!=symbol or
        scan.scan.verified_days!=chain.complete_verified_source_days):
        raise ProspectiveGateError("V69_PHYSICAL_SCAN_IDENTITY_DISAGREEMENT")
    if (chain.trade_entry_enabled or chain.paper_eligible or chain.live_enabled or
        scan.entry_signal or scan.paper_eligible or scan.live_enabled or
        scan.scan.entry_signal or scan.scan.paper_eligible or scan.scan.live_enabled or
        chain.new_pnl is not None):
        raise ProspectiveGateError("V69_RESEARCH_ONLY_CHAIN_VIOLATED")
    if not observed.physical_source_timing_consistent:
        state="BLOCK_INVALID_SOURCE_STAGE_CHRONOLOGY"
    elif not observed.physically_available_by_decision:
        state="BLOCK_RETROSPECTIVE_SOURCE_ARRIVED_AFTER_DECISION"
    elif fixture_mode:
        state="SYNTHETIC_SOURCE_ONLY_NO_REAL_SCORE"
    else:
        state="PHYSICAL_SOURCE_READY_BY_DECISION_RESEARCH_ONLY"
    asof=(not fixture_mode and observed.physical_source_timing_consistent
          and observed.physically_available_by_decision)
    return AsOfSourceVeto(
        symbol,chain.decision_close_utc,state,
        chain.complete_verified_source_days,True,True,fixture_mode,
        observed.physically_available_by_decision,
        observed.physical_data_available_utc,
        observed.availability_lag_seconds,
        research_asof_reporting_eligible=asof)
