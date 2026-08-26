"""Explicitly isolated ProductRuntime account for regime-selected Paper lanes.

The default ProductRuntime contract remains unchanged.  This adapter exists only
for the multi-strategy regime runtime, whose verifier requires every selected
lane to own a distinct Paper aggregate.  It has no Live authority.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from paper_event_store import GENESIS_DIGEST, build_event, replay
from product_runtime import (
    PAPER_CURRENCY,
    ProductRuntime,
    ProductRuntimeError,
    _paper_provenance,
)

# Derived event/correlation/causation identifiers add bounded suffixes and the
# Paper event envelope caps every identifier at 128 characters.
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,95}$")


class IsolatedProductRuntime(ProductRuntime):
    """ProductRuntime with an explicitly bound, distinct Paper aggregate id."""

    def __init__(
        self,
        root: Path,
        *,
        account_id: str,
        opening_cash: str = "10000",
        clock: Callable[[], str] | None = None,
    ) -> None:
        account_id = str(account_id).strip()
        if not _ACCOUNT_RE.fullmatch(account_id):
            raise ProductRuntimeError("isolated Paper account_id is invalid or unbounded")
        self.account_id = account_id
        super().__init__(root, opening_cash=opening_cash, clock=clock)

    def _ensure_account(self) -> list[dict]:
        events = self._read_events()
        if events:
            state = replay(events).state
            if state.aggregate_id != self.account_id:
                raise ProductRuntimeError("isolated Paper journal aggregate binding mismatch")
            return events

        at = self.clock()
        provenance = _paper_provenance(timeframe="session", at=at)
        correlation = f"{self.account_id}:bootstrap"
        account = build_event(
            event_id=f"{self.account_id}:account:1",
            event_type="demo_account_opened",
            aggregate_id=self.account_id,
            sequence=1,
            occurred_at=at,
            correlation_id=correlation,
            causation_id=f"{self.account_id}:bootstrap-account",
            provenance=provenance,
            previous_event_digest=GENESIS_DIGEST,
            payload={"currency": PAPER_CURRENCY, "opening_cash": self.opening_cash},
        )
        session = build_event(
            event_id=f"{self.account_id}:account:2",
            event_type="session_boundary_recorded",
            aggregate_id=self.account_id,
            sequence=2,
            occurred_at=at,
            correlation_id=correlation,
            causation_id=f"{self.account_id}:bootstrap-session",
            provenance=provenance,
            previous_event_digest=account["event_digest"],
            payload={"boundary": "open"},
        )
        events = [account, session]
        self._write_events(events)
        return events


def regime_paper_account_id(*, symbol: str, timeframe: str, family: str) -> str:
    """Return the canonical bounded aggregate id for one selected Demo lane."""
    symbol = str(symbol).strip().lower()
    timeframe = str(timeframe).strip().lower()
    family = str(family).strip().lower()
    value = f"nexus-regime-demo:{symbol}:{timeframe}:{family}"
    if not _ACCOUNT_RE.fullmatch(value):
        raise ProductRuntimeError("regime Paper account identity is invalid or unbounded")
    return value
