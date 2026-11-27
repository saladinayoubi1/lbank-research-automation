"""Process-local cache for existing offline FX bar builder. No execution authority."""
from collections import OrderedDict
from nexus_fx_quote_research import QuoteWindow, _integer, _require
from nexus_fx_bars_research import BarGrid, build_closed_bars


class ClosedBarCache:
    """Reuse only inside one immutable, validated QuoteWindow.

    A new window (even with the same source ID) requires a new cache.
    Key is exact grid and cutoff; no reuse across revisions or future cutoffs.
    Bounded LRU; failures are never cached. Use one instance per serial worker.
    No persistence, strategy state, account state or cross-thread sharing.
    """
    def __init__(self, window, *, capacity=16):
        _require(type(window) is QuoteWindow, "validated quote window required")
        _integer(capacity, "capacity")
        _require(1 <= capacity <= 32, "cache capacity outside bound")
        self._window = window
        self._capacity = capacity
        self._entries = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, window, grid, as_of_ms):
        _require(window is self._window, "cache belongs to another quote window")
        _require(type(grid) is BarGrid, "bar grid required")
        _integer(as_of_ms, "cutoff")
        _require(window.start_ms <= as_of_ms <= window.end_ms, "cutoff outside window")
        key = (grid, as_of_ms)
        if key in self._entries:
            self._hits += 1
            self._entries.move_to_end(key)
            return self._entries[key]
        value = build_closed_bars(window, grid, as_of_ms)
        self._misses += 1
        self._entries[key] = value
        if len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
        return value

    @property
    def stats(self):
        return (self._hits, self._misses, len(self._entries))
