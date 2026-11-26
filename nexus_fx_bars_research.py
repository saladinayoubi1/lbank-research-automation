"""Offline NEXUS closed quote bars; no signal generation or execution authority."""
from dataclasses import dataclass
from decimal import Decimal, Context, localcontext
from nexus_fx_quote_research import QuoteWindow, _require, _integer, quote_digest


@dataclass(frozen=True)
class BarGrid:
    duration_ms: int
    anchor_ms: int
    price_basis: str

    def __post_init__(self):
        _integer(self.duration_ms, "duration")
        _integer(self.anchor_ms, "anchor")
        _require(self.duration_ms > 0 and self.anchor_ms < self.duration_ms, "invalid bar grid")
        _require(self.price_basis in ("BID", "ASK", "MID"), "explicit price basis required")


@dataclass(frozen=True)
class ClosedBar:
    start_ms: int
    end_ms: int
    available_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    count: int
    first_tick_ms: int
    last_tick_ms: int
    digest: str


@dataclass(frozen=True)
class BarSeries:
    grid: BarGrid
    as_of_ms: int
    observed_through_ms: int
    source_id: str
    source_revision: str
    instrument: object
    prefix_sha256: str
    bars: tuple
    missing_starts: tuple
    research_only: bool = True


def build_closed_bars(window, grid, as_of_ms):
    """Half-open bars [start,end); no synthetic empty bars or partial edges.

    A bar is available only once an observed quote at or after its end is
    available. That quote's price never contributes to the preceding bar.
    Missing buckets are explicit; callers must not bridge them silently.
    The prefix digest excludes every quote later than the decision cutoff.
    Source completeness and broker bar conventions are not inferred.
    """
    _require(type(window) is QuoteWindow and type(grid) is BarGrid, "bound quote window and grid required")
    _integer(as_of_ms, "cutoff")
    _require(window.start_ms <= as_of_ms <= window.end_ms, "cutoff outside window")
    prefix = tuple(t for t in window.ticks if t.time_ms <= as_of_ms)
    through = prefix[-1].time_ms
    width, anchor = grid.duration_ms, grid.anchor_ms
    first = anchor + ((window.start_ms - anchor + width - 1) // width) * width
    _require(max(0, (through - first) // width) <= 100000, "bar count bound exceeded")
    bars, missing = [], []
    i = 0
    while i < len(prefix) and prefix[i].time_ms < first:
        i += 1
    with localcontext(Context(prec=96)):
        start = first
        while start + width <= through:
            end = start + width
            j = i
            while j < len(prefix) and prefix[j].time_ms < end:
                j += 1
            if j == i:
                missing.append(start)
            else:
                group = prefix[i:j]
                if grid.price_basis == "BID":
                    prices = [t.bid for t in group]
                elif grid.price_basis == "ASK":
                    prices = [t.ask for t in group]
                else:
                    prices = [(t.bid + t.ask) / 2 for t in group]
                bars.append(ClosedBar(start, end, prefix[j].time_ms, prices[0],
                                      max(prices), min(prices), prices[-1], len(group),
                                      group[0].time_ms, group[-1].time_ms, quote_digest(group)))
            i = j
            start = end
    return BarSeries(grid, as_of_ms, through, window.source_id, window.source_revision,
                     window.instrument, quote_digest(prefix), tuple(bars), tuple(missing))


def contiguous_suffix(series, count):
    """Return the requested closed lookback or reject insufficient/gapped history."""
    _require(type(series) is BarSeries and type(count) is int and count > 0, "invalid lookback")
    _require(len(series.bars) >= count, "insufficient closed bars")
    bars = series.bars[-count:]
    expected_end = series.grid.anchor_ms + ((series.observed_through_ms -
                   series.grid.anchor_ms) // series.grid.duration_ms) * series.grid.duration_ms
    _require(bars[-1].end_ms == expected_end, "missing most recent closed bar")
    _require(all(a.end_ms == b.start_ms for a,b in zip(bars,bars[1:])), "gapped lookback")
    _require(all(b.available_ms <= series.as_of_ms for b in bars), "unavailable bar")
    return bars
