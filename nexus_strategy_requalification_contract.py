"""Lightweight immutable contract for Strategy proposal runtime requalification.

This module intentionally has no data-science/runtime imports so control-plane
code can validate QA evidence without importing pandas or the research engine.
"""
from __future__ import annotations

REQUALIFICATION_SCHEMA = "nexus.strategy-proposal-runtime-requalification.v1"
REQUALIFICATION_VERIFICATION_SCHEMA = (
    "nexus.strategy-proposal-runtime-requalification-verification.v1"
)
RESEARCH_PROPOSAL_QUEUE_SCHEMA = "nexus.strategy-research-proposal-queue.v1"
APPROVED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
APPROVED_FAMILIES = ("momentum", "trend_breakout", "mean_reversion")
APPROVED_TIMEFRAMES = ("minute15", "hour1", "hour4")
TIMEFRAME_STEP_MS = {
    "minute15": 900_000,
    "hour1": 3_600_000,
    "hour4": 14_400_000,
}
