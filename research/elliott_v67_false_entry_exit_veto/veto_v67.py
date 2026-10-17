"""V67 retrospective timing veto for false Elliott entries/exits.

Secondary reporting guard only. It cannot authenticate a V66 dictionary
or grant order authority; the source-bound V66 witness remains separate.
Historical five-day Bybit daily archives cannot be used as intraday quotes.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

RESEARCH_ONLY = True
ENTRY_SIGNAL = False
EXIT_SIGNAL = False
PAPER_ELIGIBLE = False
LIVE_ENABLED = False
FILL_CONFIRMED = False
SOURCE_READY_BY_STRUCTURE = False
P_AND_L = None
SCHEMA = "nexus.elliott-v66-history-only-hierarchy-physical-reattest.v1"
SOURCE_SHA = "fbdad48b85ff5ada62c2e12e3321413fdf60ddf5b5655df68d5b60e98c1cdfcf"
V63_SHA = "51d742a3a487e1a416e79e8319df87b2a954075f77d4a455b43a5c67bbac1585"
FIRST_PARENT_CONFIRMED_UTC = "2026-10-10T10:30:00+00:00"
HISTORICAL_CORPUS_COMPLETE_NOT_BEFORE_UTC = "2026-10-13T00:00:00+00:00"

@dataclass(frozen=True)
class RetrospectiveTimingVeto:
    state: str
    proposed_entry_utc: str | None
    proposed_exit_utc: str | None
    required_structural_confirmation_utc: str
    five_day_history_complete_not_before_utc: str
    structure_was_confirmed_at_entry: bool
    five_day_history_could_be_complete_at_entry: bool
    accepted_hierarchical_geometry: bool
    entry_signal: bool = False
    exit_signal: bool = False
    paper_eligible: bool = False
    live_enabled: bool = False
    fill_confirmed: bool = False
    pnl: None = None

def _utc(when: Any) -> datetime:
    if isinstance(when, str):
        try:
            stamp = datetime.fromisoformat(when.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("INVALID_CLAIM_TIMESTAMP") from exc
    elif isinstance(when, datetime):
        stamp = when
    else:
        raise ValueError("INVALID_CLAIM_TIMESTAMP")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("UTC_AWARE_TIMESTAMP_REQUIRED")
    return stamp.astimezone(timezone.utc)

def _check_historical_report(report: Mapping[str, Any]) -> datetime:
    if not isinstance(report, Mapping):
        raise ValueError("V66_HISTORICAL_WITNESS_REQUIRED")
    if (report.get("schema") != SCHEMA or
        report.get("verified_source_sha256") != SOURCE_SHA or
        report.get("verified_v63_receipt_sha256") != V63_SHA):
        raise ValueError("V66_RECEIPT_METADATA_MISMATCH")
    if (report.get("confirmed_1m_count") != 8 or
        report.get("confirmed_3m_interior_count") != 6 or
        report.get("confirmed_15m_parent_count") != 2 or
        report.get("physically_attested_historical_vertices") is not True):
        raise ValueError("V66_STRUCTURAL_METADATA_MISMATCH")
    if (report.get("geometry_valid_expansions") != 0 or
        report.get("geometry_state") != "NO_ADMISSIBLE_5_PLUS_ABC_GEOMETRY"):
        raise ValueError("V66_HISTORICALLY_REJECTED_GEOMETRY_MISMATCH")
    for flag in ("entry_signal","paper_eligible","live_enabled",
                 "executable_quote_proof","source_archive_accessible_at_structural_time"):
        if report.get(flag) is not False:
            raise ValueError("V66_NONTRADING_CONSTRAINT_VIOLATION")
    if report.get("pnl","ABSENT") is not None:
        raise ValueError("V66_PNL_MUST_BE_NULL")
    structure = _utc(report.get("first_structural_pivot_decision_not_before_utc"))
    required = _utc(FIRST_PARENT_CONFIRMED_UTC)
    if structure != required:
        raise ValueError("V66_STRUCTURAL_CLOCK_NOT_PINNED")
    return structure

def audit_retrospective_claim(
    witness: Mapping[str, Any],
    *,
    proposed_entry_utc: str | datetime | None = None,
    proposed_exit_utc: str | datetime | None = None,
) -> RetrospectiveTimingVeto:
    """Never returns trade eligibility. Each reason is a retrospective veto.

    Real-source authentication requires independent V66 physical file/hashes;
    this secondary pure function only examines already-attested metadata and
    cannot turn an OHLC pivot into an executable entry or a booked trade.
    """
    structural = _check_historical_report(witness)
    history_end = _utc(HISTORICAL_CORPUS_COMPLETE_NOT_BEFORE_UTC)
    if proposed_entry_utc is None:
        if proposed_exit_utc is not None:
            raise ValueError("EXIT_WITHOUT_ENTRY_CLAIM")
        return RetrospectiveTimingVeto(
            "NO_TRADE_CLAIM",None,None,structural.isoformat(),history_end.isoformat(),
            False,False,False)
    entry = _utc(proposed_entry_utc)
    exit_at = _utc(proposed_exit_utc) if proposed_exit_utc is not None else None
    if exit_at is not None and exit_at <= entry:
        state = "INVALID_ENTRY_EXIT_CHRONOLOGY"
    elif entry < structural:
        state = "REJECT_BACKDATED_BEFORE_PARENT_RIGHT_CONFIRMATION"
    elif entry < history_end:
        state = "REJECT_UNFINISHED_HISTORICAL_ARCHIVE_AS_INTRADAY_SOURCE"
    else:
        state = "REJECT_UNVALIDATED_WAVE_WITH_NO_EXECUTABLE_QUOTE_OR_FILL"
    return RetrospectiveTimingVeto(
        state,entry.isoformat(),exit_at.isoformat() if exit_at else None,
        structural.isoformat(),history_end.isoformat(),
        entry >= structural,entry >= history_end,False)
