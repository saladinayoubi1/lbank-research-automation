"""MR40 deterministic research event coordinator — NO order transport, NO fills.

Receives already-computed, CLOSED-bar MR40 signals. It only emits descriptive
intent/event markers for a future offline simulator; no exchange integration.
See research/mr40_entry_event_contract_protocol_20261022.json.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


def dec(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite_market_value")
    return result


@dataclass(frozen=True)
class Position:
    entry_price: Decimal
    quantity: Decimal
    stop_price: Optional[Decimal] = None

    def __post_init__(self):
        if dec(self.entry_price) <= 0 or dec(self.quantity) <= 0:
            raise ValueError("invalid_position")
        if self.stop_price is not None and dec(self.stop_price) <= 0:
            raise ValueError("invalid_stop")


@dataclass(frozen=True)
class Event:
    kind: str
    index: int
    reference_price: Optional[Decimal] = None
    note: str = ""

    # Only markers; never an executable order.
    @property
    def executable(self):
        return False


class EntryEventCoordinator:
    """Three-phase bar clock: open() -> optional low_touch() -> close().

    The API deliberately prevents current candle LOW from being passed to open()
    and prevents a signal from being evaluated until close(confirmed=True).
    No order, fill, PnL, optimization, or exchange calls are implemented.
    """

    def __init__(self, arm2_gross_entry_stop=False):
        self.arm2 = bool(arm2_gross_entry_stop)
        self.episode_latched = False
        self.pending_entry_for = None
        self.pending_natural_exit_for = None
        self.gross_entry_stop_floor = None
        self.arm_at_next_open = None
        self.await_entry_ack = False
        self.await_exit_ack = False
        self.last_open_index = None
        self.last_close_index = None
        self.last_open_price = None
        self.current_effective_stop = None
        self.current_data_ok = False
        self.bad_data_latched = False

    def _block(self, index, reason):
        self.pending_entry_for = None
        self.pending_natural_exit_for = None
        self.arm_at_next_open = None
        self.bad_data_latched = True
        self.episode_latched = True
        self.current_data_ok = False
        return Event("DATA_BLOCK", index, note=reason)

    def open(self, index, open_price, position=None, source_ok=True):
        """Apply only state known before this bar begins."""
        if not isinstance(index, int) or index < 0:
            raise ValueError("bad_bar_index")
        if self.last_open_index is not None and index != self.last_open_index + 1:
            return self._block(index, "missing_or_nonmonotonic_bar")
        if self.last_open_index is not None and self.last_close_index != self.last_open_index:
            return self._block(index, "previous_bar_not_closed")
        self.last_open_index = index
        self.current_data_ok = bool(source_ok)
        try:
            px = dec(open_price)
        except (TypeError, ValueError, ArithmeticError):
            return self._block(index, "bad_open")
        if not source_ok or px <= 0:
            return self._block(index, "source_not_verified_or_invalid_open")
        self.last_open_price = px

        if position is None:
            self.await_exit_ack = False
            self.gross_entry_stop_floor = None
            self.arm_at_next_open = None
            self.current_effective_stop = None
        else:
            self.await_entry_ack = False
            stop = position.stop_price
            if self.arm_at_next_open is not None:
                self.gross_entry_stop_floor = max(
                    self.gross_entry_stop_floor or self.arm_at_next_open,
                    self.arm_at_next_open,
                )
                self.arm_at_next_open = None
            if self.gross_entry_stop_floor is not None:
                stop = max(dec(stop), self.gross_entry_stop_floor) if stop is not None else self.gross_entry_stop_floor
            self.current_effective_stop = dec(stop) if stop is not None else None

        if self.bad_data_latched:
            return Event("DATA_BLOCK", index, note="await_closed_reset_after_gap")
        if position is not None:
            if self.await_exit_ack:
                return Event("AWAIT_EXIT_ACK", index)
            if self.pending_natural_exit_for == index:
                self.pending_natural_exit_for = None
                self.await_exit_ack = True
                return Event("NATURAL_EXIT_NEXT_OPEN", index, px, "research_marker_only")
            if self.current_effective_stop is not None and px <= self.current_effective_stop:
                self.await_exit_ack = True
                return Event("GAP_BELOW_STOP_OPEN", index, px, "unverified_fill")
            return Event("HOLD", index)
        else:
            self.pending_natural_exit_for = None
            if self.await_entry_ack:
                return Event("AWAIT_ENTRY_ACK", index)
            if self.pending_entry_for == index:
                self.pending_entry_for = None
                self.await_entry_ack = True
                return Event("ENTRY_NEXT_OPEN", index, px, "unverified_fill")
            self.pending_entry_for = None
            return Event("FLAT", index)

    def low_touch(self, index, low_price, position=None, source_ok=True):
        """Intrabar historical LOW is never treated as an actual fill."""
        if index != self.last_open_index or not self.current_data_ok or not source_ok:
            return self._block(index, "missing_open_or_invalid_intrabar_source")
        try:
            low = dec(low_price)
        except (TypeError, ValueError, ArithmeticError):
            return self._block(index, "invalid_low")
        if low <= 0 or low > self.last_open_price:
            return self._block(index, "inconsistent_intrabar_low")
        if position is None or self.await_exit_ack or self.bad_data_latched:
            return Event("NO_INTRABAR_EXIT", index)
        stop = self.current_effective_stop
        if stop is not None and low <= stop:
            self.await_exit_ack = True
            return Event("STOP_LOW_TOUCHED_UNVERIFIED_FILL", index, stop,
                         "OHLC_does_not_prove_fill_at_stop")
        return Event("NO_INTRABAR_EXIT", index)

    def close(self, index, close_price, entry_signal, exit_signal, position=None,
              *, high_price, low_price, confirmed=False, source_ok=True, quality_allowed=True):
        """Only CLOSED-bar predicates queue next-open intents (no immediate trades)."""
        if index != self.last_open_index:
            return self._block(index, "close_not_matching_open")
        if self.last_close_index == index:
            raise ValueError("duplicate_close")
        self.last_close_index = index
        if not confirmed or not source_ok or not self.current_data_ok:
            return self._block(index, "unconfirmed_or_invalid_close")
        try:
            px = dec(close_price)
        except (TypeError, ValueError, ArithmeticError):
            return self._block(index, "bad_close")
        try:
            hi, lo = dec(high_price), dec(low_price)
        except (TypeError, ValueError, ArithmeticError):
            return self._block(index, "invalid_closed_ohlc")
        if (px <= 0 or hi <= 0 or lo <= 0 or self.last_open_price is None
                or hi < max(self.last_open_price, px)
                or lo > min(self.last_open_price, px)
                or lo > hi):
            return self._block(index, "inconsistent_closed_ohlc")

        # Verified neutral signal after data outage releases suspension.
        if self.bad_data_latched:
            if entry_signal:
                return Event("DATA_BLOCK", index, note="first_neutral_episode_required")
            self.bad_data_latched = False
            self.episode_latched = False
            return Event("NEUTRAL_RESET", index)

        if not entry_signal:
            self.episode_latched = False
        elif not self.episode_latched:
            self.episode_latched = True
            if position is None and quality_allowed and not self.await_entry_ack:
                self.pending_entry_for = index + 1

        if position is not None:
            self.pending_entry_for = None
            if exit_signal and not self.await_exit_ack:
                self.pending_natural_exit_for = index + 1
            if (self.arm2 and not self.await_exit_ack and self.gross_entry_stop_floor is None
                    and self.arm_at_next_open is None
                    and px >= dec(position.entry_price) * Decimal("1.02")):
                self.arm_at_next_open = dec(position.entry_price)
        return Event("CLOSE_CONFIRMED", index, px, "next_bar_only")


__all__ = ["Position", "Event", "EntryEventCoordinator"]
